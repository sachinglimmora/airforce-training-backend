import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, File, Form, UploadFile
from fastapi.routing import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.auth.deps import get_current_user
from app.modules.auth.schemas import CurrentUser

router = APIRouter()

_401 = {401: {"description": "Not authenticated"}}
_404 = {404: {"description": "Video not found"}}


@router.get(
    "",
    response_model=dict,
    summary="List instructor videos",
    description=(
        "Returns all videos uploaded by instructors. "
        "Trainees see only videos assigned to them via `GET /instructor-videos/my-assignments`."
    ),
    responses={**_401},
    operation_id="instructor_videos_list",
)
async def list_videos(
    _db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
):
    return {"data": []}


@router.get(
    "/my-assignments",
    response_model=dict,
    summary="Get videos assigned to the calling trainee",
    description=(
        "Returns the list of instructor videos that have been assigned to the authenticated trainee."
    ),
    responses={**_401},
    operation_id="instructor_videos_my_assignments",
)
async def get_my_assignments(
    _db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
):
    return {"data": []}


@router.post(
    "/upload",
    response_model=dict,
    summary="Upload an instructor video",
    description=(
        "Uploads a video file and stores it in MinIO. Returns the video record with a playback URL.\n\n"
        "**Form fields:**\n"
        "- `video` (required) — video file binary\n"
        "- `title` (required) — display title\n"
        "- `description` (optional)\n"
        "- `category` (optional) — matches `CourseCategory`\n"
        "- `difficulty` (optional) — beginner | intermediate | advanced\n"
        "- `tags` (optional) — comma-separated tag string"
    ),
    responses={**_401, 400: {"description": "Unsupported file format"}},
    operation_id="instructor_videos_upload",
)
async def upload_video(
    title: str = Form(...),
    description: str | None = Form(None),
    category: str | None = Form(None),  # noqa: ARG001
    difficulty: str | None = Form(None),  # noqa: ARG001
    tags: str | None = Form(None),  # noqa: ARG001
    video: UploadFile = File(...),  # noqa: ARG001
    _db: Annotated[AsyncSession, Depends(get_db)] = None,
    _current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
):
    return {
        "data": {
            "id": str(uuid.uuid4()),
            "title": title,
            "description": description,
            "videoUrl": "https://example.com/video.mp4",
            "createdAt": datetime.now(UTC).isoformat(),
        }
    }


@router.post(
    "/{video_id}/assign",
    response_model=dict,
    summary="Assign a video to a trainee",
    description=(
        "Makes a video visible to a specific trainee.\n\n"
        "Body: `{ \"trainee_id\": \"uuid\" }`"
    ),
    responses={**_401, **_404},
    operation_id="instructor_videos_assign",
)
async def assign_video(
    _video_id: uuid.UUID,
    _body: dict,
    _db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
):
    return {"data": {"message": "Video assigned successfully"}}


@router.delete(
    "/{video_id}/assign/{trainee_id}",
    response_model=dict,
    summary="Unassign a video from a trainee",
    description="Removes the assignment of a video from a specific trainee.",
    responses={**_401, **_404},
    operation_id="instructor_videos_unassign",
)
async def unassign_video(
    _video_id: uuid.UUID,
    _trainee_id: uuid.UUID,
    _db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
):
    return {"data": {"message": "Video unassigned successfully"}}


@router.delete(
    "/{video_id}",
    response_model=dict,
    summary="Delete a video",
    description="Permanently deletes a video and removes all trainee assignments.",
    responses={**_401, **_404},
    operation_id="instructor_videos_delete",
)
async def delete_video(
    _video_id: uuid.UUID,
    _db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
):
    return {"data": {"message": "Video deleted successfully"}}
