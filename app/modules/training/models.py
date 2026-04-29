import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _now():
    return datetime.now(UTC)



class Course(Base):
    __tablename__ = "courses"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(100), nullable=True)
    duration: Mapped[str] = mapped_column(String(50), nullable=True)
    difficulty: Mapped[str] = mapped_column(String(50), nullable=True)
    thumbnail: Mapped[str | None] = mapped_column(String(512), nullable=True)
    module_count: Mapped[int] = mapped_column(Integer, default=0)
    completed_modules: Mapped[int] = mapped_column(Integer, default=0)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(50), default="not-started")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    modules: Mapped[list["TrainingModule"]] = relationship(
        "TrainingModule", back_populates="course", cascade="all, delete-orphan"
    )


class TrainingModule(Base):
    __tablename__ = "training_modules"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    course_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("courses.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    documentation: Mapped[str | None] = mapped_column(Text, nullable=True)
    procedures: Mapped[list[dict] | None] = mapped_column(JSONB, nullable=True)
    diagrams: Mapped[list[dict] | None] = mapped_column(JSONB, nullable=True)
    category: Mapped[str] = mapped_column(String(100), nullable=True)
    difficulty: Mapped[str] = mapped_column(String(50), nullable=True)
    duration: Mapped[str] = mapped_column(String(50), nullable=True)
    order: Mapped[int] = mapped_column(Integer, default=0)
    is_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    video_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    video_status: Mapped[str] = mapped_column(String(50), default="none")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    course: Mapped["Course"] = relationship("Course", back_populates="modules")
