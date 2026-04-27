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


class GeminiProvider:
    name = "gemini"
    _DEFAULT_MODEL = "gemini-1.5-pro"
    _EMBED_MODEL = "text-embedding-004"

    async def complete(self, req: CompletionRequest) -> CompletionResponse:
        import google.generativeai as genai

        genai.configure(api_key=settings.GEMINI_API_KEY)
        model = genai.GenerativeModel(self._DEFAULT_MODEL)

        prompt_parts = [f"{m.role}: {m.content}" for m in req.messages]
        full_prompt = "\n".join(prompt_parts)

        start = time.monotonic()
        response = model.generate_content(
            full_prompt,
            generation_config=genai.GenerationConfig(
                temperature=req.temperature,
                max_output_tokens=req.max_tokens,
            ),
        )
        elapsed_ms = int((time.monotonic() - start) * 1000)

        text = response.text or ""
        usage = response.usage_metadata
        prompt_tokens = getattr(usage, "prompt_token_count", 0)
        completion_tokens = getattr(usage, "candidates_token_count", 0)
        cost = prompt_tokens * 0.0000035 + completion_tokens * 0.0000105

        log.info("gemini_complete", elapsed_ms=elapsed_ms, prompt_tokens=prompt_tokens)
        return CompletionResponse(
            text=text,
            model=self._DEFAULT_MODEL,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost,
        )

    async def embed(self, texts: list[str], model: str) -> EmbedResponse:
        import google.generativeai as genai

        genai.configure(api_key=settings.GEMINI_API_KEY)
        result = genai.embed_content(
            model=model or self._EMBED_MODEL, content=texts, task_type="retrieval_document"
        )
        embeddings = (
            result["embedding"]
            if isinstance(result["embedding"][0], list)
            else [result["embedding"]]
        )
        return EmbedResponse(embeddings=embeddings, model=model, total_tokens=0)

    async def health_check(self) -> ProviderHealth:
        import httpx

        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get("https://generativelanguage.googleapis.com/v1beta/models")
            elapsed = int((time.monotonic() - start) * 1000)
            return ProviderHealth(name=self.name, healthy=r.status_code < 500, latency_ms=elapsed)
        except Exception as e:
            return ProviderHealth(name=self.name, healthy=False, error=str(e))
