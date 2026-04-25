from typing import Annotated, List, Optional
import uuid
from datetime import UTC, datetime
from fastapi import Depends, HTTPException
from fastapi.routing import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.auth.deps import get_current_user
from app.modules.auth.schemas import CurrentUser
from app.modules.ai.service import AIService
from app.modules.ai.schemas import CompletionRequest

router = APIRouter()

@router.get("/history", response_model=dict)
async def get_history(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
):
    # Mock history for now
    return {"data": []}

@router.post("/message", response_model=dict)
async def send_message(
    body: dict,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
):
    content = body.get("content")
    if not content:
        raise HTTPException(status_code=400, detail="Content is required")
        
    svc = AIService(db)
    # We use the existing AI service's complete method
    # Wrap it to match the expected frontend format
    req = CompletionRequest(
        messages=[{"role": "user", "content": content}],
        model="gemini-1.5-pro", # Default
    )
    
    ai_result = await svc.complete(req, current_user.id)
    
    user_message = {
        "id": str(uuid.uuid4()),
        "role": "user",
        "content": content,
        "timestamp": datetime.now(UTC).isoformat()
    }
    
    assistant_message = {
        "id": str(uuid.uuid4()),
        "role": "assistant",
        "content": ai_result.content,
        "timestamp": datetime.now(UTC).isoformat(),
        "sources": ai_result.citations
    }
    
    return {
        "data": {
            "userMessage": user_message,
            "assistantMessage": assistant_message
        }
    }

@router.delete("/history", response_model=dict)
async def clear_history(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
):
    return {"data": {"message": "History cleared"}}
