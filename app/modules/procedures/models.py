import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

_now = lambda: datetime.now(UTC)


class Procedure(Base):
    __tablename__ = "procedures"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    aircraft_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("aircraft.id"), nullable=True
    )
    procedure_type: Mapped[str] = mapped_column(
        Enum("normal", "abnormal", "emergency", name="procedure_type"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    phase: Mapped[str] = mapped_column(String(64), nullable=False)
    citation_key: Mapped[str | None] = mapped_column(
        String(128), ForeignKey("content_references.citation_key"), nullable=True
    )

    steps: Mapped[list["ProcedureStep"]] = relationship(
        "ProcedureStep",
        back_populates="procedure",
        foreign_keys="ProcedureStep.procedure_id",
        order_by="ProcedureStep.ordinal",
    )


class ProcedureStep(Base):
    __tablename__ = "procedure_steps"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    procedure_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("procedures.id"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    action_text: Mapped[str] = mapped_column(Text, nullable=False)
    expected_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    mode: Mapped[str] = mapped_column(
        Enum("challenge_response", "read_do", "do_verify", name="step_mode"),
        nullable=False,
        default="do_verify",
    )
    target_time_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parent_step_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("procedure_steps.id"), nullable=True
    )
    branch_condition: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_critical: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    procedure: Mapped["Procedure"] = relationship(
        "Procedure", back_populates="steps", foreign_keys=[procedure_id]
    )
    branches: Mapped[list["ProcedureStep"]] = relationship(
        "ProcedureStep", foreign_keys=[parent_step_id], lazy="selectin"
    )


class ProcedureSession(Base):
    __tablename__ = "procedure_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    procedure_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("procedures.id"), nullable=False
    )
    trainee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(
        Enum("in_progress", "completed", "aborted", name="proc_session_status"),
        default="in_progress",
    )


class Deviation(Base):
    __tablename__ = "deviations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("procedure_sessions.id"), nullable=False
    )
    step_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("procedure_steps.id"), nullable=False
    )
    deviation_type: Mapped[str] = mapped_column(
        Enum("skip", "out_of_order", "timing", "wrong_action", "incomplete", name="deviation_type"),
        nullable=False,
    )
    severity: Mapped[str] = mapped_column(
        Enum("minor", "moderate", "major", "critical", name="deviation_severity"), nullable=False
    )
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    expected: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    actual: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
