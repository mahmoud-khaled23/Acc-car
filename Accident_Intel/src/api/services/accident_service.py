"""Accident analysis orchestration pipeline.

Stages (mirroring the project's architecture):

1. **tracking**  — YOLO11x + BoT-SORT → trajectories + annotated video + telemetry
2. **vlm**       — Qwen2-VL grounded report (telemetry + event-triggered sampling)
3. **laws**      — VTL retrieval (keyword anchors + dense/BM25 hybrid)
4. **reasoning** — Groq model produces the citation-checked assessment
"""
from __future__ import annotations

import logging
from pathlib import Path

from .. import mappers
from . import law_service, reasoning_service, tracking_service, vlm_service

logger = logging.getLogger(__name__)


def _accident_dir(settings, accident_id: str) -> Path:
    directory = Path(settings.data_dir) / "accidents" / accident_id
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def run_analysis_pipeline(accident_id: str, video_path: str, db_path: str, settings) -> None:
    """Background task: tracking → VLM → law retrieval → reasoning."""
    from ..models import update_accident

    try:
        out_dir = _accident_dir(settings, accident_id)

        # 1 ── vehicle tracking ------------------------------------------------
        update_accident(db_path, accident_id, {"status": "tracking"})
        tracking = tracking_service.run_tracking(
            video_path, accident_id, str(out_dir), settings, mock=settings.tracking_mock
        )
        update_accident(
            db_path,
            accident_id,
            {
                "tracks": tracking["tracks"],
                "telemetry": tracking["telemetry"],
                "vehicle_count": tracking["vehicleCount"],
                "fps": tracking["fps"],
                "video_width": tracking["width"],
                "video_height": tracking["height"],
                "tracked_video_path": tracking.get("trackedVideoPath"),
                "trajectories_path": tracking.get("trajectoriesPath"),
            },
        )

        # 2 ── VLM report ------------------------------------------------------
        update_accident(db_path, accident_id, {"status": "vlm_analysis"})
        report_text, _summary = vlm_service.analyze_video(
            video_path, accident_id, settings, tracking_result=tracking
        )
        vlm_analysis = vlm_service.parse_report(report_text, tracking.get("durationSeconds", 0.0))
        update_accident(
            db_path,
            accident_id,
            {"vlm_description": report_text, "vlm_analysis": vlm_analysis},
        )

        # 3 ── law retrieval ---------------------------------------------------
        update_accident(db_path, accident_id, {"status": "law_retrieval"})
        facts = reasoning_service.extract_facts(report_text, settings)
        sections = law_service.retrieve_laws(
            description=report_text,
            out_dir=str(settings.rag_out_dir),
            settings=settings,
            extra_queries=(facts or {}).get("queries"),
            extra_sections=(facts or {}).get("relevant_sections"),
        )
        laws = mappers.laws_to_traffic_laws(sections)
        update_accident(db_path, accident_id, {"laws": laws, "facts": facts})

        # 4 ── reasoning -------------------------------------------------------
        update_accident(db_path, accident_id, {"status": "reasoning"})
        report = reasoning_service.analyze_accident(
            description=report_text,
            tracking_summary=tracking["telemetry"].get("summaryText"),
            laws=sections,
            settings=settings,
            facts=facts,
        )
        update_accident(db_path, accident_id, {"report": report, "status": "completed"})
        logger.info("Analysis pipeline completed for accident %s", accident_id)

    except Exception as exc:  # noqa: BLE001 - surface the failure in the UI
        logger.exception("Analysis pipeline failed for accident %s", accident_id)
        try:
            update_accident(db_path, accident_id, {"status": "failed", "error": str(exc)})
        except Exception:  # pragma: no cover
            pass
