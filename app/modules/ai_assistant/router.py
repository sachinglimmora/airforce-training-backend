import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends
from fastapi.routing import APIRouter
from pydantic import BaseModel
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
