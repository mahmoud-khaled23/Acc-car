"""VLM video-analysis service — drives the project's Qwen2-VL workflow.

Real path: ``src/VLM/analyze_video.py`` (grounded "paradigm 2": YOLO/BoT-SORT
telemetry + event-triggered 3-phase sampling + Qwen2-VL generation) using the
prompts in ``src/VLM/prompts.py``.
"""
from __future__ import annotations

import logging
import sys
import threading
from argparse import Namespace
from pathlib import Path

logger = logging.getLogger(__name__)

_project_root = str(Path(__file__).parents[3])
_src_path = str(Path(__file__).parents[3] / "src")
for _p in (_project_root, _src_path):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from .. import mappers  # noqa: E402

# Model caching: loading Qwen2-VL takes minutes, so keep it in memory between
# requests.  A lock prevents two background analyses loading it concurrently.
_model_lock = threading.Lock()
_cached_model = None
_cached_processor = None
_cached_model_id: str | None = None


def load_cached_model(settings):
    """Load (once) and return the Qwen2-VL model + processor."""
    global _cached_model, _cached_processor, _cached_model_id

    with _model_lock:
        if _cached_model is None or _cached_model_id != settings.vlm_model_id:
            from VLM.analyze_video import load_model

            logger.info("Loading VLM %s (first call may download weights)…", settings.vlm_model_id)
            _cached_model, _cached_processor = load_model(
                model_id=settings.vlm_model_id,
                load_in_4bit=settings.vlm_load_in_4bit,
                load_in_8bit=settings.vlm_load_in_8bit,
            )
            _cached_model_id = settings.vlm_model_id
        return _cached_model, _cached_processor


def _build_args(settings) -> Namespace:
    """Argparse-compatible namespace for the VLM module's helper functions."""
    return Namespace(
        prompt_mode="json",          # structured accident report (SCENE/TIMELINE/…)
        prompt_file=None,
        n_frames=settings.vlm_n_frames,
        max_new_tokens=settings.vlm_max_tokens,
        model_id=settings.vlm_model_id,
        torch_dtype="auto",
        load_4bit=settings.vlm_load_in_4bit,
        load_8bit=settings.vlm_load_in_8bit,
        repetition_penalty=1.15,
        min_track_frames=settings.tracking_min_frames,
        yolo_model=settings.tracking_model,
        trajectories=None,
        use_annotated_video=True,
        raw_video_only=False,
        smart_sampling=True,
        no_smart_sampling=False,
        auto_trigger=False,
        suspicion_threshold=0.45,
        pre_seconds=1.8,
        impact_seconds=0.5,
        post_seconds=2.0,
        crop_roi=False,
    )


def analyze_video(
    video_path: str,
    accident_id: str,
    settings,
    tracking_result: dict | None = None,
) -> tuple[str, dict | None]:
    """Run the VLM over a video.

    ``tracking_result`` is the output of ``tracking_service.run_tracking``: it
    is fed into the grounded prompt (and re-used so the video is not tracked
    twice).  Returns ``(report_text, tracking_summary)``.
    """
    if settings.vlm_mock:
        return _MOCK_DESCRIPTION, None

    from VLM.analyze_video import run_paradigm_with_tracking

    try:
        fps, duration, _, _ = _probe(video_path)
    except Exception as exc:
        raise RuntimeError(f"Could not read video metadata: {exc}") from exc

    trajectories = (tracking_result or {}).get("rawTrajectories")
    annotated = (tracking_result or {}).get("trackedVideoPath")

    return run_paradigm_with_tracking(
        None,
        None,
        video_path,
        _build_args(settings),
        duration,
        fps,
        model_loader=lambda: load_cached_model(settings),
        precomputed_trajectories=trajectories,
        precomputed_annotated_video=annotated,
    )


def _probe(video_path: str) -> tuple[float, float, int, int]:
    from .tracking_service import _video_metadata

    return _video_metadata(video_path)


def parse_report(report: str, duration_s: float = 0.0) -> dict:
    """Convert the raw VLM report into the UI's ``VLMAnalysis`` contract."""
    return mappers.parse_vlm_report(report, duration_s=duration_s)


# ---------------------------------------------------------------------------
# Mock (opt-in via VLM_MOCK=true)
# ---------------------------------------------------------------------------

_MOCK_DESCRIPTION = """\
1. SCENE OVERVIEW
The video shows an urban intersection with a traffic signal. Three vehicles are visible: a white
sedan (Vehicle ID 1), a dark hatchback (Vehicle ID 2) and a motorcycle (Vehicle ID 3).

2. TIMELINE
START [0.00s - 4.00s]: The white sedan (Vehicle ID 1) approaches the intersection from the north at a
steady speed while the signal for its approach shows green.
MIDDLE [4.00s - 8.00s]: The dark hatchback (Vehicle ID 2) moves out from the kerb and enters the
left lane without an observed indicator. The motorcycle (Vehicle ID 3) follows behind.
END [8.00s - 12.00s]: The sedan (Vehicle ID 1) brakes sharply and stops short of the hatchback.
No physical contact between any vehicles is clearly visible in the sampled frames.

3. ACCIDENT CHECKLIST
- Contact between road users: UNCLEAR - the frames around the closest approach are blurred and the
  vehicles overlap in the image; no visible deformation or debris is observed.
- Hit fixed object or left the road: NO - all tracked vehicles remain on the roadway.
- Person or rider fell down: NO - the rider (Vehicle ID 3) remains upright throughout.
- Abrupt swerve or hard stop: YES - Vehicle ID 1 decelerates sharply near the middle of the clip.
- Vehicle left in abnormal position: NO - all vehicles come to rest in normal lane positions.

4. FINAL STATE
The sedan (Vehicle ID 1) is stationary in the left lane with the hatchback (Vehicle ID 2) stopped
ahead of it. The motorcycle (Vehicle ID 3) has stopped behind the sedan. Traffic continues in the
right lane.

5. VERDICT SUMMARY
- Incident Detected: SUSPECTED
- Primary Classification: Near-Miss
- Primary Vehicles Involved: Vehicle ID 1, Vehicle ID 2
- Critical Incident Timestamp: ~6.40s

6. CONCLUSION
The footage shows a near-miss with hard braking; whether physical contact occurred is unclear from
the sampled frames. The strongest visible evidence is the abrupt emergency deceleration of
Vehicle ID 1 immediately after Vehicle ID 2 changed lane.

7. UNCLEAR DETAILS
Whether the vehicles made physical contact; the state of the traffic signal at the critical moment;
licence plates and driver identities.
"""
