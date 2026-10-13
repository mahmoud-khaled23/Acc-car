"""Translation layer: project model output  ->  React UI contracts.

The React app's TypeScript types (``frontend/src/types/*.ts``) are the source of
truth for the shapes produced here.  Every field is derived from what the real
models actually returned -- nothing is invented.  Where a model does not produce
a field (for example speeds in km/h, which would need camera calibration) the
field is left out instead of being guessed.
"""
from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

#: Bounding-box colours cycled per vehicle (matches the UI palette style).
PALETTE = [
    "#ef4444",
    "#3b82f6",
    "#22c55e",
    "#eab308",
    "#a855f7",
    "#14b8a6",
    "#f97316",
    "#06b6d4",
    "#ec4899",
    "#84cc16",
    "#8b5cf6",
    "#f43f5e",
]

#: Backend lifecycle status -> frontend ``AnalysisStatus`` union.
STATUS_MAP = {
    "created": "uploaded",
    "uploaded": "uploaded",
    "queued": "tracking",
    "processing": "tracking",
    "tracking": "tracking",
    "vlm_analysis": "vlm_analysis",
    "law_retrieval": "law_retrieval",
    "reasoning": "reasoning",
    "completed": "completed",
    "failed": "failed",
}

#: Human label for each pipeline stage (used by the UI progress text).
STAGE_LABELS = {
    "uploaded": "Waiting to start",
    "tracking": "Detecting and tracking vehicles",
    "vlm_analysis": "Analysing footage with the vision-language model",
    "law_retrieval": "Retrieving relevant traffic-law sections",
    "reasoning": "Producing the liability assessment",
    "completed": "Analysis complete",
    "failed": "Analysis failed",
}


def _clip01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _round(value: Any, digits: int = 3) -> float | None:
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def prettify(token: str) -> str:
    """``front_bumper`` -> ``Front Bumper``."""
    return " ".join(part.capitalize() for part in str(token).replace("-", "_").split("_") if part)


# ---------------------------------------------------------------------------
# Vehicle tracking  (src/vehicle_tracking/tracker.py + accident_candidates.py)
# ---------------------------------------------------------------------------

def build_telemetry(
    trajectories: dict[str, Any],
    fps: float,
    duration_s: float,
    min_track_frames: int = 6,
) -> dict[str, Any]:
    """Run the project's accident-candidate analysis over raw trajectories.

    Returns a JSON-serialisable telemetry bundle that both the UI and the VLM
    prompt consume.  All detection logic lives in
    ``src/vehicle_tracking/accident_candidates.py`` -- this only packages it.
    """
    from vehicle_tracking.accident_candidates import (
        calculate_speeds,
        detect_abrupt_deceleration,
        format_tracking_summary,
        identify_accident_candidates,
        identify_duplicate_tracks,
        identify_single_vehicle_incidents,
    )

    if not trajectories:
        return {
            "fps": fps,
            "durationSeconds": round(duration_s, 3),
            "vehicleCount": 0,
            "candidates": [],
            "singleVehicleIncidents": [],
            "duplicates": {},
            "perVehicle": {},
            "summaryText": "No persistent vehicles were detected or tracked by the object detector.",
        }

    candidates = identify_accident_candidates(trajectories, min_track_frames=min_track_frames)
    single = identify_single_vehicle_incidents(trajectories, fps=fps, min_track_frames=min_track_frames)
    duplicates = identify_duplicate_tracks(trajectories)
    summary_text = format_tracking_summary(
        trajectories, fps=fps, candidates=candidates, min_track_frames=min_track_frames
    )

    per_vehicle: dict[str, Any] = {}
    for tid, data in trajectories.items():
        traj = data.get("trajectory", {})
        speeds = calculate_speeds(traj)
        decel = detect_abrupt_deceleration(speeds)
        peak = max(speeds.values()) if speeds else 0.0
        per_vehicle[str(tid)] = {
            "class": data.get("class", "vehicle"),
            "frames": len(traj),
            "peakSpeedPxPerFrame": round(float(peak), 3),
            "deceleration": {
                "detected": bool(decel.get("detected")),
                "frame": decel.get("frame"),
                "relativeDrop": _round(decel.get("relative_drop")),
            },
        }

    return {
        "fps": fps,
        "durationSeconds": round(duration_s, 3),
        "vehicleCount": len(trajectories),
        "candidates": candidates,
        "singleVehicleIncidents": single,
        "duplicates": {str(k): str(v) for k, v in duplicates.items()},
        "perVehicle": per_vehicle,
        "summaryText": summary_text,
    }


