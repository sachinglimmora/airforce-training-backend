import uuid
from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

_now = lambda: datetime.now(UTC)


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    aircraft_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("aircraft.id"), nullable=True)
    asset_type: Mapped[str] = mapped_column(
        Enum("exterior", "cockpit", "subsystem", "environment", name="asset_type"), nullable=False
    )
    fidelity: Mapped[str] = mapped_column(
        Enum("low", "medium", "high", name="asset_fidelity"), nullable=False, default="medium"
    )
    format: Mapped[str] = mapped_column(String(16), nullable=False, default="glb")
    storage_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    version: Mapped[str] = mapped_column(String(32), nullable=False, default="1.0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
