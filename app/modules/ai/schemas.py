from pydantic import BaseModel, Field


class MessageIn(BaseModel):
    role: str = Field(pattern="^(system|user|assistant)$")
    content: str


class CompletionRequest(BaseModel):
    messages: list[MessageIn]
    context_citations: list[str] = []
    provider_preference: str = "auto"
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int = Field(default=800, ge=1, le=4096)
    cache: bool = True


class CompletionOut(BaseModel):
    response: str
    provider: str
    model: str
    cached: bool
    usage: dict
    citations: list[str]
    request_id: str


class EmbedRequest(BaseModel):
    texts: list[str] = Field(min_length=1)
    model: str = "text-embedding-3-small"


class EmbedOut(BaseModel):
    embeddings: list[list[float]]
    model: str
    usage: dict
