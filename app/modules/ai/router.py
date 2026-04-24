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
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    svc = AIService(db)
    result = await svc.embed(body.texts, body.model)
    return {"data": result}


@router.get("/providers/status", summary="AI provider health")
async def provider_status(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    svc = AIService(db)
    status = await svc.provider_status()
    return {"data": status}


@router.get("/usage", summary="Token and cost usage (admin)")
async def usage(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    # Phase 1: query ai_requests table for aggregated usage
    return {"data": {"message": "Usage analytics coming in next iteration"}}
