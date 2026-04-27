import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field


class UploadSourceRequest(BaseModel):
    source_type: str = Field(pattern="^(fcom|qrh|amm|sop|syllabus)$")
    aircraft_id: uuid.UUID | None = None
    title: str
    version: str
    effective_date: date | None = None


class ContentSourceOut(BaseModel):
    id: uuid.UUID
    source_type: str
    aircraft_id: uuid.UUID | None
    title: str
    version: str
    status: str
    approved_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class SectionOut(BaseModel):
    id: uuid.UUID
    section_number: str
    title: str
    citation_key: str | None
    page_number: int | None
    content_markdown: str | None
    children: list["SectionOut"] = []

    model_config = {"from_attributes": True}


SectionOut.model_rebuild()


class ContentTreeOut(BaseModel):
    source_id: uuid.UUID
    source_type: str
    version: str
    sections: list[SectionOut]


class ContentReferenceOut(BaseModel):
    id: uuid.UUID
    source_id: uuid.UUID
    section_id: uuid.UUID
    citation_key: str
    display_label: str

    model_config = {"from_attributes": True}


class IngestionJobOut(BaseModel):
    source_id: uuid.UUID
    status: str
    job_id: str
