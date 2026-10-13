"""Traffic-law retrieval service — drives the project's RAG stack.

Real path: ``src/rag/retrieval/report_retrieval.py::retrieve_for_report``
(keyword anchors + hybrid dense/BM25 retrieval from ``src/rag/retrieval/index_and_retrieve.py``,
embedding model ``BAAI/bge-m3``, index under ``out/``).
"""
from __future__ import annotations

import logging
import sys
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

_project_root = str(Path(__file__).parents[3])
_src_path = str(Path(__file__).parents[3] / "src")
for _p in (_project_root, _src_path):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from .. import mappers  # noqa: E402


def retrieve_laws(
    description: str,
    out_dir: str,
    settings,
    extra_queries: list[str] | None = None,
    extra_sections: list[str] | None = None,
) -> list[dict]:
    """Retrieve relevant VTL sections for an accident description.

    ``extra_queries`` / ``extra_sections`` are the hints produced by the
    reasoning model's fact-extraction step (same flow as the project's
    ``analyze_accident`` CLI).  Returns the retrieval sections in the project's
    native format (``id``/``title``/``text``/``score``/``matched_queries``).
    """
    if settings.rag_mock:
        return _MOCK_LAWS

    try:
        from rag.retrieval import report_retrieval
        from rag.retrieval.report_retrieval import retrieve_for_report
    except ImportError as exc:
        raise RuntimeError(
            "The RAG package is not importable — install its dependencies "
            f"(chromadb, sentence-transformers, rank-bm25, openai). Original error: {exc}"
        ) from exc

    # ``report_retrieval`` imported ``retrieve`` by value, so the mode has to be
    # injected on the name it actually calls.
    original = report_retrieval.retrieve
    if settings.rag_mode != "hybrid":
        logger.debug("Using RAG mode '%s'", settings.rag_mode)

        def scoped_retrieve(queries, out, **kwargs):
            kwargs.setdefault("mode", settings.rag_mode)
            return original(queries, out, **kwargs)

        report_retrieval.retrieve = scoped_retrieve

    try:
        return retrieve_for_report(
            description=description,
            out=out_dir,
            extra_queries=extra_queries,
            extra_sections=extra_sections,
            top_k=settings.rag_top_k,
            rerank=settings.rag_rerank,
        )
    finally:
        report_retrieval.retrieve = original


def retrieve_laws_for_ui(description: str, out_dir: str, settings) -> list[dict]:
    """Retrieval result converted to the frontend ``TrafficLaw[]`` contract."""
    return mappers.laws_to_traffic_laws(retrieve_laws(description, out_dir, settings))


def search_laws(query: str, out_dir: str, settings, limit: int = 10) -> list[dict]:
    """Full-text/vector search used by the Traffic Laws page."""
    if not query.strip():
        return []
    sections = retrieve_laws(query, out_dir, settings)
    return mappers.laws_to_traffic_laws(sections)[:limit]


def get_law_by_id(section_id: str, out_dir: str, settings) -> dict | None:
    """Direct section lookup by VTL number against the prepared index.

    ``out/parents.json`` is a prepared lookup table, so this is exact — the
    previous similarity-search fallback has been removed.
    """
    wanted = str(section_id).strip().upper().replace("VTL-", "").replace("VTL §", "").strip()
    wanted = wanted.lstrip("§").strip()
    if not wanted:
        return None

    if settings.rag_mock:
        for item in _MOCK_LAWS:
            if item["section_id"].endswith(wanted):
                return item
        return None

    parents = _load_parents(str(out_dir))
    for pid, section in parents.items():
        if pid.upper() == f"VTL-{wanted}" or str(section.get("section")) == wanted:
            return section
    return None


@lru_cache(maxsize=4)
def _load_parents(out_dir: str) -> dict:
    import json

    path = Path(out_dir) / "parents.json"
    if not path.is_file():
        raise RuntimeError(
            f"Law index not found at {path}. Run 'python -m src.rag.retrieval.index_and_retrieve index "
            "--out out' (or copy the prepared out/ directory) before starting the API."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def list_sections(out_dir: str, settings, limit: int | None = None) -> list[dict]:
    """Every searchable (``core``) section in the prepared index, UI-shaped.

    Used by the Traffic Laws page to browse the corpus and build its filters.
    """
    if settings.rag_mock:
        return mappers.laws_to_traffic_laws(_MOCK_LAWS)

    parents = _load_parents(str(out_dir))
    sections = [section for section in parents.values() if section.get("category") == "core"]
    sections.sort(key=lambda s: (s.get("section") or "", s.get("id") or ""))
    if limit:
        sections = sections[:limit]
    return mappers.laws_to_traffic_laws(sections)


def law_to_ui(section: dict) -> dict:
    """Map a single prepared section into the frontend ``TrafficLaw`` contract."""
    return mappers.laws_to_traffic_laws([section])[0]


# ---------------------------------------------------------------------------
# Mock (opt-in via RAG_MOCK=true)
# ---------------------------------------------------------------------------

_MOCK_LAWS = [
    {
        "id": "VTL-1140",
        "section": "1140",
        "title": "Vehicle approaching or entering intersection",
        "text": (
            "The driver of a vehicle approaching an intersection shall yield the right of way to a "
            "vehicle which has entered the intersection from a different highway."
        ),
        "score": 0.91,
        "score_kind": "keyword-rule",
        "matched_queries": ["rule: right-of-way"],
        "category": "core",
        "source": "mock",
    },
    {
        "id": "VTL-1128",
        "section": "1128",
        "title": "Driving on roadways laned for traffic",
        "text": (
            "Whenever any roadway has been divided into two or more clearly marked lanes for traffic, "
            "a vehicle shall be driven as nearly as practicable entirely within a single lane."
        ),
        "score": 0.87,
        "score_kind": "dense",
        "matched_queries": ["unsafe lane change"],
        "category": "core",
        "source": "mock",
    },
    {
        "id": "VTL-1111",
        "section": "1111",
        "title": "Traffic-control signal indications",
        "text": (
            "Traffic shall be controlled by traffic-control signals exhibiting different colored "
            "lights; vehicular traffic facing a steady red indication shall stop."
        ),
        "score": 0.83,
        "score_kind": "dense",
        "matched_queries": ["failure to obey traffic control signal"],
        "category": "core",
        "source": "mock",
    },
]
