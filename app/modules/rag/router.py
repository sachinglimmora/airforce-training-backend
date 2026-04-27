from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.routing import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.auth.deps import get_current_user
from app.modules.auth.schemas import CurrentUser
from app.modules.rag.grounder import decide
from app.modules.rag.retriever import retrieve
from app.modules.rag.schemas import HitOut, RagQueryRequest, RagQueryResponse
from app.config import get_settings

router = APIRouter()
_settings = get_settings()


@router.post(
    "/query",
    response_model=dict,
    summary="Retrieve grounded citations for a query (debug)",
    description=(
        "Standalone retrieval endpoint — returns the citation_keys that "
        "would be sent to the AI gateway, plus grounding decision + suggestions. "
        "Used for tuning thresholds and debugging.\n\n"
        "**Required role:** instructor or admin."
    ),
    operation_id="rag_query",
)
async def rag_query(
    body: RagQueryRequest,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if current_user.role not in ("admin", "instructor"):
        raise HTTPException(status_code=403, detail="Admin or instructor required")
    cfg = {
        "top_k": body.top_k or _settings.RAG_TOP_K,
        "mmr_lambda": _settings.RAG_MMR_LAMBDA,
        "include_threshold": _settings.RAG_INCLUDE_THRESHOLD,
        "soft_include_threshold": _settings.RAG_SOFT_INCLUDE_THRESHOLD,
        "suggest_threshold": _settings.RAG_SUGGEST_THRESHOLD,
        "max_chunks": _settings.RAG_MAX_CHUNKS,
    }
    hits, _latency = await retrieve(db, body.query, body.aircraft_id, cfg)
    decision = decide(hits, cfg)

    hits_out = [
        HitOut(
            citation_key=h.citation_keys[0] if h.citation_keys else "",
            score=h.score,
            included=h.included,
            mmr_rank=h.mmr_rank,
        )
        for h in hits
    ]
    suggestions_out = [
        HitOut(
            citation_key=s["citation_key"],
            score=s["score"],
            included=False,
            mmr_rank=-1,
        )
        for s in decision["suggestions"]
    ]
    return {"data": RagQueryResponse(
        grounded=decision["grounded"],
        citation_keys=decision["citation_keys"],
        hits=hits_out,
        suggestions=suggestions_out,
    ).model_dump()}
