"""RAG retrieval service — stub implementation for Phase 1.

In Phase 2+ this will query pgvector for semantic search over FCOM/QRH embeddings.
For now it returns an empty hit list so the quiz endpoint can operate in
'low-grounded' mode against whatever the AI knows from pre-training.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class RetrievalHit:
    """A single chunk retrieved from the vector store."""

    citation_keys: list[str]
    score: float
    content: str = ""
    included: bool = True


@dataclass
class RetrievalConfig:
    top_k: int = 5
    score_threshold: float = 0.25
    strong_threshold: float = 0.60


# ---------------------------------------------------------------------------
# Module-level helpers (called by quiz_service and future explain_service)
# ---------------------------------------------------------------------------


def _build_cfg() -> RetrievalConfig:
    """Return the default retrieval config."""
    return RetrievalConfig()


async def retrieve(
    db: AsyncSession,
    query: str,
    aircraft_id: UUID | None,
    cfg: RetrievalConfig,
) -> tuple[list[RetrievalHit], str]:
    """Retrieve relevant chunks from the vector store.

    Phase 1 stub: always returns empty hits.  The quiz service will handle the
    'low-grounded' fallback path.  Replace with real pgvector query in Phase 2.
    """
    return [], query


def decide(hits: list[RetrievalHit], cfg: RetrievalConfig) -> dict:
    """Decide grounding level based on retrieval hits.

    Returns a dict with keys:
      - grounded: "strong" | "weak" | "low" | "refused"
      - citation_keys: list[str]
    """
    included = [h for h in hits if h.included]
    if not included:
        return {"grounded": "low", "citation_keys": []}

    avg_score = sum(h.score for h in included) / len(included)
    all_keys: list[str] = []
    for h in included:
        all_keys.extend(h.citation_keys)

    if avg_score >= cfg.strong_threshold:
        level = "strong"
    elif avg_score >= cfg.score_threshold:
        level = "weak"
    else:
        level = "low"

    return {"grounded": level, "citation_keys": list(dict.fromkeys(all_keys))}


async def _aircraft_context_label(db: AsyncSession, aircraft_id: UUID | None) -> str:
    """Return a human-readable aircraft context string for prompt injection."""
    if aircraft_id is None:
        return "general"
    # Phase 1 stub — would query Aircraft table in Phase 2
    return str(aircraft_id)


async def _resolve_sources(
    db: AsyncSession,
    citation_keys: list[str],
    scores: dict[str, float],
) -> list[dict]:
    """Resolve citation keys to source metadata dicts.

    Phase 1 stub: returns lightweight dicts with just the citation key.
    Phase 2 will join ContentReference + ContentSection for full metadata.
    """
    sources = []
    for key in citation_keys:
        sources.append(
            {
                "citation_key": key,
                "score": scores.get(key, 0.0),
            }
        )
    return sources


# ---------------------------------------------------------------------------
# RAGService (convenience class — wraps the module-level helpers)
# ---------------------------------------------------------------------------


@dataclass
class RAGService:
    db: AsyncSession
    _cfg: RetrievalConfig = field(default_factory=_build_cfg)

    async def retrieve(
        self, query: str, aircraft_id: UUID | None = None
    ) -> tuple[list[RetrievalHit], str]:
        return await retrieve(self.db, query, aircraft_id, self._cfg)

    def decide(self, hits: list[RetrievalHit]) -> dict:
        return decide(hits, self._cfg)
