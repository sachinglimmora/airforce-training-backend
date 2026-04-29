import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _now():
    return datetime.now(UTC)


class AircraftSystem(Base):
    __tablename__ = "aircraft_systems"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    aircraft_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("aircraft.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)  # engine, hydraulics, etc.
    status: Mapped[str] = mapped_column(String(50), default="operational")
    health: Mapped[float] = mapped_column(Float, default=100.0)

    components: Mapped[list["Component"]] = relationship(
        "Component", back_populates="system", cascade="all, delete-orphan"
    )


class Component(Base):
    __tablename__ = "components"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    system_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("aircraft_systems.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    part_number: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="operational")
    health: Mapped[float] = mapped_column(Float, default=100.0)
    last_maintenance: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_maintenance: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    specifications: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    system: Mapped["AircraftSystem"] = relationship("AircraftSystem", back_populates="components")
