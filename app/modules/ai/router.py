from typing import Annotated

from fastapi import Depends
from fastapi.routing import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.auth.deps import get_current_user
from app.modules.auth.schemas import CurrentUser
from app.modules.ai.schemas import CompletionRequest, EmbedRequest
from app.modules.ai.service import AIService

router = APIRouter()

_401 = {401: {"description": "Not authenticated"}}
_429 = {429: {"description": "Per-user or global rate limit exceeded — see Retry-After header"}}
_502 = {502: {"description": "All LLM providers unreachable"}}


@router.post(
    "/complete",
    response_model=dict,
    summary="LLM completion (RAG gateway)",
    description=(
        "Send a message array to the AI gateway. The gateway:\n\n"
        "1. Resolves `context_citations` (citation keys → section markdown) and prepends them as a system message\n"
        "2. Runs the PII filter — `403 PII_DETECTED` if unsafe content is found\n"
        "3. Checks the response cache (key: SHA-256 of provider + model + messages + temperature + citations)\n"
        "4. Calls Gemini (primary) with 15 s timeout; falls back to OpenAI on failure\n"
        "5. Caches the response when `cache: true` and `temperature < 0.3`\n"
        "6. Logs the call to `ai_requests` for usage tracking\n\n"
        "**Rate limits:** 60/min (trainee) · 200/min (instructor) · 2 000/min (global)\n\n"
        "**Error codes:** `403 PII_DETECTED` · `400 CITATION_NOT_FOUND` · `429 RATE_LIMITED` · `502 ALL_PROVIDERS_DOWN`"
    ),
    responses={
        **_401,
        400: {"description": "CITATION_NOT_FOUND — one or more citation keys do not exist"},
        403: {"description": "PII_DETECTED — request blocked by PII filter"},
        **_429,
        **_502,
    },
    operation_id="ai_complete",
)
async def complete(
    body: CompletionRequest,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    svc = AIService(db)
    result = await svc.complete(body, current_user.id)
    return {"data": result}


@router.post(
    "/embed",
    response_model=dict,
    summary="Generate text embeddings",
    description=(
        "Generate embeddings for one or more text chunks. Used by Shreyansh's RAG ingestion pipeline.\n\n"
        "- `texts` — list of strings to embed (1–100 recommended per call)\n"
        "- `model` — embedding model identifier (default: `text-embedding-3-small`)\n\n"
        "Returns `embeddings` (list of float vectors) and `usage` (token count)."
    ),
    responses={**_401, **_429, **_502},
    operation_id="ai_embed",
)
async def embed(
    body: EmbedRequest,
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    svc = AIService(db)
    result = await svc.embed(body.texts, body.model)
    return {"data": result}


@router.get(
    "/providers/status",
    response_model=dict,
    summary="AI provider health check",
    description=(
        "Returns the current health status and latency of each configured LLM provider "
        "(Gemini and OpenAI). Degraded providers are skipped as primary but still tried on fallback."
    ),
    responses={**_401},
    operation_id="ai_provider_status",
)
async def provider_status(
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    svc = AIService(db)
    status = await svc.provider_status()
    return {"data": status}


@router.get(
    "/usage",
    response_model=dict,
    summary="AI token and cost usage (admin)",
    description=(
        "Returns aggregated token consumption and USD cost from the `ai_requests` table, "
        "grouped by provider. Includes cache hit counts.\n\n"
        "Response shape:\n"
        "```json\n"
        "{\n"
        "  \"total_requests\": 1240,\n"
        "  \"total_cost_usd\": 4.21,\n"
        "  \"by_provider\": [\n"
        "    { \"provider\": \"gemini\", \"requests\": 980, \"prompt_tokens\": 420000,\n"
        "      \"completion_tokens\": 180000, \"cost_usd\": 3.12, \"cache_hits\": 310 }\n"
        "  ]\n"
        "}\n"
        "```"
    ),
    responses={**_401, 403: {"description": "Requires admin role"}},
    operation_id="ai_usage",
)
async def usage(
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from decimal import Decimal
    from sqlalchemy import func, select
    from app.modules.ai.models import AIRequest

    rows = await db.execute(
        select(
            AIRequest.provider,
            func.count().label("requests"),
            func.sum(AIRequest.prompt_tokens).label("prompt_tokens"),
            func.sum(AIRequest.completion_tokens).label("completion_tokens"),
            func.sum(AIRequest.cost_usd).label("cost_usd"),
            func.sum(func.cast(AIRequest.cached, func.Integer())).label("cache_hits"),
        ).group_by(AIRequest.provider)
    )
    by_provider = []
    total_cost = Decimal("0")
    total_requests = 0
    for row in rows:
        cost = float(row.cost_usd or 0)
        total_cost += Decimal(str(cost))
        total_requests += row.requests or 0
        by_provider.append({
            "provider": row.provider,
            "requests": row.requests or 0,
            "prompt_tokens": row.prompt_tokens or 0,
            "completion_tokens": row.completion_tokens or 0,
            "cost_usd": cost,
            "cache_hits": row.cache_hits or 0,
        })

    return {"data": {
        "total_requests": total_requests,
        "total_cost_usd": float(total_cost),
        "by_provider": by_provider,
    }}
