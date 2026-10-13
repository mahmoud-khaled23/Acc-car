"""Accident reasoning service — drives the project's Groq reasoning model.

Real path: the same model and prompt stack as
``src/rag/retrieval/analyze_accident.py`` (Groq OpenAI-compatible endpoint,
default model ``openai/gpt-oss-120b``) — fact extraction first, then a
law-grounded, citation-checked assessment.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_project_root = str(Path(__file__).parents[3])
_src_path = str(Path(__file__).parents[3] / "src")
for _p in (_project_root, _src_path):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_EXTRACT_HINT = (
    "You are a traffic-accident analyst reading a video-analysis report written by a "
    "vision-language model. Return ONLY the JSON object."
)

_ANALYZE_SYSTEM_API = """You are a traffic-law analyst assisting a human reviewer. You receive (1) facts of an
accident produced by a video analysis, and (2) excerpts of traffic law retrieved from a database.

Strict rules:
- Use ONLY the law excerpts provided. Never cite a section that is not in them.
- Cite every point as "VTL § <number>(<subdivision>)".
- If the excerpts do not cover a behavior, say so instead of inventing a rule.
- Do not assume facts that are not in the facts section. List what is missing.
- Distinguish clearly between what the footage shows and what is unclear.
- This is an analysis aid, not a legal judgment.

Return ONLY a JSON object (no markdown fences) with exactly these keys:
{
  "overall_assessment": "3-6 sentence evidence-grounded assessment",
  "responsibility": "primary_vehicle | shared | undetermined",
  "vehicles": [
    {"id": "1", "label": "Vehicle 1", "role": "primary_at_fault | contributing | not_at_fault | unclear",
     "summary": "what this vehicle did and why it matters",
     "violations": [{"section": "1111", "description": "short description", "severity": "minor | moderate | major"}],
     "mitigating_factors": ["..."],
     "evidence": [{"description": "what supports this", "timestamp": 6.4, "law_section": "1111"}]}
  ],
  "violations": [
    {"vehicle_id": "1", "section": "1111", "title": "short title", "description": "why it applies",
     "severity": "minor | moderate | major", "evidence": "short evidence phrase"}
  ],
  "conflicting_evidence": ["..."],
  "missing_info": ["..."],
  "limitations": ["..."],
  "confidence": 0.0,
  "markdown_report": "the same analysis written as a short markdown report with headings"
}

Rules for the JSON:
- "timestamp" values must come from timestamps that appear in the facts; use the closest stated
  timestamp and never invent precise numbers.
- "confidence" is 0.0-1.0 and must reflect the strength of the visible evidence, not the model's
  certainty about the law.
