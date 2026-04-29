"""RAG orchestration: rewrite -> retrieve -> ground -> AIService.complete -> persist."""

import json
import time
from datetime import UTC, datetime
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.modules.ai.schemas import CompletionRequest as AICompletionRequest
from app.modules.ai.service import AIService
from app.modules.ai_assistant.models import ChatMessage, ChatSession
from app.modules.content.models import ContentReference, ContentSection, ContentSource
from app.modules.rag.grounder import decide
from app.modules.rag.models import RetrievalLog
from app.modules.rag.prompts import (
    INSTRUCTOR_SYSTEM_PROMPT,
    SOFT_GROUNDED_PREFIX,
    TRAINEE_SYSTEM_PROMPT,
    render_refusal,
)
from app.modules.rag.retriever import retrieve
from app.modules.rag.rewriter import rewrite

log = structlog.get_logger()
_settings = get_settings()


def _build_cfg() -> dict:
    return {
        "top_k": _settings.RAG_TOP_K,
        "max_chunks": _settings.RAG_MAX_CHUNKS,
        "include_threshold": _settings.RAG_INCLUDE_THRESHOLD,
        "soft_include_threshold": _settings.RAG_SOFT_INCLUDE_THRESHOLD,
        "suggest_threshold": _settings.RAG_SUGGEST_THRESHOLD,
        "mmr_lambda": _settings.RAG_MMR_LAMBDA,
    }


def _system_prompt(role: str, aircraft_context: str, soft: bool) -> str:
    base = INSTRUCTOR_SYSTEM_PROMPT if role == "instructor" else TRAINEE_SYSTEM_PROMPT
    base = base.format(aircraft_context=aircraft_context or "general aviation")
    if soft:
        return SOFT_GROUNDED_PREFIX + "\n\n" + base
    return base


async def _aircraft_context_label(db: AsyncSession, aircraft_id: UUID | None) -> str:
    """Resolve an aircraft UUID to its display name for prompt injection."""
    if not aircraft_id:
        return "general aviation"
    from app.modules.content.models import Aircraft
    result = await db.execute(select(Aircraft).where(Aircraft.id == aircraft_id))
    a = result.scalar_one_or_none()
    return a.display_name if a else "general aviation"


async def _resolve_sources(
    db: AsyncSession, citation_keys: list[str], scores_by_key: dict[str, float]
) -> list[dict]:
    """Fetch display metadata for a list of citation keys."""
    if not citation_keys:
        return []
    result = await db.execute(
        select(ContentReference, ContentSection, ContentSource)
        .join(ContentSection, ContentSection.id == ContentReference.section_id)
        .join(ContentSource, ContentSource.id == ContentReference.source_id)
        .where(ContentReference.citation_key.in_(citation_keys))
    )
    out = []
    for ref, sec, src in result:
        snippet = (sec.content_markdown or "")[:200]
        out.append({
            "citation_key": ref.citation_key,
            "display_label": ref.display_label,
            "page_number": sec.page_number,
            "score": scores_by_key.get(ref.citation_key, 0.0),
            "source_type": src.source_type,
            "source_version": src.version,
            "snippet": snippet,
        })
    return out