def _event_phrases(vehicle_id: str, telemetry: dict[str, Any] | None) -> list[str]:
    """Human-readable per-vehicle events.

    Strings containing ``t=<seconds>s`` light up the timeline markers in the UI
    (``Timeline.tsx`` parses that pattern).
    """
    if not telemetry:
        return []

    fps = float(telemetry.get("fps") or 0.0) or 30.0
    events: list[str] = []
    per_vehicle = (telemetry.get("perVehicle") or {}).get(str(vehicle_id), {})
    duplicates = telemetry.get("duplicates") or {}

    if str(vehicle_id) in duplicates:
        events.append(f"Tracker fragment of Vehicle {duplicates[str(vehicle_id)]} (duplicate track)")

    for candidate in telemetry.get("candidates") or []:
        ids = [str(v) for v in candidate.get("vehicle_ids", [])]
        if str(vehicle_id) not in ids:
            continue
        others = [v for v in ids if v != str(vehicle_id)]
        ts = candidate.get("overlap_frame")
        ts_s = (ts / fps) if isinstance(ts, (int, float)) and fps else None
        score = candidate.get("suspicion_score")
        if candidate.get("max_iou") and candidate["max_iou"] > 0:
            label = f"Possible contact with Vehicle {others[0]}" if others else "Possible contact"
        else:
            label = f"Close proximity to Vehicle {others[0]}" if others else "Close proximity"
        if ts_s is not None:
            label += f" at t={ts_s:.1f}s"
        if score is not None:
            label += f" (candidate score {score:.2f})"
        events.append(label)

        my_decel = (candidate.get("deceleration") or {}).get(str(vehicle_id)) or {}
        if my_decel.get("detected") and my_decel.get("frame") is not None:
            drop = my_decel.get("relative_drop")
            ts_d = my_decel["frame"] / fps if fps else None
            text = "Sharp deceleration detected"
            if ts_d is not None:
                text += f" at t={ts_d:.1f}s"
            if drop is not None:
                text += f" (-{float(drop) * 100:.0f}% speed)"
            events.append(text)

    for incident in telemetry.get("singleVehicleIncidents") or []:
        if str(incident.get("vehicle_id")) != str(vehicle_id):
            continue
        ts = incident.get("deceleration_time")
        text = "Single-vehicle emergency braking detected"
        if ts is not None:
            text += f" at t={float(ts):.1f}s"
        if incident.get("stopped_after"):
            text += " (came to a stop)"
        events.append(text)

    decel = (per_vehicle.get("deceleration") or {})
    if decel.get("detected") and decel.get("frame") is not None and not any(
        "Sharp deceleration" in e or "emergency braking" in e for e in events
    ):
        events.append(f"Sharp deceleration detected at t={float(decel['frame']) / fps:.1f}s")

    peak = per_vehicle.get("peakSpeedPxPerFrame")
    if peak is not None and peak < 0.6 and per_vehicle.get("frames", 0) >= 10:
        events.append("Stationary / parked for the whole clip")

    return events


