"""Vehicle tracking service — runs the project's YOLO11x + BoT-SORT tracker.

Real path:  ``src/vehicle_tracking/tracker.py::process_video`` plus the
accident-candidate analysis in ``src/vehicle_tracking/accident_candidates.py``.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_project_root = str(Path(__file__).parents[3])
_src_path = str(Path(__file__).parents[3] / "src")
for _p in (_project_root, _src_path):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from .. import mappers  # noqa: E402


def _video_metadata(video_path: str) -> tuple[float, float, int, int]:
    """(fps, duration_s, width, height).

    Frame dimensions are needed to normalise boxes for the UI overlay; the
    project's ``get_video_info`` only returns (duration, fps), so OpenCV is
    read directly here.
    """
    import cv2  # lazy: only needed on the tracking path

    cap = cv2.VideoCapture(str(video_path))
    try:
        if not cap.isOpened():
            raise RuntimeError(f"Could not open video: {video_path}")
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        total_frames = float(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    finally:
        cap.release()

    if fps <= 0 or total_frames <= 0:
        raise ValueError(f"Could not read video metadata. Check path: {video_path}")
    return fps, total_frames / fps, width, height


def run_tracking(
    video_path: str,
    accident_id: str,
    output_dir: str,
    settings,
    mock: bool = False,
) -> dict:
    """Track vehicles and package the result for the UI + VLM prompt.

    Returns a dict with the raw trajectories, the UI-shaped tracks, the
    telemetry bundle and the paths of the generated artifacts.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    fps, duration, width, height = 0.0, 0.0, 0, 0
    try:
        fps, duration, width, height = _video_metadata(video_path)
    except Exception as exc:  # pragma: no cover - depends on codec availability
        logger.warning("Could not probe video metadata (%s); continuing with defaults", exc)

    if mock:
        return _mock_tracking(fps, duration, width, height)

    try:
        from vehicle_tracking.tracker import process_video
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "vehicle_tracking is not importable — install the tracking extras "
            f"(ultralytics, supervision, opencv-python). Original error: {exc}"
        ) from exc

    tracked_video = out_dir / f"{accident_id}_tracked.mp4"
    trajectories_json = out_dir / f"{accident_id}_trajectories.json"

    raw = process_video(
        input_path=video_path,
        output_video=str(tracked_video),
        output_json=str(trajectories_json),
        model_path=settings.tracking_model,
        min_track_frames=settings.tracking_min_frames,
    )

    if not fps or fps <= 0:
        fps = 25.0
    if not width or not height:
        # Normalisation needs the frame size: fall back to the largest box seen.
        max_x = max_y = 1.0
        for data in raw.values():
            for entry in data.get("trajectory", {}).values():
                box = entry.get("box") or [0, 0, 1, 1]
                max_x = max(max_x, float(box[2]))
                max_y = max(max_y, float(box[3]))
        width, height = int(max_x), int(max_y)

    telemetry = mappers.build_telemetry(
        raw,
        fps=fps,
        duration_s=duration or (max((int(f) for d in raw.values() for f in d.get("trajectory", {})), default=0) + 1) / fps,
        min_track_frames=settings.tracking_min_frames,
    )

    tracks = mappers.vehicle_tracks(
        raw,
        fps=fps,
        width=width,
        height=height,
        telemetry=telemetry,
        meters_per_pixel=0.0,
        min_track_frames=settings.tracking_min_frames,
    )

    return {
        "rawTrajectories": raw,
        "tracks": tracks,
        "telemetry": telemetry,
        "fps": fps,
        "durationSeconds": telemetry["durationSeconds"],
        "width": width,
        "height": height,
        "videoWidth": width,
        "videoHeight": height,
        "trackedVideoPath": str(tracked_video),
        "trajectoriesPath": str(trajectories_json),
        "vehicleCount": len(tracks),
    }


# ---------------------------------------------------------------------------
# Mock (opt-in via TRACKING_MOCK=true) — kept so the UI can be exercised with
# no GPU and no model weights.
# ---------------------------------------------------------------------------

def _mock_tracking(fps: float, duration: float, width: int, height: int) -> dict:
    fps = fps or 25.0
    duration = duration or 12.0
    width = width or 1280
    height = height or 720

    specs = [
        (1, "car", 0.75, 0.45, 0.06, 0.02),
        (2, "car", 0.20, 0.55, 0.10, 0.01),
        (3, "motorcycle", 0.05, 0.72, 0.14, 0.0),
    ]
    total_frames = int(duration * fps)
    raw: dict[str, dict] = {}
    for track_id, cls, x0, y0, dx, dy in specs:
        trajectory = {}
        for frame in range(0, total_frames, 2):
            t = frame / fps
            x = min(0.9, x0 + dx * t)
            y = min(0.9, y0 + dy * t)
            cx, cy = x * width, y * height
            trajectory[str(frame)] = {
                "center": [cx, cy],
                "box": [cx - 60, cy - 40, cx + 60, cy + 40],
                "conf": 0.9,
            }
        raw[str(track_id)] = {"class": cls, "trajectory": trajectory}

    telemetry = mappers.build_telemetry(raw, fps=fps, duration_s=duration, min_track_frames=1)
    tracks = mappers.vehicle_tracks(
        raw, fps=fps, width=width, height=height, telemetry=telemetry, min_track_frames=1
    )
    return {
        "rawTrajectories": raw,
        "tracks": tracks,
        "telemetry": telemetry,
        "fps": fps,
        "durationSeconds": duration,
        "width": width,
        "height": height,
        "videoWidth": width,
        "videoHeight": height,
        "trackedVideoPath": None,
        "trajectoriesPath": None,
        "vehicleCount": len(tracks),
        "mock": True,
    }
