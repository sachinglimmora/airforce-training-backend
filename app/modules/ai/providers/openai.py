import time

import structlog

from app.config import get_settings
from app.modules.ai.providers.base import (
    CompletionRequest,
    CompletionResponse,
    EmbedResponse,
    ProviderHealth,
)

log = structlog.get_logger()
settings = get_settings()


class OpenAIProvider:
    name = "openai"
    _DEFAULT_MODEL = "gpt-4o"
    _DEFAULT_EMBED_MODEL = "text-embedding-3-small"

    async def complete(self, req: CompletionRequest) -> CompletionResponse:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        messages = [{"role": m.role, "content": m.content} for m in req.messages]

        start = time.monotonic()
        response = await client.chat.completions.create(
            model=self._DEFAULT_MODEL,
            messages=messages,
            temperature=req.temperature,
            max_tokens=req.max_tokens,
        )
        elapsed_ms = int((time.monotonic() - start) * 1000)

        choice = response.choices[0]
        usage = response.usage
        prompt_tokens = usage.prompt_tokens if usage else 0
        completion_tokens = usage.completion_tokens if usage else 0
        cost = prompt_tokens * 0.000005 + completion_tokens * 0.000015

        log.info("openai_complete", elapsed_ms=elapsed_ms, model=self._DEFAULT_MODEL)
        return CompletionResponse(
            text=choice.message.content or "",
            model=self._DEFAULT_MODEL,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost,
        )

    async def embed(self, texts: list[str], model: str) -> EmbedResponse:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        m = model or self._DEFAULT_EMBED_MODEL
        response = await client.embeddings.create(input=texts, model=m)
        embeddings = [d.embedding for d in response.data]
        total_tokens = response.usage.total_tokens if response.usage else 0
        return EmbedResponse(embeddings=embeddings, model=m, total_tokens=total_tokens)

    async def health_check(self) -> ProviderHealth:
        import httpx

        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(
                    "https://api.openai.com/v1/models",
                    headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
                )
            elapsed = int((time.monotonic() - start) * 1000)
            return ProviderHealth(name=self.name, healthy=r.status_code < 500, latency_ms=elapsed)
        except Exception as e:
            return ProviderHealth(name=self.name, healthy=False, error=str(e))
