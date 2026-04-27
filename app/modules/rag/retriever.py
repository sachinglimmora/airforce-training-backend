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
    return [dict(row._mapping) for row in result]


async def retrieve(db: AsyncSession, query: str, aircraft_id: UUID | None, cfg: dict | None = None) -> list[Hit]:
    raise NotImplementedError  # implemented in Task C3
