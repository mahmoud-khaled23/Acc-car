"""Damage assessments router — upload images, run the cost pipeline, serve results."""
from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse

from .. import mappers
from ..config import Settings
from ..dependencies import get_settings
from ..models import create_damage, get_damage, list_damage, update_damage
from ..services import damage_service

router = APIRouter(prefix="/api/damage-assessments", tags=["damage"])

IN_PROGRESS_STATUSES = {"processing", "estimating"}


def _require(db_path: str, assessment_id: str) -> dict:
    record = get_damage(db_path, assessment_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Assessment not found")
    return record


def _image_urls(assessment_id: str, record: dict) -> list[str]:
    return [
        f"/api/damage-assessments/{assessment_id}/images/{Path(p).name}"
        for p in record.get("images", [])
    ]


def _record(db_path: str, assessment_id: str) -> dict:
    record = _require(db_path, assessment_id)
    result = record.get("result")
    if isinstance(result, dict):
        result = dict(result)
        result["status"] = record.get("status", "")
        result["error"] = record.get("error") or None
        result["imageUrls"] = _image_urls(assessment_id, record)
        return result

    # Not processed yet (queued/processing/failed) — send what is known.
    return mappers.damage_to_record(
        record,
        image_urls=_image_urls(assessment_id, record),
        vehicle_info=record.get("vehicle_info") or {},
    )


def _run_assessment(assessment_id: str, db_path: str, settings: Settings) -> None:
    record = get_damage(db_path, assessment_id)
    if record is None:
        return
    image_paths = record.get("images", [])
    vehicle_info = record.get("vehicle_info", {})
    update_damage(db_path, assessment_id, {"status": "processing"})
    try:
        result = damage_service.run_damage_assessment(
            image_paths=image_paths,
            vehicle_info=vehicle_info,
            assessment_id=assessment_id,
            settings=settings,
        )
        update_damage(
            db_path,
            assessment_id,
            {"status": "completed", "result": result},
        )
    except Exception as exc:  # noqa: BLE001 - surfaced to the UI as status=failed
        update_damage(db_path, assessment_id, {"status": "failed", "error": str(exc)})


@router.get("")
@router.get("/")
def list_assessments(settings: Settings = Depends(get_settings)):
    records, _ = list_damage(str(settings.db_path), limit=100)
    return [_record(str(settings.db_path), record["id"]) for record in records]


@router.post("", status_code=status.HTTP_201_CREATED)
@router.post("/", status_code=status.HTTP_201_CREATED)
def create_assessment(body: dict, settings: Settings = Depends(get_settings)):
    assessment_id = str(uuid.uuid4())
    data = {
        "status": "created",
        "vehicle_info": {
            "make": body.get("make", ""),
            "model": body.get("model", ""),
            "year": body.get("year", 0),
            "tier": body.get("tier", "mid"),
            "color": body.get("color", ""),
            "currency": body.get("currency", "EGP"),
        },
        "images": [],
        "corrections": [],
    }
    record = create_damage(str(settings.db_path), assessment_id, data)
    return mappers.damage_to_record(record, vehicle_info=data["vehicle_info"])


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_and_run(
    images: list[UploadFile] = File(...),
    make: str = Form(""),
    model: str = Form(""),
    year: int = Form(0),
    color: str = Form(""),
    mileage: int | None = Form(None),
    vin: str = Form(""),
    repair_location: str = Form(""),
    tier: str = Form("mid"),
    currency: str = Form("EGP"),
    settings: Settings = Depends(get_settings),
):
    """One-shot create + upload + start estimation (used by the UI)."""
    assessment_id = str(uuid.uuid4())
    vehicle_info = {
        "make": make,
        "model": model,
        "year": year,
        "color": color,
        "mileage": mileage,
        "vin": vin or None,
        "repair_location": repair_location,
        "tier": tier,
        "currency": currency,
    }
    create_damage(
        str(settings.db_path),
        assessment_id,
        {"status": "created", "vehicle_info": vehicle_info, "images": [], "corrections": []},
    )

    dest_dir = Path(settings.data_dir) / "damage" / assessment_id / "images"
    dest_dir.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    for uploaded in images:
        safe_name = f"{uuid.uuid4().hex}_{Path(uploaded.filename or 'image.jpg').name}"
        target = dest_dir / safe_name
        with open(target, "wb") as handle:
            shutil.copyfileobj(uploaded.file, handle)
        saved.append(str(target))

    update_damage(str(settings.db_path), assessment_id, {"images": saved, "status": "queued"})

    # The estimator UI loads the finished report straight after this call, so
    # run the pipeline inline instead of in a background task.
    _run_assessment(assessment_id, str(settings.db_path), settings)
    return _record(str(settings.db_path), assessment_id)


@router.post("/{assessment_id}/images")
async def upload_images(
    assessment_id: str,
    files: list[UploadFile] | None = File(None),
    images: list[UploadFile] | None = File(None),
    settings: Settings = Depends(get_settings),
):
    record = _require(str(settings.db_path), assessment_id)
    uploads = (files or []) + (images or [])
    if not uploads:
        raise HTTPException(status_code=400, detail="No images were provided")

    dest_dir = Path(settings.data_dir) / "damage" / assessment_id / "images"
    dest_dir.mkdir(parents=True, exist_ok=True)

    saved = list(record.get("images", []))
    for uploaded in uploads:
        safe_name = f"{uuid.uuid4().hex}_{Path(uploaded.filename or 'image.jpg').name}"
        target = dest_dir / safe_name
        with open(target, "wb") as handle:
            shutil.copyfileobj(uploaded.file, handle)
        saved.append(str(target))

    update_damage(str(settings.db_path), assessment_id, {"images": saved})
    return {"message": f"{len(uploads)} image(s) uploaded", "images": saved}


@router.post("/{assessment_id}/estimate")
def trigger_estimate(
    assessment_id: str,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
):
    record = _require(str(settings.db_path), assessment_id)
    if record.get("status") in IN_PROGRESS_STATUSES:
        raise HTTPException(status_code=409, detail=f"Assessment already running ({record['status']})")
    if not record.get("images"):
        raise HTTPException(status_code=400, detail="Upload at least one image before estimating")

    background_tasks.add_task(
        _run_assessment,
        assessment_id=assessment_id,
        db_path=str(settings.db_path),
        settings=settings,
    )
    return {"status": "processing", "message": "Damage assessment started"}


@router.post("/{assessment_id}/corrections")
def apply_corrections(
    assessment_id: str,
    corrections: list[dict],
    settings: Settings = Depends(get_settings),
):
    """Record reviewer corrections (kept on the record and reflected in the UI)."""
    record = _require(str(settings.db_path), assessment_id)
    current = list(record.get("corrections", []))
    current.extend(corrections)
    update_damage(str(settings.db_path), assessment_id, {"corrections": current})

    result = record.get("result")
    if isinstance(result, dict) and result.get("damagedParts"):
        by_id = {str(c.get("id")): c for c in corrections if isinstance(c, dict)}
        for part in result["damagedParts"]:
            correction = by_id.get(str(part.get("id")))
            if correction:
                part.update({k: v for k, v in correction.items() if k != "id"})
                part["source"] = "user"
        update_damage(str(settings.db_path), assessment_id, {"result": result})

    return _record(str(settings.db_path), assessment_id)


@router.get("/{assessment_id}")
def get_assessment(assessment_id: str, settings: Settings = Depends(get_settings)):
    return _record(str(settings.db_path), assessment_id)


@router.get("/{assessment_id}/images/{filename}")
def get_image(assessment_id: str, filename: str, settings: Settings = Depends(get_settings)):
    path = Path(settings.data_dir) / "damage" / assessment_id / "images" / Path(filename).name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(path)
