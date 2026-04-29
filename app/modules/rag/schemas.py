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
    moderation: dict | None = None  # populated when block/redact fires


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


# ─── Moderation ──────────────────────────────────────────────────────────


class ModerationRuleIn(BaseModel):
    category: str = Field(pattern="^(classification|banned_phrase|profanity|casual)$")
    pattern: str = Field(min_length=1, max_length=500)
    pattern_type: str = Field(default="regex", pattern="^(regex|literal)$")
    action: str = Field(pattern="^(block|redact|log)$")
    severity: str = Field(pattern="^(critical|high|medium|low)$")
    description: str | None = None
    active: bool = True


class ModerationRuleUpdate(BaseModel):
    category: str | None = Field(default=None, pattern="^(classification|banned_phrase|profanity|casual)$")
    pattern: str | None = Field(default=None, min_length=1, max_length=500)
    pattern_type: str | None = Field(default=None, pattern="^(regex|literal)$")
    action: str | None = Field(default=None, pattern="^(block|redact|log)$")
    severity: str | None = Field(default=None, pattern="^(critical|high|medium|low)$")
    description: str | None = None
    active: bool | None = None


class ModerationRuleOut(BaseModel):
    id: UUID
    category: str
    pattern: str
    pattern_type: str
    action: str
    severity: str
    description: str | None
    active: bool
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ModerationLogOut(BaseModel):
    id: UUID
    request_id: str | None
    session_id: UUID | None
    user_id: UUID | None
    rule_id: UUID | None
    category: str
    matched_text: str
    original_response: str
    action_taken: str
    severity: str
    created_at: datetime

    model_config = {"from_attributes": True}