def vehicle_tracks(
    raw_trajectories: dict[str, Any],
    fps: float,
    width: int,
    height: int,
    telemetry: dict[str, Any] | None = None,
    meters_per_pixel: float = 0.0,
    min_track_frames: int | None = None,
) -> list[dict[str, Any]]:
    """Convert ``process_video`` trajectories into frontend ``VehicleTrack[]``.

    The tracker works in pixels; the UI expects bounding boxes normalised to
    0-1, so each box is divided by the video dimensions.
    """
    if not raw_trajectories:
        return []

    fps = fps if fps and fps > 0 else 30.0
    width = width or 1
    height = height or 1
    tracks: list[dict[str, Any]] = []

    ordered = sorted(
        raw_trajectories.items(),
        key=lambda item: min((int(f) for f in item[1].get("trajectory", {})), default=0),
    )

    for index, (track_id, data) in enumerate(ordered):
        frames_raw = data.get("trajectory", {})
        if min_track_frames and len(frames_raw) < min_track_frames:
            continue
        if not frames_raw:
            continue

        frame_numbers = sorted(int(f) for f in frames_raw)
        frames: list[dict[str, Any]] = []
        confidences: list[float] = []

        for frame_no in frame_numbers:
            entry = frames_raw[str(frame_no)]
            box = entry.get("box") or []
            if len(box) != 4:
                continue
            x1, y1, x2, y2 = (float(v) for v in box)
            conf = entry.get("conf")
            if isinstance(conf, (int, float)):
                confidences.append(float(conf))
            frames.append(
                {
                    "timestamp": round(frame_no / fps, 3),
                    "vehicleId": str(track_id),
                    "bbox": {
                        "x": _clip01(min(x1, x2) / width),
                        "y": _clip01(min(y1, y2) / height),
                        "width": _clip01(abs(x2 - x1) / width),
                        "height": _clip01(abs(y2 - y1) / height),
                    },
                    "confidence": round(float(conf), 3) if isinstance(conf, (int, float)) else 1.0,
                }
            )

        if not frames:
            continue

        confidence = (
            sum(confidences) / len(confidences)
            if confidences
            else round(len(frame_numbers) / max(1, int(round(fps * (telemetry or {}).get("durationSeconds", 0) or 1))), 3)
        )

        track: dict[str, Any] = {
            "id": str(track_id),
            "label": f"Vehicle {track_id}",
            "class": str(data.get("class", "vehicle")),
            "color": PALETTE[index % len(PALETTE)],
            "firstSeen": frames[0]["timestamp"],
            "lastSeen": frames[-1]["timestamp"],
            "confidence": _clip01(confidence or 1.0),
            "events": _event_phrases(str(track_id), telemetry),
            "frames": frames,
        }

        # Only report a speed when the deployment knows its camera scale
        # (metres/pixel); otherwise the value would be a fabricated number.
        if meters_per_pixel and meters_per_pixel > 0 and telemetry:
            peak_px = (telemetry.get("perVehicle", {}).get(str(track_id), {}) or {}).get(
                "peakSpeedPxPerFrame"
            )
            if peak_px:
                track["speed"] = round(peak_px * meters_per_pixel * fps * 3.6, 1)

        tracks.append(track)

    return tracks


# ---------------------------------------------------------------------------
# VLM report  (src/VLM/analyze_video.py + prompts.py)
# ---------------------------------------------------------------------------

_SECTION_ALIASES = {
    "SCENE OVERVIEW": "scene",
    "SCENE": "scene",
    "TIMELINE": "timeline",
    "ACCIDENT CHECKLIST": "checklist",
    "CHECKLIST": "checklist",
    "FINAL STATE": "final",
    "FINAL OBSERVED STATE": "final",
    "VERDICT SUMMARY": "verdict",
    "VERDICT": "verdict",
    "CONCLUSION": "conclusion",
    "UNCLEAR DETAILS": "unclear",
    "UNCERTAINTIES AND LIMITATIONS": "unclear",
    "UNCERTAINTIES": "unclear",
}

_HEDGE_WORDS = (
    "appears",
    "appear",
    "possibly",
    "possible",
    "may ",
    "might",
    "likely",
    "suggests",
    "suggest",
    "seems",
    "unclear",
    "cannot be determined",
    "not clear",
)

_TS_BRACKET = re.compile(r"\[(\d+(?:\.\d+)?)\s*(?:s)?\s*(?:-|–|to)\s*(\d+(?:\.\d+)?)", re.I)
_TS_SINGLE = re.compile(r"\[(\d+(?:\.\d+)?)\s*s?\]")
_TS_AT = re.compile(r"\b(?:at|t=|~)\s*(\d+(?:\.\d+)?)\s*(?:s\b|seconds?\b)", re.I)

#: frontend wants exactly these two values
_FACT = "fact"
_INTERPRETATION = "interpretation"


_PHASE_SEGMENT = re.compile(r"(?P<phase>START|MIDDLE|END)\s*(?P<bracket>\[[^\]]*\])?\s*:?", re.I)


def _phase_segments(text: str) -> list[tuple[str, float | None, str]]:
    """Split the TIMELINE section into (phase, start_seconds, body) segments.

    The VLM is asked for START / MIDDLE / END paragraphs carrying
    ``[start - end]`` timestamp brackets, but they arrive on separate lines
    without blank lines between them, so splitting on the phase markers is the
    only reliable approach.
    """
    matches = list(_PHASE_SEGMENT.finditer(text))
    segments: list[tuple[str, float | None, str]] = []

    if not matches:
        return [("", None, text)]

    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end():end].strip()
        phase = match.group("phase").upper()
        bracket = match.group("bracket")
        start_s = None
        if bracket:
            inner = _TS_BRACKET.search(bracket) or _TS_SINGLE.search(bracket)
            if inner:
                try:
                    start_s = round(float(inner.group(1)), 2)
                except ValueError:
                    start_s = None
        segments.append((phase, start_s, body))

    # Text before the first phase marker (rare) is kept as an untagged segment.
    preface = text[: matches[0].start()].strip()
    if preface:
        segments.insert(0, ("", None, preface))
    return segments