- If the evidence does not establish a collision, say so and mark the classification accordingly.
"""


def _client(settings):
    from openai import OpenAI

    api_key = settings.reasoning_key
    if not api_key:
        raise RuntimeError(
            "No reasoning API key configured. Set GROQ_API_KEY (or OPENAI_API_KEY) in the "
            "environment / .env file, or enable REASONING_MOCK=true."
        )
    return OpenAI(api_key=api_key, base_url=settings.groq_base_url, timeout=settings.reasoning_timeout)


def _chat(settings, system: str, user: str, model: str | None = None) -> str:
    from rag.retrieval.analyze_accident import DEFAULT_MODEL

    client = _client(settings)
    response = client.chat.completions.create(
        model=model or settings.reasoning_model or DEFAULT_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.2,
    )
    return response.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# Step 1 — fact extraction (also feeds law retrieval)
# ---------------------------------------------------------------------------

def extract_facts(description: str, settings) -> dict | None:
    """Use the project's extraction prompt to pull sections + queries.

    Returns ``None`` when no API key is configured or a failure occurs — the
    retrieval stage then simply falls back to its keyword rules.
    """
    if settings.reasoning_mock or not settings.reasoning_key:
        return None

    try:
        from rag.retrieval.analyze_accident import EXTRACT_SYSTEM, build_catalog, parse_json
        from rag.retrieval.index_and_retrieve import load

        parents, _ = load(str(settings.rag_out_dir))
        catalog = build_catalog(parents)
        user = (
            "# SECTION CATALOG\n" + catalog[:12000] + "\n\n"
            "# VIDEO ANALYSIS REPORT (accident description)\n" + description[:16000]
        )
        raw = _chat(settings, EXTRACT_SYSTEM, user)
        return parse_json(raw)
    except Exception as exc:  # noqa: BLE001 - retrieval must still work without the LLM
        logger.warning("Fact extraction failed (%s); falling back to rule-based retrieval", exc)
        return None


# ---------------------------------------------------------------------------
# Step 2 — law-grounded assessment
# ---------------------------------------------------------------------------

def analyze_accident(
    description: str,
    tracking_summary: str | None,
    laws: list[dict],
    settings,
    facts: dict | None = None,
) -> dict:
    """Return a structured liability assessment dict for the UI."""
    if settings.reasoning_mock:
        return dict(_MOCK_REPORT)

    from rag.retrieval.analyze_accident import format_laws, parse_json

    facts_block = json.dumps(facts, indent=2) if facts else description
    laws_block = format_laws(laws) if laws else "(no law excerpts were retrieved)"

    user = (
        "# ACCIDENT FACTS\n" + str(facts_block)[:16000] + "\n\n"
        "# GROUND-TRUTH TRACKING TELEMETRY\n" + (tracking_summary or "(no tracking data)") + "\n\n"
        "# RETRIEVED LAW EXCERPTS\n" + laws_block[:24000] + "\n\n"
        "# RAW VIDEO ANALYSIS REPORT\n" + description[:12000] + "\n\n"
        "# TASK\nProduce the JSON analysis described in the system message."
    )

    raw = _chat(settings, _ANALYZE_SYSTEM_API, user)

    try:
        report = parse_json(raw)
    except Exception as exc:  # noqa: BLE001 - keep the UI usable on malformed output
        logger.warning("Reasoning model returned non-JSON output (%s)", exc)
        report = {
            "overall_assessment": raw,
            "responsibility": "undetermined",
            "vehicles": [],
            "violations": [],
            "conflicting_evidence": [],
            "missing_info": [],
            "limitations": ["The reasoning model returned prose instead of structured JSON; showing the raw text."],
            "confidence": 0.5,
        }

    report.setdefault("limitations", [])
    if not isinstance(report.get("limitations"), list):
        report["limitations"] = [str(report["limitations"])]
    report["analysisSource"] = f"groq:{settings.reasoning_model}"
    return report


# ---------------------------------------------------------------------------
# Mock (opt-in via REASONING_MOCK=true)
# ---------------------------------------------------------------------------

_MOCK_REPORT = {
    "overall_assessment": (
        "The analysis indicates a near-miss with emergency braking: Vehicle 1 decelerated sharply "
        "after Vehicle 2 entered its lane without an observed signal. Whether physical contact "
        "occurred is not established by the sampled frames, so any liability statement must be "
        "treated as provisional."
    ),
    "responsibility": "undetermined",
    "vehicles": [
        {
            "id": "1",
            "label": "Vehicle 1",
            "role": "not_at_fault",
            "summary": "Braked sharply to avoid the lane conflict; no rule violation is visible.",
            "violations": [],
            "mitigating_factors": ["Emergency avoidance manoeuvre"],
            "evidence": [
                {"description": "Sharp deceleration detected", "timestamp": 6.4},
            ],
        },
        {
            "id": "2",
            "label": "Vehicle 2",
            "role": "contributing",
            "summary": "Changed lane without an observed indicator, creating the conflict.",
            "violations": [{"section": "1128", "description": "Moved from lane without safety check", "severity": "moderate"}],
            "mitigating_factors": [],
            "evidence": [{"description": "Lane change without indicator", "timestamp": 5.1}],
        },
    ],
    "violations": [
        {
            "vehicle_id": "2",
            "section": "1128",
            "title": "Driving on roadways laned for traffic",
            "description": "A vehicle shall not move from its lane until the movement can be made safely.",
            "severity": "moderate",
            "evidence": "Lane change into the path of Vehicle 1 without signal",
        }
    ],
    "conflicting_evidence": ["Contact between the vehicles could not be confirmed from the frames"],
    "missing_info": ["Traffic-signal state at the critical moment", "Statements from the drivers"],
    "limitations": ["Mock assessment — REASONING_MOCK=true", "Video resolution limits speed estimation"],
    "confidence": 0.5,
    "markdown_report": "## Mock assessment\n\nThis is a canned response used when `REASONING_MOCK=true`.",
    "analysisSource": "mock",
}
