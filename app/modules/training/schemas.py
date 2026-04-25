import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict

class CourseBase(BaseModel):
    title: str
    description: str | None = None
    category: str | None = None
    duration: str | None = None
    difficulty: str | None = None
    thumbnail: str | None = None

class CourseCreate(CourseBase):
    pass

class CourseUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    category: str | None = None
    duration: str | None = None
    difficulty: str | None = None
    thumbnail: str | None = None
    status: str | None = None

class CourseOut(CourseBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    module_count: int
    completed_modules: int
    progress: int
    status: str
    created_at: datetime
    updated_at: datetime

class ModuleBase(BaseModel):
    title: str
    description: str | None = None
    documentation: str | None = None
    procedures: list[dict] | None = None
    diagrams: list[dict] | None = None
    category: str | None = None
    difficulty: str | None = None
    duration: str | None = None
    order: int = 0

class ModuleCreate(ModuleBase):
    course_id: uuid.UUID

class ModuleUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    documentation: str | None = None
    procedures: list[dict] | None = None
    diagrams: list[dict] | None = None
    category: str | None = None
    difficulty: str | None = None
    duration: str | None = None
    order: int | None = None
    is_completed: bool | None = None

class ModuleOut(ModuleBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    course_id: uuid.UUID
    is_completed: bool
    video_url: str | None
    video_status: str
    created_at: datetime
    updated_at: datetime
