from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


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