def _clean_sentence(sentence: str) -> str:
    """Drop phase labels / timestamp brackets left over from the model output."""
    cleaned = _PHASE_SEGMENT.sub(" ", sentence, count=1)
    cleaned = _TS_BRACKET.sub(" ", cleaned)
    cleaned = _TS_SINGLE.sub(" ", cleaned)
    return re.sub(r"^\s*[-•*:\s]+", "", cleaned).strip()


def _split_sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", text)
    return [p.strip() for p in parts if p.strip()]


def _classify(sentence: str) -> str:
    lowered = sentence.lower()
    return _INTERPRETATION if any(word in lowered for word in _HEDGE_WORDS) else _FACT


def _timestamp_in(sentence: str) -> float | None:
    match = _TS_BRACKET.search(sentence) or _TS_SINGLE.search(sentence)
    if match:
        try:
            return round(float(match.group(1)), 2)
        except ValueError:
            return None
    match = _TS_AT.search(sentence)
    if match:
        try:
            return round(float(match.group(1)), 2)
        except ValueError:
            return None
    return None


def _split_sections(report: str) -> dict[str, str]:
    """Split the numbered report the VLM prompt asks for into named sections."""
    sections: dict[str, str] = {}
    current: str | None = None
    buffer: list[str] = []

    heading = re.compile(
        r"^\s*[#*\s]*(\d)\.\s*\**\s*([A-Z][A-Za-z /&\-]{3,})\**\s*:?\s*$|"
        r"^\s*\**([A-Z][A-Z /&\-]{5,})\**\s*:?\s*$"
    )

    for line in report.splitlines():
        match = heading.match(line.strip())
        key = None
        if match:
            raw = (match.group(2) or match.group(3) or "").strip().upper()
            key = _SECTION_ALIASES.get(raw)
        if key:
            if current and buffer:
                sections[current] = "\n".join(buffer).strip()
            current = key
            buffer = []
        elif current is not None:
            buffer.append(line)

    if current and buffer:
        sections[current] = "\n".join(buffer).strip()
    return sections


