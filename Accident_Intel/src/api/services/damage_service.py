"""Damage-assessment service — drives the project's Car_damage_cost pipeline.

Real path: ``src/Car_damage_cost/pipeline.py::analyze_case`` (YOLO-seg damage +
parts models, optional VLM checks) and ``cost_engine.estimate_cost`` for the
repair-cost report.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_project_root = str(Path(__file__).parents[3])            # Accident_Intel/
_src_path = str(Path(__file__).parents[3] / "src")        # Accident_Intel/src
_car_damage_path = str(Path(__file__).parents[3] / "src" / "Car_damage_cost")
for _p in (_project_root, _src_path, _car_damage_path):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from .. import mappers  # noqa: E402


def _missing_file_error(path: str, what: str) -> RuntimeError:
    return RuntimeError(
        f"{what} not found at '{path}'. This repository does not ship model weights or price "
        "tables; copy them into place (see src/Car_damage_cost/README or config.py) or enable "
        "DAMAGE_MOCK=true for a canned response."
    )


def run_damage_assessment(
    image_paths: list[str],
    vehicle_info: dict,
    assessment_id: str,
    settings,
) -> dict:
    """Run the damage pipeline and return the UI's ``DamageAssessmentRecord``."""
    if settings.damage_mock:
        return _mock_assessment(vehicle_info, assessment_id=assessment_id, image_paths=image_paths)

    if not image_paths:
        raise RuntimeError("No images were uploaded for this assessment.")

    try:
        from Car_damage_cost.config import Config
        from Car_damage_cost.cost_engine import estimate_cost, load_tables
        from Car_damage_cost.pipeline import analyze_case
        from Car_damage_cost.schemas import CarInfo
        from Car_damage_cost.yolo_wrapper import YoloSegWrapper
    except ImportError as exc:
        raise RuntimeError(
            "Car_damage_cost is not importable — install its dependencies (ultralytics, "
            f"opencv-python, pydantic, httpx, python-dotenv). Original error: {exc}"
        ) from exc

    cfg = Config.from_env() if hasattr(Config, "from_env") else Config()
    cfg.damage_weights = settings.damage_weights
    cfg.parts_weights = settings.parts_weights
    cfg.prices_path = settings.prices_path
    if settings.gemini_api_key:
        cfg.gemini_api_key = settings.gemini_api_key
        cfg.gemini_model = settings.gemini_model

    for path, what in (
        (cfg.damage_weights, "Damage-segmentation weights"),
        (cfg.parts_weights, "Parts-segmentation weights"),
        (cfg.prices_path, "Price table"),
    ):
        if not Path(path).is_file():
            raise _missing_file_error(path, what)

    damage_model = YoloSegWrapper(
        cfg.damage_weights, conf=cfg.damage_conf, imgsz=cfg.parts_imgsz, class_conf=cfg.class_conf
    )
    parts_model = YoloSegWrapper(cfg.parts_weights, conf=cfg.parts_conf, iou=cfg.parts_iou, imgsz=cfg.parts_imgsz)

    case = analyze_case(
        paths=image_paths,
        damage_model=damage_model,
        parts_model=parts_model,
        vlm=None,                     # VLM severity refinement is opt-in in the project UI
        cfg=cfg,
        case_id=assessment_id,
    )

    car = CarInfo(
        make=str(vehicle_info.get("make") or "Unknown"),
        model=str(vehicle_info.get("model") or "Unknown"),
        year=int(vehicle_info.get("year") or 2020),
        tier=str(vehicle_info.get("tier") or "mid"),
    )
    tables = load_tables(cfg.prices_path)
    price_agent = None
    if settings.gemini_api_key:
        try:
            from Car_damage_cost.price_agent import PriceAgent

            price_agent = PriceAgent(
                api_key=settings.gemini_api_key,
                model=cfg.gemini_model,
                cache_path=cfg.price_cache_path,
            )
        except Exception as exc:  # noqa: BLE001 - the estimate works without online prices
            logger.warning("Price agent unavailable (%s); using the offline price table", exc)

    cost = estimate_cost(case.fused, car, tables, price_agent)

    damage_dict = case.model_dump() if hasattr(case, "model_dump") else dict(case)
    cost_dict = cost.model_dump() if hasattr(cost, "model_dump") else dict(cost)

    record = {"id": assessment_id}
    return mappers.damage_to_record(
        record,
        damage_report=damage_dict,
        cost_report=cost_dict,
        image_urls=[f"/api/damage-assessments/{assessment_id}/images/{Path(p).name}" for p in image_paths],
        vehicle_info=vehicle_info,
    )


# ---------------------------------------------------------------------------
# Mock (opt-in via DAMAGE_MOCK=true)
# ---------------------------------------------------------------------------

def _mock_assessment(
    vehicle_info: dict,
    assessment_id: str = "mock",
    image_paths: list[str] | None = None,
) -> dict:
    """Canned assessment used when DAMAGE_MOCK=true.

    The ids and image URLs come from the real request so the stored record is
    consistent with the database row and the served files.
    """
    image_urls = [
        f"/api/damage-assessments/{assessment_id}/images/{Path(p).name}"
        for p in (image_paths or [])
    ]
    return {
        "id": assessment_id,
        "sessionId": assessment_id,
        "imageUrls": image_urls,
        "vehicleInfo": {
            "make": vehicle_info.get("make") or "",
            "model": vehicle_info.get("model") or "",
            "year": vehicle_info.get("year") or 0,
            "color": vehicle_info.get("color") or "",
            "mileage": vehicle_info.get("mileage"),
            "vin": vehicle_info.get("vin"),
            "repairLocation": vehicle_info.get("repair_location"),
        },
        "damagedParts": [
            {
                "id": "part-001",
                "name": "Front Bumper",
                "location": "Front",
                "damageType": "Crack",
                "severity": "moderate",
                "confidence": 0.86,
                "source": "ai",
            },
            {
                "id": "part-002",
                "name": "Hood",
                "location": "Hood",
                "damageType": "Dent",
                "severity": "minor",
                "confidence": 0.78,
                "source": "ai",
            },
        ],
        "repairItems": [
            {
                "id": "ri-0-parts",
                "description": "Front Bumper — Replacement (parts)",
                "category": "parts",
                "unitCost": 2600.0,
                "quantity": 1,
                "total": 2600.0,
            },
            {
                "id": "ri-0-labor",
                "description": "Front Bumper — Replacement (labor)",
                "category": "labor",
                "unitCost": 900.0,
                "quantity": 1,
                "total": 900.0,
            },
        ],
        "estimate": {
            "subtotal": 4500.0,
            "tax": 0.0,
            "total": 4500.0,
            "lowEstimate": 4500.0,
            "highEstimate": 7200.0,
            "currency": "EGP",
            "assumptions": ["Mock assessment — DAMAGE_MOCK=true"],
            "limitations": ["No images analysed; canned response"],
        },
        "assessmentDate": "",
        "status": "completed",
        "isDemoData": False,
    }
