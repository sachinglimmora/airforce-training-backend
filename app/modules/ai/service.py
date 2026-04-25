import asyncio
import uuid
from decimal import Decimal

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AllProvidersDown, CitationNotFound
from app.modules.ai.cache import _make_cache_key, get_cached, set_cached
from app.modules.ai.pii_filter import filter_messages
from app.modules.ai.providers.base import CompletionRequest as ProviderCompletionReq, Message
from app.modules.ai.providers.gemini import GeminiProvider
from app.modules.ai.providers.openai import OpenAIProvider
from app.modules.ai.schemas import CompletionRequest
from app.config import get_settings

log = structlog.get_logger()
settings = get_settings()

_gemini = GeminiProvider()
_openai = OpenAIProvider()


class AIService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def complete(self, req: CompletionRequest, user_id: str) -> dict:
        request_id = f"ai_req_{uuid.uuid4().hex[:12]}"

        # Resolve citations → inject context text
        messages = [{"role": m.role, "content": m.content} for m in req.messages]
        if req.context_citations:
            citation_text = await self._resolve_citations(req.context_citations)
            messages.insert(0, {"role": "system", "content": f"Reference material:\n{citation_text}"})

        # PII filter
        messages = filter_messages(messages)

        cache_key = _make_cache_key(
            req.provider_preference, "", [m["content"] for m in messages], req.temperature, req.context_citations
        )

        # Cache lookup (only for low-temperature deterministic requests)
        if req.cache and req.temperature < 0.3:
            cached = await get_cached(cache_key)
            if cached:
                log.info("ai_cache_hit", request_id=request_id)
                cached["cached"] = True
                cached["request_id"] = request_id
                return cached

        # Provider call with fallback
        provider_req = ProviderCompletionReq(
            messages=[Message(role=m["role"], content=m["content"]) for m in messages],
            temperature=req.temperature,
            max_tokens=req.max_tokens,
        )

        result, provider_name = await self._call_with_fallback(req.provider_preference, provider_req)

        response = {
            "response": result.text,
            "provider": provider_name,
            "model": result.model,
            "cached": False,
            "usage": {
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
                "cost_usd": result.cost_usd,
            },
            "citations": req.context_citations,
            "request_id": request_id,
        }

        if req.cache and req.temperature < 0.3:
            await set_cached(cache_key, response)

        await self._log_request(
            user_id=user_id,
            provider=provider_name,
            model=result.model,
            prompt_hash=cache_key,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            cost_usd=result.cost_usd,
            cached=False,
            status="success",
            citations=req.context_citations,
        )

        log.info("ai_complete", provider=provider_name, request_id=request_id, user_id=user_id)
        return response

    async def embed(self, texts: list[str], model: str) -> dict:
        result = await _gemini.embed(texts, model) if settings.GEMINI_API_KEY else await _openai.embed(texts, model)
        return {
            "embeddings": result.embeddings,
            "model": result.model,
            "usage": {"total_tokens": result.total_tokens},
        }

    async def provider_status(self) -> dict:
        gemini_health = await _gemini.health_check()
        openai_health = await _openai.health_check()
        return {
            "gemini": {"healthy": gemini_health.healthy, "latency_ms": gemini_health.latency_ms},
            "openai": {"healthy": openai_health.healthy, "latency_ms": openai_health.latency_ms},
        }

    async def _call_with_fallback(self, preference: str, req: ProviderCompletionReq):
        providers = []
        if preference == "gemini":
            providers = [(_gemini, "gemini")]
        elif preference == "openai":
            providers = [(_openai, "openai")]
        else:
            providers = [(_gemini, "gemini"), (_openai, "openai")]

        for provider, name in providers:
            try:
                result = await asyncio.wait_for(
                    provider.complete(req),
                    timeout=settings.AI_PROVIDER_TIMEOUT_SECONDS,
                )
                return result, name
            except Exception as exc:
                log.warning("ai_provider_failed", provider=name, error=str(exc))

        raise AllProvidersDown()

    async def _log_request(
        self,
        user_id: str,
        provider: str,
        model: str,
        prompt_hash: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: float,
        cached: bool,
        status: str,
        citations: list[str],
    ) -> None:
        try:
            from app.modules.ai.models import AIRequest

            entry = AIRequest(
                user_id=user_id,
                provider=provider,
                model=model,
                prompt_hash=prompt_hash,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost_usd=Decimal(str(cost_usd)),
                cached=cached,
                status=status,
                citations=citations,
            )
            self.db.add(entry)
            await self.db.flush()
        except Exception as exc:
            log.warning("ai_request_log_failed", error=str(exc))

    async def _resolve_citations(self, citation_keys: list[str]) -> str:
        from sqlalchemy import select
        from app.modules.content.models import ContentReference, ContentSection

        parts = []
        for key in citation_keys:
            result = await self.db.execute(
                select(ContentReference).where(ContentReference.citation_key == key)
            )
            ref = result.scalar_one_or_none()
            if not ref:
                raise CitationNotFound(key)
            sec_result = await self.db.execute(
                select(ContentSection).where(ContentSection.id == ref.section_id)
            )
            sec = sec_result.scalar_one_or_none()
            if sec and sec.content_markdown:
                parts.append(f"[{key}] {sec.content_markdown}")
        return "\n\n".join(parts)