class RAGService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _get_session(self, session_id: UUID) -> ChatSession:
        result = await self.db.execute(select(ChatSession).where(ChatSession.id == session_id))
        sess = result.scalar_one_or_none()
        if not sess:
            from app.core.exceptions import NotFound
            raise NotFound("Chat session")
        return sess

    async def _load_history(self, session_id: UUID) -> list[dict]:
        result = await self.db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at)
        )
        return [{"role": m.role, "content": m.content} for m in result.scalars().all()]

    async def _aircraft_context_label(self, aircraft_id: UUID | None) -> str:
        return await _aircraft_context_label(self.db, aircraft_id)

    async def _resolve_sources(self, citation_keys: list[str], scores_by_key: dict[str, float]) -> list[dict]:
        return await _resolve_sources(self.db, citation_keys, scores_by_key)

    async def answer(self, query: str, session_id: UUID, user) -> dict:
        latency: dict[str, int] = {}
        sess = await self._get_session(session_id)
        history = await self._load_history(session_id)
        turn = len([m for m in history if m["role"] == "user"])

        # 1. Rewrite
        t0 = time.monotonic()
        rewritten = await rewrite(query, history, turn)
        latency["rewrite"] = int((time.monotonic() - t0) * 1000)
        skipped = rewritten == query

        # 2. Retrieve
        cfg = _build_cfg()
        hits, retr_lat = await retrieve(self.db, rewritten, sess.aircraft_id, cfg)
        latency.update(retr_lat)

        # 3. Ground
        decision = decide(hits, cfg)

        # 4. Persist user message + update session activity
        user_msg = ChatMessage(
            session_id=session_id, role="user", content=query, citations=None, grounded=None,
        )
        self.db.add(user_msg)
        sess.last_activity_at = datetime.now(UTC)
        await self.db.flush()

        # 5. Refusal short-circuit
        if decision["grounded"] == "refused":
            response_text = render_refusal(decision["suggestions"])
            assistant_msg = ChatMessage(
                session_id=session_id, role="assistant", content=response_text,
                citations=[], grounded="refused",
            )
            self.db.add(assistant_msg)
            await self._log_retrieval(None, session_id, user, query, rewritten, skipped,
                                      sess.aircraft_id, cfg["top_k"], hits, decision, latency)
            await self.db.commit()
            return {
                "user_message": user_msg, "assistant_message": assistant_msg,
                "decision": decision, "hits": hits, "rewritten_query": rewritten,
                "skipped_rewrite": skipped, "sources": [],
                "suggestions": await self._resolve_sources(
                    [s["citation_key"] for s in decision["suggestions"]],
                    {s["citation_key"]: s["score"] for s in decision["suggestions"]},
                ),
            }

        # 6. Build messages and call gateway
        scores_by_key = {k: h.score for h in hits for k in h.citation_keys if h.included}
        aircraft_label = await self._aircraft_context_label(sess.aircraft_id)
        # Pick the most-privileged role from CurrentUser.roles (list[str]) for prompt selection.
        user_roles = set(getattr(user, "roles", []))
        primary_role = "instructor" if "instructor" in user_roles or "admin" in user_roles else "trainee"
        sys_prompt = _system_prompt(primary_role, aircraft_label, soft=(decision["grounded"] == "soft"))
        messages = [{"role": "system", "content": sys_prompt}]
        for m in history:
            messages.append(m)
        messages.append({"role": "user", "content": query})

        t0 = time.monotonic()
        ai_svc = AIService(self.db)
        ai_result = await ai_svc.complete(
            AICompletionRequest(
                messages=messages,
                context_citations=decision["citation_keys"],
                provider_preference="auto",
                temperature=0.2,
                max_tokens=800,
                cache=True,
            ),
            user_id=str(getattr(user, "id", "anonymous")),
        )
        latency["llm"] = int((time.monotonic() - t0) * 1000)

        assistant_msg = ChatMessage(
            session_id=session_id, role="assistant", content=ai_result["response"],
            citations=decision["citation_keys"], grounded=decision["grounded"],
        )
        self.db.add(assistant_msg)
        await self._log_retrieval(ai_result["request_id"], session_id, user, query, rewritten, skipped,
                                  sess.aircraft_id, cfg["top_k"], hits, decision, latency)
        sources = await self._resolve_sources(decision["citation_keys"], scores_by_key)
        await self.db.commit()

        return {
            "user_message": user_msg, "assistant_message": assistant_msg,
            "decision": decision, "hits": hits, "rewritten_query": rewritten,
            "skipped_rewrite": skipped, "sources": sources, "suggestions": [],
        }

    async def _log_retrieval(self, request_id, session_id, user, original, rewritten, skipped,
                              aircraft_id, top_k, hits, decision, latency):
        log_entry = RetrievalLog(
            request_id=request_id,
            session_id=session_id,
            user_id=getattr(user, "id", None),
            original_query=original,
            rewritten_query=rewritten if not skipped else None,
            query_skipped_rewrite=skipped,
            aircraft_scope_id=aircraft_id,
            top_k=top_k,
            hits=[
                {
                    "citation_key": h.citation_keys[0] if h.citation_keys else "",
                    "score": h.score,
                    "included": h.included,
                    "mmr_rank": h.mmr_rank,
                }
                for h in hits
            ],
            grounded=decision["grounded"],
            latency_ms=latency,
        )
        self.db.add(log_entry)


