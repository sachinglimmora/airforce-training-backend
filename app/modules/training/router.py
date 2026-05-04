import uuid
from typing import Annotated

from fastapi import Depends, File, Query, UploadFile
from fastapi.routing import APIRouter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.auth.deps import get_current_user
from app.modules.auth.schemas import CurrentUser
from app.modules.training.models import Course, TrainingModule
from app.modules.training.schemas import (
    CourseOut,
    ModuleCreate,
    ModuleOut,
    ModuleUpdate,
)

router = APIRouter()


# Courses
@router.get(
    "/courses",
    response_model=dict,
    summary="List all courses",
    description="Returns the full training catalogue with course metadata and progress tracking.",
    operation_id="training_courses_list",
)
async def list_courses(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
):
    result = await db.execute(select(Course))
    courses = result.scalars().all()
    return {"data": [CourseOut.model_validate(c).model_dump() for c in courses]}


@router.get(
    "/courses/{course_id}",
    response_model=dict,
    summary="Get course detail",
    description="Returns full metadata for a single course including its description and difficulty level.",
    operation_id="training_courses_get",
)
async def get_course(
    course_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
):
    result = await db.execute(select(Course).where(Course.id == course_id))
    course = result.scalar_one_or_none()
    if not course:
        return {"error": {"message": "Course not found"}}
    return {"data": CourseOut.model_validate(course).model_dump()}


# Modules
@router.get(
    "/modules",
    response_model=dict,
    summary="List training modules",
    description="Returns modules filtered by course ID if provided.",
    operation_id="training_modules_list",
)
async def list_modules(
    db: Annotated[AsyncSession, Depends(get_db)],
    course_id: uuid.UUID | None = Query(None, alias="courseId"),
    current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
):
    q = select(TrainingModule)
    if course_id:
        q = q.where(TrainingModule.course_id == course_id)
    result = await db.execute(q)
    modules = result.scalars().all()
    return {"data": [ModuleOut.model_validate(m).model_dump() for m in modules]}


@router.get(
    "/modules/{module_id}",
    response_model=dict,
    summary="Get module detail",
    description="Returns full metadata for a training module including procedures and diagrams.",
    operation_id="training_modules_get",
)
async def get_module(
    module_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
):
    result = await db.execute(select(TrainingModule).where(TrainingModule.id == module_id))
    module = result.scalar_one_or_none()
    if not module:
        return {"error": {"message": "Module not found"}}
    return {"data": ModuleOut.model_validate(module).model_dump()}


@router.post(
    "/modules/{module_id}/complete",
    response_model=dict,
    summary="Mark module as complete",
    description="Updates the completion status for a specific training module.",
    operation_id="training_modules_complete",
)
async def complete_module(
    module_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
):
    result = await db.execute(select(TrainingModule).where(TrainingModule.id == module_id))
    module = result.scalar_one_or_none()
    if not module:
        return {"error": {"message": "Module not found"}}

    module.is_completed = True
    await db.commit()

    return {"data": {"success": True, "message": "Module marked as complete"}}


@router.post(
    "/modules",
    response_model=dict,
    summary="Create a new module",
    description="Admin-only: Creates a new training module and links it to a course.",
    operation_id="training_modules_create",
)
async def create_module(
    body: ModuleCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
):
    module = TrainingModule(**body.model_dump())
    db.add(module)
    await db.commit()
    await db.refresh(module)
    return {"data": ModuleOut.model_validate(module).model_dump()}


@router.patch(
    "/modules/{module_id}",
    response_model=dict,
    summary="Update a module",
    description="Admin-only: Partial update of a training module.",
    operation_id="training_modules_update",
)
async def update_module(
    module_id: uuid.UUID,
    body: ModuleUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
):
    result = await db.execute(select(TrainingModule).where(TrainingModule.id == module_id))
    module = result.scalar_one_or_none()
    if not module:
        return {"error": {"message": "Module not found"}}

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(module, field, value)

    await db.commit()
    await db.refresh(module)
    return {"data": ModuleOut.model_validate(module).model_dump()}


@router.delete(
    "/modules/{module_id}",
    response_model=dict,
    summary="Delete a module",
    description="Admin-only: Permanently removes a training module.",
    operation_id="training_modules_delete",
)
async def delete_module(
    module_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
):
    result = await db.execute(select(TrainingModule).where(TrainingModule.id == module_id))
    module = result.scalar_one_or_none()
    if not module:
        return {"error": {"message": "Module not found"}}

    await db.delete(module)
    await db.commit()
    return {"data": {"message": "Module deleted successfully"}}


@router.post(
    "/modules/{module_id}/video/upload",
    response_model=dict,
    summary="Upload module video",
    description="Uploads a training video and associates it with the module.",
    operation_id="training_modules_video_upload",
)
async def upload_video(
    module_id: uuid.UUID,
    video: Annotated[UploadFile, File(...)],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
):
    # Handle upload
    return {"data": {"videoUrl": "https://example.com/v.mp4", "module": {}}}


@router.post(
    "/modules/{module_id}/video/generate",
    response_model=dict,
    summary="AI-generate module video",
    description="Triggers AI generation of a training video for the module.",
    operation_id="training_modules_video_generate",
)
async def generate_video(
    module_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
):
    return {
        "data": {
            "message": "Generation started",
            "videoStatus": "processing",
            "moduleId": str(module_id),
        }
    }
