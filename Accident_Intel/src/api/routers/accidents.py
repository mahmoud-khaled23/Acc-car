"""Accidents router — upload, run the pipeline, and serve results to the UI."""
from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse

from .. import mappers
from ..config import Settings
from ..dependencies import get_settings
from ..models import create_accident, delete_accident, get_accident, list_accidents, update_accident
from ..services import accident_service

router = APIRouter(prefix="/api/accidents", tags=["accidents"])

IN_PROGRESS_STATUSES = {"tracking", "vlm_analysis", "law_retrieval", "reasoning", "processing"}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _require(db_path: str, accident_id: str) -> dict:
    record = get_accident(db_path, accident_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Accident not found")
    return record


def _record(db_path: str, accident_id: str, settings: Settings) -> dict:
    return mappers.accident_to_record(_require(db_path, accident_id))


def _start_analysis(accident_id: str, record: dict, background_tasks: BackgroundTasks, settings: Settings) -> None:
    video_path = record.get("video_path") or ""
    if not video_path or not Path(video_path).is_file():
        raise HTTPException(status_code=400, detail="No video uploaded for this accident yet")

    background_tasks.add_task(
        accident_service.run_analysis_pipeline,
        accident_id=accident_id,
        video_path=video_path,
        db_path=str(settings.db_path),
        settings=settings,
    )


# ---------------------------------------------------------------------------
# collection
# ---------------------------------------------------------------------------

@router.get("")
@router.get("/")
def list_accidents_endpoint(
    page: int = 1,
    limit: int = 20,
    page_size: int | None = None,          # accepted for the React client
    status_filter: str | None = None,
    settings: Settings = Depends(get_settings),
):
    limit = page_size or limit
    items, total = list_accidents(str(settings.db_path), page=page, limit=limit, status=status_filter)
    return {
        "items": [mappers.accident_to_record(record) for record in items],
        "total": total,
        "page": page,
        "pageSize": limit,
        "totalPages": max(1, (total + limit - 1) // limit),
    }


@router.post("", status_code=status.HTTP_201_CREATED)
@router.post("/", status_code=status.HTTP_201_CREATED)
def create_accident_endpoint(body: dict, settings: Settings = Depends(get_settings)):
    accident_id = str(uuid.uuid4())
    data = {
        "status": "created",
        "location": body.get("location") or "",
        "date_time": body.get("dateTime") or body.get("date_time") or "",
        "description": body.get("description") or "",
        "notes": body.get("notes") or "",
        "video_filename": "",
    }
    record = create_accident(str(settings.db_path), accident_id, data)
    return mappers.accident_to_record(record)


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_and_create(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    location: str = Form(""),
    incident_date: str = Form(""),
    description: str = Form(""),
    notes: str = Form(""),
    autostart: bool = Form(True),
    settings: Settings = Depends(get_settings),
):
    """One-shot create + upload (+ optionally start analysis) used by the UI."""
    accident_id = str(uuid.uuid4())
    record = create_accident(
        str(settings.db_path),
        accident_id,
        {
            "status": "created",
            "location": location,
            "date_time": incident_date,
            "description": description,
            "notes": notes,
            "video_filename": file.filename or "video.mp4",
        },
    )

    dest_dir = Path(settings.data_dir) / "accidents" / accident_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(file.filename or "video.mp4").suffix or ".mp4"
    video_path = dest_dir / f"video{suffix}"
    with open(video_path, "wb") as handle:
        shutil.copyfileobj(file.file, handle)

    record = update_accident(
        str(settings.db_path),
        accident_id,
        {"status": "uploaded", "video_path": str(video_path)},
    )
    if autostart:
        _start_analysis(accident_id, record, background_tasks, settings)

    return mappers.accident_to_record(record)


# ---------------------------------------------------------------------------
# single accident
# ---------------------------------------------------------------------------

@router.get("/{accident_id}")
def get_accident_endpoint(accident_id: str, settings: Settings = Depends(get_settings)):
    return _record(str(settings.db_path), accident_id, settings)


@router.delete("/{accident_id}")
def delete_accident_endpoint(accident_id: str, settings: Settings = Depends(get_settings)):
    record = _require(str(settings.db_path), accident_id)
    deleted = delete_accident(str(settings.db_path), accident_id)
    if not deleted:
        raise HTTPException(status_code=500, detail="Could not delete the accident")

    directory = Path(settings.data_dir) / "accidents" / accident_id
    if directory.is_dir():
        shutil.rmtree(directory, ignore_errors=True)
    return {"deleted": True, "id": accident_id, "hadVideo": bool(record.get("video_path"))}


@router.post("/{accident_id}/analyze")
def trigger_analysis(
    accident_id: str,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
):
    record = _require(str(settings.db_path), accident_id)
    if record.get("status") in IN_PROGRESS_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"Analysis already in progress (status: {record['status']})",
        )
    _start_analysis(accident_id, record, background_tasks, settings)
    return {"status": "processing", "message": "Analysis pipeline started"}


@router.post("/{accident_id}/video")
async def upload_video(
    accident_id: str,
    file: UploadFile = File(...),
    settings: Settings = Depends(get_settings),
):
    record = _require(str(settings.db_path), accident_id)

    dest_dir = Path(settings.data_dir) / "accidents" / accident_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(file.filename or "video.mp4").suffix or ".mp4"
    video_path = dest_dir / f"video{suffix}"
    with open(video_path, "wb") as handle:
        shutil.copyfileobj(file.file, handle)

    update_accident(
        str(settings.db_path),
        accident_id,
        {"status": "uploaded", "video_path": str(video_path), "video_filename": file.filename or video_path.name},
    )
    return {"message": "Video uploaded", "path": str(video_path)}


# ---------------------------------------------------------------------------
# results (UI contract)
# ---------------------------------------------------------------------------

@router.get("/{accident_id}/tracking")
def get_tracking(accident_id: str, settings: Settings = Depends(get_settings)):
    record = _require(str(settings.db_path), accident_id)
    if not record.get("tracks"):
        raise HTTPException(status_code=404, detail="Tracking data is not available yet")
    return record["tracks"]


@router.get("/{accident_id}/telemetry")
def get_telemetry(accident_id: str, settings: Settings = Depends(get_settings)):
    record = _require(str(settings.db_path), accident_id)
    return record.get("telemetry") or {}


@router.get("/{accident_id}/vlm")
def get_vlm(accident_id: str, settings: Settings = Depends(get_settings)):
    record = _require(str(settings.db_path), accident_id)
    analysis = record.get("vlm_analysis")
    if not analysis:
        raise HTTPException(status_code=404, detail="VLM description is not available yet")
    return analysis


@router.get("/{accident_id}/description")
def get_description(accident_id: str, settings: Settings = Depends(get_settings)):
    record = _require(str(settings.db_path), accident_id)
    return {"description": record.get("vlm_description"), "analysis": record.get("vlm_analysis")}


@router.get("/{accident_id}/laws")
def get_laws(accident_id: str, settings: Settings = Depends(get_settings)):
    record = _require(str(settings.db_path), accident_id)
    if not record.get("laws"):
        raise HTTPException(status_code=404, detail="Law retrieval has not run yet")
    return record["laws"]


@router.get("/{accident_id}/report")
def get_report(accident_id: str, settings: Settings = Depends(get_settings)):
    record = _require(str(settings.db_path), accident_id)
    if not record.get("report"):
        raise HTTPException(status_code=404, detail="The reasoning report is not available yet")
    return record["report"]


@router.get("/{accident_id}/liability")
def get_liability(accident_id: str, settings: Settings = Depends(get_settings)):
    record = _require(str(settings.db_path), accident_id)
    assessment = mappers.liability_to_assessment(record.get("report"), record.get("laws") or [])
    if not assessment:
        raise HTTPException(status_code=404, detail="The liability assessment is not available yet")
    return assessment


# ---------------------------------------------------------------------------
# artifacts
# ---------------------------------------------------------------------------

@router.get("/{accident_id}/video")
def get_video(accident_id: str, settings: Settings = Depends(get_settings)):
    record = _require(str(settings.db_path), accident_id)
    path = record.get("video_path")
    if not path or not Path(path).is_file():
        raise HTTPException(status_code=404, detail="Video file not found")
    return FileResponse(path, media_type="video/mp4", filename=Path(path).name)


@router.get("/{accident_id}/tracked-video")
def get_tracked_video(accident_id: str, settings: Settings = Depends(get_settings)):
    record = _require(str(settings.db_path), accident_id)
    path = record.get("tracked_video_path")
    if not path or not Path(path).is_file():
        raise HTTPException(status_code=404, detail="Annotated video not found")
    return FileResponse(path, media_type="video/mp4", filename=Path(path).name)


@router.get("/{accident_id}/trajectories")
def get_trajectories(accident_id: str, settings: Settings = Depends(get_settings)):
    record = _require(str(settings.db_path), accident_id)
    path = record.get("trajectories_path")
    if not path or not Path(path).is_file():
        raise HTTPException(status_code=404, detail="Trajectory file not found")
    return FileResponse(path, media_type="application/json", filename=Path(path).name)