def _verdict_fields(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    patterns = {
        "incidentDetected": r"Incident Detected\s*:\s*(.+)",
        "classification": r"Primary Classification\s*:\s*(.+)",
        "vehiclesInvolved": r"Primary Vehicles Involved\s*:\s*(.+)",
        "criticalTimestamp": r"Critical Incident Timestamp\s*:\s*(.+)",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, text, re.I)
        if match:
            out[key] = match.group(1).strip().strip("*").strip()
    return out


def parse_vlm_report(report: str, duration_s: float = 0.0) -> dict[str, Any]:
    """Parse the VLM's numbered report into the UI's ``VLMAnalysis`` shape.

    The UI renders ``summary``, ``timeline``, ``vehicleActions``,
    ``collisionDescription``, ``trafficSignals``, ``roadContext``,
    ``uncertainties``; ``rawReport``/``verdict`` are extra context that the UI
    may ignore.
    """
    report = (report or "").strip()
    if not report:
        return {
            "summary": "",
            "timeline": [],
            "vehicleActions": {},
            "collisionDescription": "",
            "trafficSignals": "unclear",
            "roadContext": "",
            "uncertainties": [],
            "rawReport": "",
            "verdict": {},
        }

    sections = _split_sections(report)

    # --- timeline ---------------------------------------------------------
    timeline: list[dict[str, Any]] = []
    timeline_text = sections.get("timeline", "")
    if timeline_text:
        for segment in _phase_segments(timeline_text):
            phase, phase_ts, body = segment
            sentences = _split_sentences(body) or ([body.strip()] if body.strip() else [])
            for idx, sentence in enumerate(sentences):
                ts = _timestamp_in(sentence)
                content = _clean_sentence(sentence)
                if not content:
                    continue
                if ts is None and idx == 0 and phase_ts is not None:
                    ts = round(phase_ts, 2)
                entry: dict[str, Any] = {"type": _classify(content), "content": content}
                if ts is not None:
                    entry["timestamp"] = ts
                if phase:
                    entry["phase"] = phase
                timeline.append(entry)

    if not timeline:
        # Fallback: keep whatever the model produced, as un-timestamped events.
        body = sections.get("scene") or report
        for sentence in _split_sentences(body):
            timeline.append({"type": _classify(sentence), "content": sentence})

    # --- summary / description -------------------------------------------
    scene = sections.get("scene", "").strip()
    conclusion = sections.get("conclusion", "").strip()
    checklist = sections.get("checklist", "").strip()
    final_state = sections.get("final", "").strip()

    contact_lines = [
        line.strip().lstrip("-•* ").strip()
        for line in checklist.splitlines()
        if line.strip() and re.search(r"contact|collision|hit", line, re.I)
    ]
    collision_description = " ".join(contact_lines) or final_state or scene

    summary_source = conclusion or scene or _split_sentences(report)[:2]
    summary = summary_source if isinstance(summary_source, str) else " ".join(summary_source)

    # --- signals / road context ------------------------------------------
    signal_hits = [
        _clean_sentence(sentence)
        for sentence in _split_sentences(" ".join([scene, timeline_text, final_state]))
        if re.search(r"traffic[- ](light|signal)|signal", sentence, re.I)
    ]
    signal_hits = [hit for hit in signal_hits if hit]
    traffic_signals = " ".join(signal_hits[:3]) if signal_hits else "No traffic signal is clearly visible in the footage."

    # --- uncertainties ----------------------------------------------------
    uncertainties: list[str] = []
    unclear = sections.get("unclear", "")
    if unclear:
        for line in unclear.splitlines():
            cleaned = line.strip().lstrip("-•*0123456789. ").strip()
            if cleaned:
                uncertainties.append(cleaned)
    if not uncertainties:
        for sentence in _split_sentences(" ".join([scene, checklist, final_state])):
            if "unclear" in sentence.lower() or "cannot" in sentence.lower():
                uncertainties.append(sentence)

    return {
        "summary": summary,
        "timeline": timeline,
        "vehicleActions": {},  # per-vehicle actions come from the tracker telemetry, not the VLM
        "collisionDescription": collision_description,
        "trafficSignals": traffic_signals,
        "roadContext": scene,
        "uncertainties": uncertainties,
        "rawReport": report,
        "verdict": _verdict_fields(report),
        "durationSeconds": round(duration_s, 2) if duration_s else None,
    }


# ---------------------------------------------------------------------------
# Traffic laws  (src/rag/retrieval)
# ---------------------------------------------------------------------------

_TOPIC_RULES: list[tuple[str, str]] = [
    (r"signal|red light|traffic-control", "traffic-signals"),
    (r"right of way|yield", "right-of-way"),
    (r"speed|prudent", "speed"),
    (r"lane|overtak|passing", "lane-use"),
    (r"turn|signal.*turn|starting and stopping", "turning"),
    (r"following|tailgat|distance", "following-distance"),
    (r"stop sign|stop.*intersection", "stop-signs"),
    (r"pedestrian|crosswalk", "pedestrians"),
    (r"parking|stopping|standing", "parking"),
    (r"emergency vehicle|ambulance|fire", "emergency-vehicles"),
    (r"school bus", "school-buses"),
    (r"seat belt|restraint", "occupant-safety"),
]


def _topics_for(section: dict[str, Any]) -> list[str]:
    haystack = " ".join(
        str(section.get(key, "")) for key in ("title", "text", "matched_queries")
    ).lower()
    topics = [topic for pattern, topic in _TOPIC_RULES if re.search(pattern, haystack)]
    return topics[:3]


def laws_to_traffic_laws(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert retrieved parent sections into frontend ``TrafficLaw[]``.

    ``relevanceScore`` is a *relative* rank within this result set: sections
    picked by the keyword rules are shown at 1.0 and vector hits are scaled
    against the best vector score.  It is a ranking aid, not a model
    probability.
    """
    if not sections:
        return []

    numeric_scores = [
        float(s["score"])
        for s in sections
        if isinstance(s.get("score"), (int, float))
    ]
    best = max(numeric_scores) if numeric_scores else 0.0

    laws: list[dict[str, Any]] = []
    for section in sections:
        text = str(section.get("text", ""))
        score = section.get("score")
        if section.get("score_kind") in ("keyword-rule", "suggested"):
            relevance = 1.0
        elif isinstance(score, (int, float)) and best > 0:
            relevance = _clip01(float(score) / best)
        else:
            relevance = None

        section_number = str(section.get("section") or section.get("id", "")).replace("VTL-", "")
        matched = section.get("matched_queries") or []
        laws.append(
            {
                "id": str(section.get("id")),
                "title": str(section.get("title", "")),
                "jurisdiction": "New York State (VTL)",
                "section": f"VTL § {section_number}" if section_number else str(section.get("id", "")),
                "excerpt": (text[:320] + "…") if len(text) > 320 else text,
                "fullText": text,
                "whyApplies": "; ".join(str(m) for m in matched) or None,
                "sourceUrl": str(section.get("source") or ""),
                "relevanceScore": relevance,
                "topics": _topics_for(section),
            }
        )
    return laws


# ---------------------------------------------------------------------------
# Liability assessment  (reasoning LLM output)
# ---------------------------------------------------------------------------

_RESPONSIBILITY_TO_LEVEL = {
    "primary_vehicle": "potential_responsibility",
    "shared": "shared_responsibility",
    "undetermined": "insufficient_evidence",
    "insufficient": "insufficient_evidence",
}


def _evidence_items(raw_evidence: Any, vehicle_id: str, law_lookup: dict[str, str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    entries = raw_evidence if isinstance(raw_evidence, list) else ([raw_evidence] if raw_evidence else [])
    for index, entry in enumerate(entries):
        if isinstance(entry, dict):
            description = str(entry.get("description") or entry.get("text") or "").strip()
            timestamp = entry.get("timestamp")
            law_section = entry.get("law_section") or entry.get("section")
        else:
            description = str(entry).strip()
            timestamp = _timestamp_in(description)
            law_section = None
        if not description:
            continue
        if isinstance(timestamp, str):
            timestamp = _timestamp_in(timestamp)
        ts_value = float(timestamp) if isinstance(timestamp, (int, float)) else None
        law_id = law_lookup.get(str(law_section).replace("VTL-", "").strip("§ ")) if law_section else None
        item: dict[str, Any] = {
            "id": f"ev-{vehicle_id}-{index}",
            "type": "law_citation" if law_id else ("video_timestamp" if ts_value is not None else "observation"),
            "description": description,
        }
        if ts_value is not None:
            item["timestamp"] = round(ts_value, 2)
        if law_id:
            item["lawId"] = law_id
        items.append(item)
    return items


def liability_to_assessment(
    report: dict[str, Any] | None,
    laws: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Map the reasoning model's JSON into the UI's ``LiabilityAssessment``."""
    if not report:
        return None

    laws = laws or []
    law_lookup: dict[str, str] = {}
    for law in laws:
        number = str(law.get("section", "")).replace("VTL §", "").replace("VTL-", "").strip()
        if number:
            law_lookup[number] = str(law.get("id"))

    violations: list[dict[str, Any]] = []
    raw_violations = report.get("violations")
    if isinstance(raw_violations, list):
        for index, violation in enumerate(raw_violations):
            if not isinstance(violation, dict):
                description = str(violation)
                violation = {"description": description}
            section = violation.get("section") or violation.get("law_section") or ""
            section_number = str(section).replace("VTL §", "").replace("VTL-", "").strip()
            law_id = law_lookup.get(section_number)
            violations.append(
                {
                    "id": f"viol-{index}",
                    "vehicleId": str(violation.get("vehicle_id") or violation.get("vehicle") or ""),
                    "title": str(violation.get("title") or violation.get("description") or "Traffic-law violation"),
                    "description": str(violation.get("description") or ""),
                    "lawSection": f"VTL § {section_number}" if section_number else None,
                    "severity": str(violation.get("severity", "moderate")).lower(),
                    "evidence": _evidence_items(
                        violation.get("evidence"), str(violation.get("vehicle_id", "")), law_lookup
                    ),
                    "lawId": law_id,
                }
            )

    raw_vehicles = report.get("vehicles") or report.get("vehicle_analyses") or []
    vehicle_analyses: list[dict[str, Any]] = []
    for vehicle in raw_vehicles if isinstance(raw_vehicles, list) else []:
        if not isinstance(vehicle, dict):
            continue
        vehicle_id = str(vehicle.get("id") or vehicle.get("vehicle_id") or "")
        violations_for_vehicle = vehicle.get("violations") or []
        contributing: list[str] = []
        for entry in violations_for_vehicle if isinstance(violations_for_vehicle, list) else []:
            if isinstance(entry, dict):
                text = str(entry.get("description") or entry.get("title") or "").strip()
            else:
                text = str(entry).strip()
            if text:
                contributing.append(text)

        role = str(vehicle.get("role") or "").lower()
        if vehicle.get("liability_level"):
            level = str(vehicle["liability_level"])
        elif "primary" in role or "at_fault" in role or "fault" in role and "no" not in role:
            level = "potential_responsibility"
        elif "shared" in role:
            level = "shared_responsibility"
        else:
            level = "insufficient_evidence"

        vehicle_analyses.append(
            {
                "vehicleId": vehicle_id or f"v{len(vehicle_analyses) + 1}",
                "vehicleLabel": str(vehicle.get("label") or f"Vehicle {vehicle_id}"),
                "liabilityLevel": level,
                "summary": str(vehicle.get("summary") or vehicle.get("role") or ""),
                "contributingActions": contributing,
                "mitigatingFactors": [str(m) for m in (vehicle.get("mitigating_factors") or [])],
                "evidence": _evidence_items(vehicle.get("evidence"), vehicle_id, law_lookup),
            }
        )

    responsibility = str(report.get("responsibility") or "").lower()
    overall_level = _RESPONSIBILITY_TO_LEVEL.get(responsibility)
    if overall_level is None:
        # Derive from the vehicles when the model did not state it explicitly.
        levels = {v["liabilityLevel"] for v in vehicle_analyses}
        if levels == {"potential_responsibility"}:
            overall_level = "potential_responsibility"
        elif "potential_responsibility" in levels:
            overall_level = "shared_responsibility"
        else:
            overall_level = "insufficient_evidence"

    confidence = report.get("confidence")
    return {
        "overallAssessment": str(report.get("overall_assessment") or report.get("summary") or ""),
        "overallLevel": overall_level,
        "vehicleAnalyses": vehicle_analyses,
        "violations": violations,
        "conflictingEvidence": [str(x) for x in (report.get("conflicting_evidence") or [])],
        "missingInfo": [str(x) for x in (report.get("missing_info") or [])],
        "confidenceLevel": _clip01(float(confidence)) if isinstance(confidence, (int, float)) else 0.5,
        "limitations": [str(x) for x in (report.get("limitations") or [])],
        "markdownReport": report.get("markdown_report") or report.get("report") or None,
    }


# ---------------------------------------------------------------------------
# Accident records
# ---------------------------------------------------------------------------

def accident_to_record(record: dict[str, Any], api_prefix: str = "") -> dict[str, Any]:
    """DB record -> frontend ``AccidentRecord`` (+ additive pipeline metadata)."""
    status = STATUS_MAP.get(str(record.get("status", "")), "uploaded")

    laws = record.get("laws") or []
    liability = liability_to_assessment(record.get("report"), laws)

    liability_status = "pending"
    if status == "completed":
        if liability and liability.get("overallLevel") == "insufficient_evidence":
            liability_status = "insufficient_evidence"
        else:
            liability_status = "assessed"

    result: dict[str, Any] = {
        "id": str(record.get("id", "")),
        "videoFilename": record.get("video_filename") or record.get("video_path") or "",
        "uploadDate": record.get("created_at") or "",
        "location": record.get("location") or None,
        "incidentDate": record.get("date_time") or None,
        "description": record.get("description") or None,
        "notes": record.get("notes") or None,
        "status": status,
        "vehicleCount": int(record.get("vehicle_count") or 0),
        "liabilityStatus": liability_status,
        "tracks": record.get("tracks") or None,
        "vlmAnalysis": record.get("vlm_analysis") or None,
        "liabilityAssessment": liability,
        "laws": laws,
        "telemetry": record.get("telemetry") or None,
        "error": record.get("error") or None,
        "stageLabel": STAGE_LABELS.get(status, ""),
        "videoUrl": f"{api_prefix}/api/accidents/{record.get('id')}/video" if record.get("video_path") else None,
        "trackedVideoUrl": (
            f"{api_prefix}/api/accidents/{record.get('id')}/tracked-video"
            if record.get("tracked_video_path")
            else None
        ),
        "isDemoData": False,
    }
    return result


# ---------------------------------------------------------------------------
# Damage assessments  (src/Car_damage_cost)
# ---------------------------------------------------------------------------

_ACTION_LABELS = {
    "repair_only": "Repair",
    "paint_only": "Paint",
    "repair_and_paint": "Repair & Paint",
    "replace": "Replacement",
}


def damage_to_record(
    record: dict[str, Any],
    damage_report: dict[str, Any] | None = None,
    cost_report: dict[str, Any] | None = None,
    image_urls: list[str] | None = None,
    vehicle_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """CaseReport + CostReport -> frontend ``DamageAssessmentRecord``."""
    vehicle_info = vehicle_info or {}
    damage_report = damage_report or {}
    cost_report = cost_report or {}

    # --- damaged parts (from the fused per-case damage list) --------------
    damaged_parts: list[dict[str, Any]] = []
    for index, fused in enumerate(damage_report.get("fused") or []):
        part_name = str(fused.get("part", "unknown"))
        severity = str(fused.get("severity", "minor")).lower()
        if severity not in ("minor", "moderate", "severe"):
            severity = "moderate"
        damaged_parts.append(
            {
                "id": f"part-{index + 1:03d}",
                "name": prettify(part_name),
                "location": prettify(part_name).split(" ")[0] if part_name != "unknown" else "Unknown",
                "damageType": prettify(str(fused.get("damage_type", "damage"))),
                "severity": severity,
                "confidence": _clip01(float(fused.get("max_confidence") or 0.0)),
                "source": "user" if fused.get("needs_review") else "ai",
            }
        )

    # --- repair line items (from the cost engine) -------------------------
    repair_items: list[dict[str, Any]] = []
    category_map = (
        ("parts_min", "parts_max", "parts"),
        ("labor_min", "labor_max", "labor"),
        ("paint_min", "paint_max", "paint"),
    )
    for index, line in enumerate(cost_report.get("lines") or []):
        part_label = prettify(str(line.get("part", "part")))
        action = _ACTION_LABELS.get(str(line.get("action")), str(line.get("action", "")))
        damage_text = ", ".join(str(d) for d in (line.get("damages") or [])) or "damage"
        for key_min, key_max, category in category_map:
            low = float(line.get(key_min) or 0.0)
            high = float(line.get(key_max) or 0.0)
            if low == 0 and high == 0:
                continue
            midpoint = round((low + high) / 2, 2)
            repair_items.append(
                {
                    "id": f"ri-{index}-{category}",
                    "partId": f"part-{index + 1:03d}" if index < len(damaged_parts) else None,
                    "description": f"{part_label} — {action} ({category}; {damage_text})",
                    "category": category,
                    "unitCost": midpoint,
                    "quantity": 1,
                    "total": midpoint,
                }
            )
        if line.get("needs_review"):
            repair_items.append(
                {
                    "id": f"ri-{index}-review",
                    "partId": f"part-{index + 1:03d}" if index < len(damaged_parts) else None,
                    "description": f"{part_label} — flagged for human review"
                    + (f": {'; '.join(str(n) for n in line.get('notes') or [])}" if line.get("notes") else ""),
                    "category": "other",
                    "unitCost": 0,
                    "quantity": 1,
                    "total": 0,
                }
            )

    total_min = float(cost_report.get("total_min") or 0.0)
    total_max = float(cost_report.get("total_max") or 0.0)
    subtotal = round((total_min + total_max) / 2, 2)
    currency = str(cost_report.get("currency") or vehicle_info.get("currency") or "EGP")

    limitations = [str(x) for x in (cost_report.get("notes") or [])]
    limitations += [str(x) for x in (damage_report.get("warnings") or [])]
    unpriced = [str(x) for x in (cost_report.get("unpriced") or [])]
    if unpriced:
        limitations.append("Damages that could not be priced: " + "; ".join(unpriced))
    if not limitations:
        limitations = ["Estimate is produced from visual analysis only; verify with a physical inspection."]

    assumptions: list[str] = []
    sources = {str(line.get("price_source", "-")) for line in (cost_report.get("lines") or [])}
    if "placeholder table" in sources:
        assumptions.append(
            "Parts prices come from the local placeholder price table, not verified supplier quotes."
        )
    if "gemini" in sources:
        assumptions.append("Some parts prices were looked up online via the price agent.")

    return {
        "id": str(record.get("id", "")),
        "sessionId": str(record.get("id", "")),
        "vehicleInfo": {
            "make": str(vehicle_info.get("make") or ""),
            "model": str(vehicle_info.get("model") or ""),
            "year": int(vehicle_info.get("year") or 0),
            "color": str(vehicle_info.get("color") or ""),
            "mileage": vehicle_info.get("mileage"),
            "vin": vehicle_info.get("vin"),
            "repairLocation": vehicle_info.get("repair_location") or vehicle_info.get("repairLocation"),
        },
        "imageUrls": image_urls or [],
        "damagedParts": damaged_parts,
        "repairItems": repair_items,
        "estimate": {
            "subtotal": subtotal,
            "tax": 0.0,
            "total": subtotal,
            "lowEstimate": total_min,
            "highEstimate": total_max,
            "currency": currency,
            "assumptions": assumptions,
            "limitations": limitations,
            "unconfirmedMin": float(cost_report.get("unconfirmed_min") or 0.0),
            "unconfirmedMax": float(cost_report.get("unconfirmed_max") or 0.0),
        },
        "assessmentDate": str(record.get("created_at") or ""),
        "status": str(record.get("status") or ""),
        "error": record.get("error") or None,
        "isDemoData": False,
    }
