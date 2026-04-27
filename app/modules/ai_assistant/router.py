import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Query
from fastapi.routing import APIRouter
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.ai_assistant.models import ChatMessage, ChatSession
from app.modules.auth.deps import get_current_user
from app.modules.auth.schemas import CurrentUser
from app.modules.rag.schemas import (
    AssistantMessage, ChatTurnResponse, CreateSessionRequest, SessionOut,
    SourceOut, UserMessage,
)
from app.modules.rag.service import RAGService

router = APIRouter()


class SendMessageRequest(BaseModel):
    content: str
    session_id: uuid.UUID | None = None


@router.post(
    "/sessions",
    response_model=dict,
    summary="Create a new chat session",
    description=(
        "Create a chat session with optional `aircraft_id` to scope retrieval. "
        "Without `aircraft_id`, only general aviation content is searched."
    ),
    operation_id="ai_assistant_create_session",
)
async def create_session(
    body: CreateSessionRequest,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    sess = ChatSession(
        user_id=uuid.UUID(str(current_user.id)),
        aircraft_id=body.aircraft_id,
        title=body.title,
    )
    db.add(sess)
    await db.commit()
    await db.refresh(sess)
    return {"data": SessionOut(
        id=sess.id, aircraft_id=sess.aircraft_id, title=sess.title, status=sess.status,
        created_at=sess.created_at, last_activity_at=sess.last_activity_at,
    ).model_dump(mode="json")}


@router.post(
    "/message",
    response_model=dict,
    summary="Send a message in a chat session (RAG-backed)",
    description=(
        "Sends a user message. The RAG layer retrieves citations from approved content "
        "and grounds the answer. Returns userMessage + assistantMessage with sources/suggestions.\n\n"
        "If `session_id` is omitted, a new session is created with no aircraft scope.\n\n"
        "Add `?debug=true` (instructor/admin only) for retrieval tracing."
    ),
    responses={
        401: {"description": "Not authenticated"},
        404: {"description": "Session not found"},
        429: {"description": "AI rate limit exceeded"},
        502: {"description": "All LLM providers unreachable"},
    },
    operation_id="ai_assistant_send_message",
)
async def send_message(
    body: SendMessageRequest,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    debug: bool = Query(False, description="Include retrieval debug info (instructor/admin only)"),
):
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="content is required")

    session_id = body.session_id
    if session_id is None:
        sess = ChatSession(user_id=uuid.UUID(str(current_user.id)))
        db.add(sess)
        await db.flush()
        session_id = sess.id

    svc = RAGService(db)
    result = await svc.answer(body.content.strip(), session_id, current_user)
    user_msg, asst_msg = result["user_message"], result["assistant_message"]
    sources = [SourceOut(**s) for s in result["sources"]]
    suggestions = [SourceOut(**s) for s in result["suggestions"]]

    response = {
        "data": ChatTurnResponse(
            userMessage=UserMessage(
                id=str(user_msg.id), role="user", content=user_msg.content,
                timestamp=user_msg.created_at,
            ),
            assistantMessage=AssistantMessage(
                id=str(asst_msg.id), role="assistant", content=asst_msg.content,
                timestamp=asst_msg.created_at,
                grounded=asst_msg.grounded,
                sources=sources, suggestions=suggestions,
            ),
        ).model_dump(mode="json")
    }

    if debug and current_user.role in ("admin", "instructor"):
        response["debug"] = {
            "original_query": body.content.strip(),
            "rewritten_query": result["rewritten_query"],
            "skipped_rewrite": result["skipped_rewrite"],
            "retrieval_hits": [
                {"citation_key": h.citation_keys[0] if h.citation_keys else "", "score": h.score, "included": h.included}
                for h in result["hits"]
            ],
        }
    return response


@router.get(
    "/history",
    response_model=dict,
    summary="Get chat history for a session",
    description="Returns ordered messages for a session_id (or empty if no session_id given).",
    operation_id="ai_assistant_history",
)
async def get_history(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    session_id: uuid.UUID | None = Query(None),
):
    if session_id is None:
        return {"data": []}
    result = await db.execute(
        select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at)
    )
    return {"data": [
        {
            "id": str(m.id),
            "role": m.role,
            "content": m.content,
            "citations": m.citations or [],
            "grounded": m.grounded,
            "timestamp": m.created_at.isoformat(),
        }
        for m in result.scalars().all()
    ]}


@router.delete(
    "/history",
    response_model=dict,
    summary="Close a chat session",
    description="Marks the session as closed. Messages remain for audit.",
    operation_id="ai_assistant_clear_history",
)
async def close_session(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    session_id: uuid.UUID = Query(...),
):
    result = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
    sess = result.scalar_one_or_none()
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")
    sess.status = "closed"
    sess.closed_at = datetime.now(UTC)
    await db.commit()
    return {"data": {"message": "Session closed", "session_id": str(session_id)}}
