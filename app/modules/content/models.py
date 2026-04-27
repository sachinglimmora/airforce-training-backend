import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

_now = lambda: datetime.now(UTC)


class Aircraft(Base):
    __tablename__ = "aircraft"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    type_code: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    manufacturer: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class ContentSource(Base):
    __tablename__ = "content_sources"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_type: Mapped[str] = mapped_column(
        Enum("fcom", "qrh", "amm", "sop", "syllabus", name="content_source_type"), nullable=False
    )
    aircraft_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("aircraft.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    effective_date: Mapped[datetime | None] = mapped_column(Date, nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(
        Enum("draft", "approved", "archived", name="content_status"), default="draft", nullable=False
    )
    embedding_status: Mapped[str] = mapped_column(
        Enum("pending", "succeeded", "failed", name="embedding_status"),
        default="pending",
        nullable=False,
    )
    original_file_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)

    sections: Mapped[list["ContentSection"]] = relationship(
        "ContentSection", back_populates="source", foreign_keys="ContentSection.source_id"
    )


class ContentSection(Base):
    __tablename__ = "content_sections"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("content_sources.id"), nullable=False, index=True)
    parent_section_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("content_sections.id"), nullable=True)
    section_number: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ordinal: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    source: Mapped["ContentSource"] = relationship("ContentSource", back_populates="sections", foreign_keys=[source_id])
    children: Mapped[list["ContentSection"]] = relationship(
        "ContentSection", foreign_keys=[parent_section_id], lazy="selectin"
    )
    reference: Mapped["ContentReference | None"] = relationship("ContentReference", back_populates="section", uselist=False)


class ContentReference(Base):
    __tablename__ = "content_references"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("content_sources.id"), nullable=False)
    section_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("content_sections.id"), nullable=False)
    citation_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    display_label: Mapped[str] = mapped_column(String(255), nullable=False)

    section: Mapped["ContentSection"] = relationship("ContentSection", back_populates="reference")
