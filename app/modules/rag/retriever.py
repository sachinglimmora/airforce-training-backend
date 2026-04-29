"""Vector search + MMR + threshold filter. See spec §9."""

from dataclasses import dataclass
from uuid import UUID

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings

log = structlog.get_logger()
_settings = get_settings()


@dataclass
class Hit:
    chunk_id: UUID
    section_id: UUID
    citation_keys: list[str]
    content: str
    page_number: int | None
    score: float
    mmr_rank: int = -1
    included: bool = False


async def _vector_search(
    db: AsyncSession,
    qvec: list[float],
    top_k: int,
    aircraft_id: UUID | None,
) -> list[dict]:
    """Raw pgvector search. Returns ranked candidate dicts."""
    sql = text("""
        SELECT
            c.id AS chunk_id,
            c.section_id,
            c.citation_keys,
            c.content,
            c.embedding,
            sec.page_number,
            1 - (c.embedding <=> CAST(:qvec AS vector)) AS cosine_score
        FROM content_chunks c
        JOIN content_sources s ON s.id = c.source_id
        JOIN content_sections sec ON sec.id = c.section_id
        WHERE c.superseded_by_source_id IS NULL
          AND s.status = 'approved'
          AND (s.aircraft_id = :aircraft_id OR s.aircraft_id IS NULL)
        ORDER BY c.embedding <=> CAST(:qvec AS vector)
        LIMIT :top_k
    """)
    result = await db.execute(sql, {
        "qvec": str(qvec),
        "aircraft_id": str(aircraft_id) if aircraft_id else None,
        "top_k": top_k,
    })
    out = []
    for row in result:
        d = dict(row._mapping)
        raw = d["embedding"]
        if isinstance(raw, str):
            # pgvector via raw SQL returns "[0.1,0.2,...]" — parse to list[float].
            d["embedding"] = [float(x) for x in raw.strip("[]").split(",") if x.strip()]
        else:
            # ORM-typed (numpy array, list, etc.) — coerce to plain list.
            d["embedding"] = [float(x) for x in raw]
        d["score"] = float(d["cosine_score"])  # MMR + grounder expect 'score'
        out.append(d)
    return out


def _cosine(a: list[float], b: list[float]) -> float:
    import math
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _mmr_rerank(candidates: list[dict], lambda_: float, qvec: list[float]) -> list[dict]:
    """Greedy Maximum Marginal Relevance.

    candidates: list of dicts with at least 'embedding' (list[float]) and 'score' (float).
    Returns reordered list, same length, with no duplicates.
    """
    if not candidates:
        return []
    selected: list[dict] = []
    remaining = list(candidates)
    # First pick = highest score
    remaining.sort(key=lambda c: -c["score"])
    selected.append(remaining.pop(0))

    while remaining:
        best_idx = 0
        best_mmr = -float("inf")
        for i, cand in enumerate(remaining):
            sim_to_query = cand["score"]
            sim_to_selected = max(_cosine(cand["embedding"], s["embedding"]) for s in selected)
            mmr = lambda_ * sim_to_query - (1 - lambda_) * sim_to_selected
            if mmr > best_mmr:
                best_mmr = mmr
                best_idx = i
        selected.append(remaining.pop(best_idx))
    return selected


async def retrieve(
    db: AsyncSession,
    query: str,
    aircraft_id: UUID | None,
    cfg: dict | None = None,
) -> tuple[list[Hit], dict]:
    """Embed query, vector search, MMR diversify, return Hit list + latency dict."""
    import time

    from app.modules.rag.embedder import embed_and_validate

    cfg = cfg or {
        "top_k": _settings.RAG_TOP_K,
        "mmr_lambda": _settings.RAG_MMR_LAMBDA,
    }
    latency: dict[str, int] = {}

    t0 = time.monotonic()
    qvec = (await embed_and_validate([query]))[0]
    latency["embed"] = int((time.monotonic() - t0) * 1000)

    t0 = time.monotonic()
    candidates = await _vector_search(db, qvec, cfg["top_k"], aircraft_id)
    latency["vector_search"] = int((time.monotonic() - t0) * 1000)

    t0 = time.monotonic()
    diversified = _mmr_rerank(candidates, cfg["mmr_lambda"], qvec)
    latency["mmr"] = int((time.monotonic() - t0) * 1000)

    hits = []
    for rank, c in enumerate(diversified):
        hits.append(Hit(
            chunk_id=c["chunk_id"],
            section_id=c["section_id"],
            citation_keys=c["citation_keys"],
            content=c["content"],
            page_number=c["page_number"],
            score=float(c["cosine_score"]),
            mmr_rank=rank,
        ))
    return hits, latency
