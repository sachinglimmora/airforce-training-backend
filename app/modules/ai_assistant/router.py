import uuid
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException
from fastapi.routing import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.ai.schemas import CompletionRequest
from app.modules.ai.service import AIService
from app.modules.auth.deps import get_current_user
from app.modules.auth.schemas import CurrentUser

router = APIRouter()

_401 = {401: {"description": "Not authenticated"}}


class SendMessageRequest(BaseModel):
    content: str


class ContextHelpRequest(BaseModel):
    question: str = Field(..., min_length=1)
    module_id: str | None = None
    step_id: str | None = None
    step_title: str | None = None
    aircraft_id: UUID | None = None
    system_state: dict | None = None


@router.get(
    "/history",
    response_model=dict,
    summary="Get AI assistant message history",
    description=(
        "Returns the conversation history for the current user's AI assistant session. "
        "History is scoped per user and persisted server-side."
    ),
    responses={**_401},
    operation_id="ai_assistant_history",
)
async def get_history(
    _db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
):
    return {"data": []}


@router.post(
    "/message",
    response_model=dict,
    summary="Send a message to the AI assistant",
    description=(
        "Sends a user message to the AI gateway and returns both the user message "
        "and the assistant reply.\n\n"
        'Body: `{ "content": "Explain the bleed air system." }`\n\n'
        "Response shape:\n"
        "```json\n"
        "{\n"
        '  "userMessage":      { "id": "...", "role": "user",      "content": "...", "timestamp": "..." },\n'
        '  "assistantMessage": { "id": "...", "role": "assistant", "content": "...", "timestamp": "...", "sources": [] }\n'
        "}\n"
        "```\n\n"
        "Internally wraps `POST /ai/complete` — PII filter and rate limits apply."
    ),
    responses={
        **_401,
        400: {"description": "content field is required"},
        429: {"description": "AI rate limit exceeded"},
        502: {"description": "All LLM providers unreachable"},
    },
    operation_id="ai_assistant_send_message",
)
async def send_message(
    body: SendMessageRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
):
    svc = AIService(db)
    req = CompletionRequest(
        messages=[{"role": "user", "content": body.content}],
    )
    ai_result = await svc.complete(req, current_user.id)

    now = datetime.now(UTC).isoformat()
    return {
        "data": {
            "userMessage": {
                "id": str(uuid.uuid4()),
                "role": "user",
                "content": body.content,
                "timestamp": now,
            },
            "assistantMessage": {
                "id": str(uuid.uuid4()),
                "role": "assistant",
                "content": ai_result.get("response", ""),
                "timestamp": now,
                "sources": ai_result.get("citations", []),
            },
        }
    }


@router.post(
    "/context-help",
    response_model=dict,
    summary="Context-sensitive AI help for module pages and cockpit overlays",
    description=(
        "Answers a user question with optional module context (module_id, step_id, step_title, "
        "aircraft_id, system_state). The frontend passes context explicitly so the endpoint works "
        "independently of any session state. Delegates to ExplainService (PR #4). "
        "Returns 503 if ExplainService is not yet available on this deployment."
    ),
    responses={
        **_401,
        400: {"description": "question is required"},
        503: {"description": "ExplainService not yet available — pending PR merge"},
    },
    operation_id="ai_assistant_context_help",
)
async def context_help(
    body: ContextHelpRequest,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if not body.question.strip():
        raise HTTPException(400, "question is required")

    topic = body.question.strip()
    context_parts = []
    if body.module_id:
        context_parts.append(f"Module: {body.module_id}")
    if body.step_id:
        context_parts.append(f"Step: {body.step_id}")
    if body.step_title:
        context_parts.append(f"Step title: {body.step_title}")
    context = ", ".join(context_parts) if context_parts else None

    # Deferred import — ExplainService lives in PR #4 (app.modules.rag.service).
    # Fail gracefully with 503 if that PR has not been merged yet.
    try:
        from app.modules.rag.service import ExplainService
    except ImportError:
        raise HTTPException(503, "Explain service not yet available — pending PR merge")

    svc = ExplainService(db)
    result = await svc.explain(
        topic=topic,
        context=context,
        system_state=body.system_state,
        aircraft_id=body.aircraft_id,
        user=current_user,
    )
    return {"data": result}


@router.delete(
    "/history",
    response_model=dict,
    summary="Clear AI assistant conversation history",
    description="Deletes all stored messages for the current user's assistant session.",
    responses={**_401},
    operation_id="ai_assistant_clear_history",
)
async def clear_history(
    _db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
):
    return {"data": {"message": "History cleared"}}
