import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal
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
from app.modules.rag.quiz_service import QuizService

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


class QuizRequest(BaseModel):
    topic: str = Field(..., min_length=1)
    module_id: str | None = None
    aircraft_id: UUID | None = None
    difficulty: Literal["beginner", "intermediate", "advanced"] = "intermediate"
    num_questions: int = Field(default=5, ge=1, le=10)


@router.post(
    "/quiz",
    response_model=dict,
    summary="Generate an adaptive multiple-choice quiz",
    description=(
        "Generates N multiple-choice questions about a given topic, grounded in retrieved "
        "FCOM/QRH chunks via RAG. Returns questions, answer key, explanations, and source "
        "citations. Stateless — no session persistence."
    ),
    responses={
        **_401,
        400: {"description": "topic is required"},
        422: {"description": "Validation error (num_questions out of 1-10 range, etc.)"},
        502: {"description": "All LLM providers unreachable"},
    },
    operation_id="ai_assistant_generate_quiz",
)
async def generate_quiz(
    body: QuizRequest,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if not body.topic.strip():
        raise HTTPException(400, "topic is required")
    svc = QuizService(db)
    result = await svc.generate_quiz(
        topic=body.topic.strip(),
        aircraft_id=body.aircraft_id,
        module_id=body.module_id,
        difficulty=body.difficulty,
        num_questions=body.num_questions,
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
