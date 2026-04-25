from typing import Annotated

from fastapi import Depends
from fastapi.routing import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.auth.deps import get_current_user
from app.modules.auth.schemas import CurrentUser
from app.modules.ai.schemas import CompletionRequest, EmbedRequest
from app.modules.ai.service import AIService

router = APIRouter()


@router.post("/complete", summary="LLM completion (RAG gateway)")
async def complete(
    body: CompletionRequest,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    svc = AIService(db)
    result = await svc.complete(body, current_user.id)
    return {"data": result}


@router.post("/embed", summary="Generate embeddings")
async def embed(
    body: EmbedRequest,
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    svc = AIService(db)
    result = await svc.embed(body.texts, body.model)
    return {"data": result}


@router.get("/providers/status", summary="AI provider health")
async def provider_status(
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    svc = AIService(db)
    status = await svc.provider_status()
    return {"data": status}


@router.get("/usage", summary="Token and cost usage (admin)")
async def usage(
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from decimal import Decimal
    from sqlalchemy import func, select
    from app.modules.ai.models import AIRequest

    rows = await db.execute(
        select(
            AIRequest.provider,
            func.count().label("requests"),
            func.sum(AIRequest.prompt_tokens).label("prompt_tokens"),
            func.sum(AIRequest.completion_tokens).label("completion_tokens"),
            func.sum(AIRequest.cost_usd).label("cost_usd"),
            func.sum(func.cast(AIRequest.cached, func.Integer())).label("cache_hits"),
        ).group_by(AIRequest.provider)
    )
    by_provider = []
    total_cost = Decimal("0")
    total_requests = 0
    for row in rows:
        cost = float(row.cost_usd or 0)
        total_cost += Decimal(str(cost))
        total_requests += row.requests or 0
        by_provider.append({
            "provider": row.provider,
            "requests": row.requests or 0,
            "prompt_tokens": row.prompt_tokens or 0,
            "completion_tokens": row.completion_tokens or 0,
            "cost_usd": cost,
            "cache_hits": row.cache_hits or 0,
        })

    return {"data": {
        "total_requests": total_requests,
        "total_cost_usd": float(total_cost),
        "by_provider": by_provider,
    }}
