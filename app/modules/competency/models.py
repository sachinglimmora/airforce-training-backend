import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import DateTime, Enum, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

_now = lambda: datetime.now(UTC)


class Competency(Base):
    __tablename__ = "competencies"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class CompetencyEvidence(Base):
    __tablename__ = "competency_evidence"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trainee_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    competency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("competencies.id"), nullable=False)
    session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class Rubric(Base):
    __tablename__ = "rubrics"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    procedure_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("procedures.id"), nullable=True)
    scenario_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("scenarios.id"), nullable=True)
    criteria: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    max_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("100.00"))


class Evaluation(Base):
    __tablename__ = "evaluations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    evaluator_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    rubric_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("rubrics.id"), nullable=False)
    scores: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    total_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    grade: Mapped[str | None] = mapped_column(
        Enum("excellent", "satisfactory", "needs_improvement", "unsatisfactory", name="evaluation_grade"), nullable=True
    )
    comments: Mapped[str | None] = mapped_column(Text, nullable=True)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
