import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict
from typing import Any, List, Optional

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
    instructor_id: Optional[uuid.UUID] = None
    aircraft_id: Optional[uuid.UUID] = None
    procedure_id: Optional[uuid.UUID] = None
    scenario_id: Optional[uuid.UUID] = None
    status: str = "in_progress"
    metadata_json: Optional[dict] = None

class TrainingSessionCreate(TrainingSessionBase):
    pass

class TrainingSessionUpdate(BaseModel):
    status: Optional[str] = None
    ended_at: Optional[datetime] = None
    metadata_json: Optional[dict] = None

class TrainingSessionOut(TrainingSessionBase):
    id: uuid.UUID
    started_at: datetime
    ended_at: Optional[datetime] = None

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