class ExplainService:
    """One-shot grounded explanation — no session, no history. See spec §7."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _aircraft_context_label(self, aircraft_id: UUID | None) -> str:
        return await _aircraft_context_label(self.db, aircraft_id)

    async def _resolve_sources(self, citation_keys: list[str], scores_by_key: dict[str, float]) -> list[dict]:
        return await _resolve_sources(self.db, citation_keys, scores_by_key)

    async def explain(
        self,
        topic: str,
        context: str | None,
        system_state: dict | None,
        aircraft_id: UUID | None,
        user,
    ) -> dict:
        """One-shot grounded explanation. No session, no history."""
        from app.modules.rag.prompts import EXPLAIN_WHY_SYSTEM_PROMPT

        # 1. Build retrieval query
        retrieval_query = topic if not context else f"{topic} ({context})"

        # 2. Retrieve
        cfg = _build_cfg()
        hits, _latency = await retrieve(self.db, retrieval_query, aircraft_id, cfg)

        # 3. Ground
        decision = decide(hits, cfg)

        # 4. Refusal short-circuit
        if decision["grounded"] == "refused":
            suggestions = await self._resolve_sources(
                [s["citation_key"] for s in decision["suggestions"]],
                {s["citation_key"]: s["score"] for s in decision["suggestions"]},
            )
            return {
                "explanation": render_refusal(decision["suggestions"]),
                "grounded": "refused",
                "sources": [],
                "suggestions": suggestions,
                "moderation": None,
            }

        # 5. Build messages + call AI gateway
        aircraft_label = await self._aircraft_context_label(aircraft_id)
        user_roles = set(getattr(user, "roles", []))
        audience_label = "instructor" if user_roles & {"admin", "instructor"} else "trainee"
        sys_state_summary = json.dumps(system_state) if system_state else "(none)"

        sys_prompt = EXPLAIN_WHY_SYSTEM_PROMPT.format(
            audience_label=audience_label,
            aircraft_context=aircraft_label,
            system_state_summary=sys_state_summary,
        )
        messages: list[dict] = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": f"Explain: {topic}"},
        ]
        if context:
            messages.append({"role": "user", "content": f"Context: {context}"})

        ai_svc = AIService(self.db)
        ai_result = await ai_svc.complete(
            AICompletionRequest(
                messages=messages,
                context_citations=decision["citation_keys"],
                temperature=0.2,
                max_tokens=600,
                cache=True,
            ),
            user_id=str(getattr(user, "id", "anonymous")),
        )

        # 6. Moderate — lazy import; pass-through when moderator not installed yet
        try:
            from app.modules.rag.moderator import moderate as _moderate  # noqa: PLC0415
            mod_result = await _moderate(
                ai_result["response"], decision["grounded"], decision["citation_keys"], self.db,
            )
        except ImportError:
            from dataclasses import dataclass as _dataclass
            from dataclasses import field as _field

            @_dataclass
            class _PassResult:  # noqa: N801
                action: str = "pass"
                primary: object = None
                redacted_text: str | None = None
                all: list = _field(default_factory=list)

            mod_result = _PassResult()

        # 7. Build response based on moderation result
        if mod_result.action == "block":
            return {
                "explanation": "This response was blocked by the content moderation layer.",
                "grounded": "blocked",
                "sources": [],
                "suggestions": [],
                "moderation": {
                    "violation_type": mod_result.primary.category,
                    "severity": mod_result.primary.severity,
                },
            }

        text = mod_result.redacted_text if mod_result.action == "redact" else ai_result["response"]
        moderation_field = (
            {"redactions_applied": sum(1 for v in mod_result.all if v.action == "redact")}
            if mod_result.action == "redact"
            else None
        )

        scores_by_key = {k: h.score for h in hits for k in h.citation_keys if h.included}
        sources = await self._resolve_sources(decision["citation_keys"], scores_by_key)

        return {
            "explanation": text,
            "grounded": decision["grounded"],
            "sources": sources,
            "suggestions": [],
            "moderation": moderation_field,
        }
