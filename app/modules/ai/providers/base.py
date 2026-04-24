from abc import abstractmethod
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class Message:
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass
class CompletionRequest:
    messages: list[Message]
    temperature: float = 0.2
    max_tokens: int = 800


@dataclass
class CompletionResponse:
    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float


@dataclass
class EmbedResponse:
    embeddings: list[list[float]]
    model: str
    total_tokens: int


@dataclass
class ProviderHealth:
    name: str
    healthy: bool
    latency_ms: int | None = None
    error: str | None = None


@runtime_checkable
class LLMProvider(Protocol):
    name: str

    @abstractmethod
    async def complete(self, req: CompletionRequest) -> CompletionResponse: ...

    @abstractmethod
    async def embed(self, texts: list[str], model: str) -> EmbedResponse: ...

    @abstractmethod
    async def health_check(self) -> ProviderHealth: ...
