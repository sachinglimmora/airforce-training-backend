import uuid
from datetime import datetime, UTC
from sqlalchemy import Column, String, DateTime, Boolean, ForeignKey, Table
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import relationship
from app.database import Base

# Association table for video assignments
video_assignments = Table(
    "instructor_video_assignments",
    Base.metadata,
    Column("video_id", UUID(as_uuid=True), ForeignKey("instructor_videos.id", ondelete="CASCADE"), primary_key=True),
    Column("trainee_id", UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("assigned_at", DateTime(timezone=True), default=lambda: datetime.now(UTC)),
)

class InstructorVideo(Base):
    __tablename__ = "instructor_videos"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    instructor_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    title = Column(String, nullable=False)
    description = Column(String, nullable=True)
    video_url = Column(String, nullable=False)
    category = Column(String, default="General")
    difficulty = Column(String, default="intermediate")
    is_public = Column(Boolean, default=False)
    tags = Column(ARRAY(String), default=[])
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))

    # Relationships
    assigned_trainees = relationship("User", secondary=video_assignments, backref="assigned_instructor_videos")
