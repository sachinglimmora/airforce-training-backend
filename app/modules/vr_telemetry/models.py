import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

_now = lambda: datetime.now(UTC)


class VRSession(Base):
    __tablename__ = "vr_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    training_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("training_sessions.id"), nullable=False
    )
    device_id: Mapped[str] = mapped_column(String(128), nullable=False)
    device_type: Mapped[str] = mapped_column(String(64), nullable=False)
    runtime: Mapped[str] = mapped_column(
        Enum("webxr", "unity", name="vr_runtime"), nullable=False, default="webxr"
    )
    app_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    frame_rate_avg: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)


class VRTelemetryEvent(Base):
    __tablename__ = "vr_telemetry_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    vr_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vr_sessions.id"), nullable=False, index=True
    )
    client_event_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    head_pose: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    controller_left: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    controller_right: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    interaction_target: Mapped[str | None] = mapped_column(String(128), nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
