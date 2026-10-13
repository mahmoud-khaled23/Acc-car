"""Laws router — search and look up New York VTL sections from the RAG index."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..config import Settings
from ..dependencies import get_settings
from ..services import law_service

router = APIRouter(prefix="/api/laws", tags=["laws"])


@router.get("")
@router.get("/")
def search_laws(
    q: str = "",
    jurisdiction: str = "",
    topic: str = "",
    limit: int = 12,
    settings: Settings = Depends(get_settings),
):
    """Search law sections. Returns the UI's ``LawSearchResult[]`` shape."""
    if not q.strip():
        return []

    try:
        results = law_service.search_laws(q, str(settings.rag_out_dir), settings, limit=limit)
    except Exception as exc:  # noqa: BLE001 - index problems should read as 503, not a 500 trace
        raise HTTPException(status_code=503, detail=f"Law index unavailable: {exc}") from exc

    if topic:
        filtered = [law for law in results if topic in (law.get("topics") or [])]
        results = filtered or results

    return [
        {
            "law": law,
            "matchScore": law.get("relevanceScore") or 0.0,
            "matchedFields": (["title", "fullText"] if law.get("whyApplies") else ["fullText"]),
        }
        for law in results
    ]


@router.get("/search")
def search_laws_alias(
    q: str = "",
    jurisdiction: str = "",
    topic: str = "",
    limit: int = 12,
    settings: Settings = Depends(get_settings),
):
    """Alias kept for the React client's ``/api/laws/search`` call."""
    return search_laws(q=q, jurisdiction=jurisdiction, topic=topic, limit=limit, settings=settings)


@router.get("/catalog")
def list_catalog(
    limit: int = 0,
    topic: str = "",
    settings: Settings = Depends(get_settings),
):
    """All core VTL sections in the prepared index (browse + filter chips)."""
    try:
        laws = law_service.list_sections(str(settings.rag_out_dir), settings, limit=limit or None)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"Law index unavailable: {exc}") from exc
    if topic:
        filtered = [law for law in laws if topic in (law.get("topics") or [])]
        return filtered
    return laws


@router.get("/{section_id}/full")
def get_law_full(section_id: str, settings: Settings = Depends(get_settings)):
    """Raw prepared section (full text + references), straight from out/parents.json."""
    try:
        section = law_service.get_law_by_id(section_id, str(settings.rag_out_dir), settings)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"Law index unavailable: {exc}") from exc
    if section is None:
        raise HTTPException(status_code=404, detail=f"Law section '{section_id}' not found")
    return section


@router.get("/{section_id}")
def get_law(section_id: str, settings: Settings = Depends(get_settings)):
    """Single law section in the UI's ``TrafficLaw`` shape."""
    try:
        section = law_service.get_law_by_id(section_id, str(settings.rag_out_dir), settings)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"Law index unavailable: {exc}") from exc
    if section is None:
        raise HTTPException(status_code=404, detail=f"Law section '{section_id}' not found")
    return law_service.law_to_ui(section)
