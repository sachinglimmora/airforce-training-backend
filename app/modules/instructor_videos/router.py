from typing import Annotated, List, Optional
import uuid
from datetime import UTC, datetime
from fastapi import Depends, HTTPException, Query, UploadFile, File, Form
from fastapi.routing import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.auth.deps import get_current_user
from app.modules.auth.schemas import CurrentUser

router = APIRouter()

@router.get("", response_model=dict)
async def list_videos(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
):
    # Mock videos
    return {"data": []}

@router.get("/my-assignments", response_model=dict)
async def get_my_assignments(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
):
    return {"data": []}

@router.post("/upload", response_model=dict)
async def upload_video(
    title: str = Form(...),
    description: Optional[str] = Form(None),
    category: Optional[str] = Form(None),
    difficulty: Optional[str] = Form(None),
    isPublic: Optional[bool] = Form(None),
    tags: Optional[str] = Form(None),
    video: UploadFile = File(...),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
):
    # Handle upload logic (save to MinIO/Cloudinary and DB)
    return {
        "data": {
            "id": str(uuid.uuid4()),
            "title": title,
            "description": description,
            "videoUrl": "https://example.com/video.mp4",
            "createdAt": datetime.now(UTC).isoformat()
        }
    }

@router.post("/{video_id}/assign", response_model=dict)
async def assign_video(
    video_id: uuid.UUID,
    body: dict,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
):
    return {"data": {"message": "Video assigned successfully"}}

@router.delete("/{video_id}/assign/{trainee_id}", response_model=dict)
async def unassign_video(
    video_id: uuid.UUID,
    trainee_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
):
    return {"data": {"message": "Video unassigned successfully"}}

@router.delete("/{video_id}", response_model=dict)
async def delete_video(
    video_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
):
    return {"data": {"message": "Video deleted successfully"}}
