"""Conversational query rewriting. See spec §11."""

import asyncio

import structlog

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.modules.ai.service import AIService
from app.modules.rag.prompts import REWRITER_PROMPT

log = structlog.get_logger()
_settings = get_settings()
_ANAPHORA = {"it", "that", "this", "they", "those", "same", "again", "also", "too", "either"}


def _has_anaphora(text: str) -> bool:
    words = {w.strip(".,?!:;").lower() for w in text.split()}
    return bool(words & _ANAPHORA)


def _needs_rewrite(text: str, turn: int) -> bool:
    if turn == 0:
        return False
    if len(text.split()) >= 10 and not _has_anaphora(text):
        return False
    return True


def _format_history(history: list[dict], window: int) -> str:
    last = history[-window:] if window else history
    return "\n".join(f"{m['role']}: {m['content']}" for m in last)


def _fallback_concat(msg: str, history: list[dict]) -> str:
    last_user = next((m["content"] for m in reversed(history) if m["role"] == "user"), None)
    if last_user:
        return f"{last_user} {msg}".strip()
    return msg


async def _llm_rewrite(msg: str, history: list[dict]) -> str:
    from app.modules.ai.schemas import CompletionRequest

    formatted = _format_history(history, _settings.RAG_REWRITER_HISTORY_WINDOW)
    prompt_text = REWRITER_PROMPT.format(history=formatted, message=msg)

    async with AsyncSessionLocal() as db:
        svc = AIService(db)
        result = await asyncio.wait_for(
            svc.complete(
                CompletionRequest(
                    messages=[{"role": "user", "content": prompt_text}],
                    provider_preference="auto",
                    temperature=0.0,
                    max_tokens=_settings.RAG_REWRITER_MAX_TOKENS,
                    cache=True,
                ),
                user_id="system_rewriter",
            ),
            timeout=_settings.RAG_REWRITER_TIMEOUT_S,
        )
    return result["response"].strip()


async def rewrite(msg: str, history: list[dict], turn: int) -> str:
    if not _needs_rewrite(msg, turn):
        return msg
    try:
        out = await _llm_rewrite(msg, history)
        if not out:
            raise RuntimeError("empty rewrite")
        return out
    except Exception as exc:
        log.warning("rewriter_fallback", error=str(exc))
        return _fallback_concat(msg, history)
