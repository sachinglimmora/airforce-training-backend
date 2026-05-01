import json as _json
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class RagQueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    aircraft_id: UUID | None = None
    top_k: int | None = None  # override config default if needed


class HitOut(BaseModel):
    citation_key: str
    score: float
    included: bool
    mmr_rank: int


class RagQueryResponse(BaseModel):
    grounded: str  # strong | soft | refused
    citation_keys: list[str]
    hits: list[HitOut]
    suggestions: list[HitOut]


class SourceOut(BaseModel):
    citation_key: str
    display_label: str
    page_number: int | None
    score: float
    source_type: str
    source_version: str
    snippet: str


class AssistantMessage(BaseModel):
    id: str
    role: str
    content: str
    timestamp: datetime
    grounded: str | None = None
    sources: list[SourceOut] = []
    suggestions: list[SourceOut] = []


class UserMessage(BaseModel):
    id: str
    role: str
    content: str
    timestamp: datetime


class ChatTurnResponse(BaseModel):
    # camelCase intentional: matches the frontend chat-UI contract per spec §12.
    userMessage: UserMessage  # noqa: N815
    assistantMessage: AssistantMessage  # noqa: N815


class CreateSessionRequest(BaseModel):
    aircraft_id: UUID | None = None
    title: str | None = None


class SessionOut(BaseModel):
    id: UUID
    aircraft_id: UUID | None
    title: str | None
    status: str
    created_at: datetime
    last_activity_at: datetime


# F12 — Module Awareness schemas
class ModuleContextUpdate(BaseModel):
    module_id: str | None = Field(default=None, max_length=128)
    step_id: str | None = Field(default=None, max_length=128)
    context_data: dict | None = None

    @field_validator("context_data")
    @classmethod
    def context_data_size_limit(cls, v: dict | None) -> dict | None:
        if v is not None and len(_json.dumps(v)) > 10_000:
            raise ValueError("context_data exceeds 10KB limit")
        return v


class ModuleContextOut(BaseModel):
    session_id: UUID
    module_id: str | None
    step_id: str | None
    context_data: dict | None
    context_updated_at: datetime | None


# F3 — Explain-Why schemas
class ExplainRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=2000)
    context: str | None = None
    system_state: dict | None = None
    aircraft_id: UUID | None = None


class ExplainResponse(BaseModel):
    explanation: str
    grounded: str  # strong | soft | refused | blocked
    sources: list[SourceOut] = []
    suggestions: list[SourceOut] = []
    moderation: dict | None = None
