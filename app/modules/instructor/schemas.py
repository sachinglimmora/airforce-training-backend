import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class TraineeOverview(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    readinessScore: float = 0.0
    progress: float = 0.0
    simulationHours: float = 0.0
    status: str = "active"

    model_config = ConfigDict(from_attributes=True)


class TrainingSessionBase(BaseModel):
    trainee_id: uuid.UUID
    session_type: str
    instructor_id: uuid.UUID | None = None
    aircraft_id: uuid.UUID | None = None
    procedure_id: uuid.UUID | None = None
    scenario_id: uuid.UUID | None = None
    status: str = "in_progress"
    metadata_json: dict | None = None


class TrainingSessionCreate(TrainingSessionBase):
    pass


class TrainingSessionUpdate(BaseModel):
    status: str | None = None
    ended_at: datetime | None = None
    metadata_json: dict | None = None


class TrainingSessionOut(TrainingSessionBase):
    id: uuid.UUID
    started_at: datetime
    ended_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ScenarioOut(BaseModel):
    id: uuid.UUID
    scenario_code: str
    name: str
    scenario_type: str

    model_config = ConfigDict(from_attributes=True)


class InstructorAnalytics(BaseModel):
    summary: Any
    charts: Any
