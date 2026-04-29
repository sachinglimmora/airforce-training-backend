# Explain-Why (F3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `POST /api/v1/ai-assistant/explain` — a stateless, one-shot, grounded educational explanation endpoint (no session, no history rewriter) reusing the existing RAG retriever + grounder + AI gateway.

**Architecture:** ExplainService sits as a sibling class to RAGService in `service.py`, reusing module-level helpers `_build_cfg`, `_aircraft_context_label`, and `_resolve_sources` (refactored out of RAGService). The moderator call is a deferred import that gracefully no-ops (pass-through) when `app.modules.rag.moderator` is not yet available in this branch — it will activate once F2 (content-moderation branch) merges.

**Tech Stack:** FastAPI, SQLAlchemy AsyncSession, pgvector (via existing `retrieve()`), Pydantic v2, pytest-asyncio, structlog. All existing — no new deps.

---

## File Map

| File | Action | What changes |
|---|---|---|
| `app/modules/rag/prompts.py` | Modify | Add `EXPLAIN_WHY_SYSTEM_PROMPT` constant |
| `app/modules/rag/schemas.py` | Modify | Add `ExplainRequest`, `ExplainResponse` Pydantic models |
| `app/modules/rag/service.py` | Modify | Refactor `_aircraft_context_label` + `_resolve_sources` to module-level; add `ExplainService` class |
| `app/modules/ai_assistant/router.py` | Modify | Add `POST /explain` endpoint; import `ExplainService` + schemas |
| `tests/unit/test_explain_service.py` | Create | Unit tests: query construction, refusal short-circuit, prompt formatting |
| `tests/integration/test_explain_endpoint.py` | Create | Integration tests: happy path, no-aircraft, empty topic 400, blocked-by-moderator, 401 unauth |

---

## Task 1: Add `EXPLAIN_WHY_SYSTEM_PROMPT` to `prompts.py`

**Files:**
- Modify: `app/modules/rag/prompts.py`

- [ ] **Step 1.1: Write the failing import test**

Create `tests/unit/test_explain_service.py` with just the import assertion:

```python
"""Unit tests for ExplainService — query construction, refusal short-circuit, prompt formatting."""
from app.modules.rag.prompts import EXPLAIN_WHY_SYSTEM_PROMPT


def test_explain_why_prompt_has_required_placeholders():
    """Prompt must have all three format placeholders the service uses."""
    assert "{audience_label}" in EXPLAIN_WHY_SYSTEM_PROMPT
    assert "{aircraft_context}" in EXPLAIN_WHY_SYSTEM_PROMPT
    assert "{system_state_summary}" in EXPLAIN_WHY_SYSTEM_PROMPT


def test_explain_why_prompt_formats_correctly():
    rendered = EXPLAIN_WHY_SYSTEM_PROMPT.format(
        audience_label="trainee",
        aircraft_context="Su-30MKI",
        system_state_summary='{"engine_n1": "23%"}',
    )
    assert "trainee" in rendered
    assert "Su-30MKI" in rendered
    assert "23%" in rendered
```

- [ ] **Step 1.2: Run test to verify it fails**

```
.venv/Scripts/python.exe -m pytest tests/unit/test_explain_service.py::test_explain_why_prompt_has_required_placeholders -v
```

Expected: `ImportError: cannot import name 'EXPLAIN_WHY_SYSTEM_PROMPT'`

- [ ] **Step 1.3: Add `EXPLAIN_WHY_SYSTEM_PROMPT` to `app/modules/rag/prompts.py`**

Append after the existing `REWRITER_PROMPT` constant and before `render_refusal`:

```python
EXPLAIN_WHY_SYSTEM_PROMPT = """You are an aerospace training assistant providing a focused 'why does this happen' explanation to an Indian Air Force trainee.

Audience: {audience_label}
Aircraft context: {aircraft_context}
Optional system state observed: {system_state_summary}

RULES:
1. Answer ONLY using the reference material in this conversation. Do NOT speculate.
2. If the reference is insufficient, say so — do NOT guess.
3. Cite specific sections in your explanation using the citation_key in [brackets].
4. Structure: brief one-line summary → mechanism (why this happens) → safety/operational implication \
→ cross-reference to related procedures if relevant.
5. Use **bold** for safety-critical values, limits, and warnings.
6. Be concise: 4-8 sentences typical, 12 max for complex systems.
7. Educational, not conversational. No filler ("great question", etc.). No first-person opinions."""
```

- [ ] **Step 1.4: Run tests to verify they pass**

```
.venv/Scripts/python.exe -m pytest tests/unit/test_explain_service.py::test_explain_why_prompt_has_required_placeholders tests/unit/test_explain_service.py::test_explain_why_prompt_formats_correctly -v
```

Expected: 2 passed

- [ ] **Step 1.5: Lint**

```
.venv/Scripts/python.exe -m ruff check app/modules/rag/prompts.py tests/unit/test_explain_service.py
```

Expected: no errors

- [ ] **Step 1.6: Commit**

```bash
git add app/modules/rag/prompts.py tests/unit/test_explain_service.py
git commit -m "$(cat <<'EOF'
feat(rag): add EXPLAIN_WHY_SYSTEM_PROMPT for F3 explain endpoint

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Add `ExplainRequest` and `ExplainResponse` to `schemas.py`

**Files:**
- Modify: `app/modules/rag/schemas.py`

- [ ] **Step 2.1: Write failing schema tests**

Append to `tests/unit/test_explain_service.py`:

```python
from uuid import UUID, uuid4

from pydantic import ValidationError
import pytest

from app.modules.rag.schemas import ExplainRequest, ExplainResponse, SourceOut


def test_explain_request_requires_topic():
    with pytest.raises(ValidationError):
        ExplainRequest(topic="")  # empty string — min_length=1


def test_explain_request_topic_only():
    req = ExplainRequest(topic="EGT spike during engine start")
    assert req.topic == "EGT spike during engine start"
    assert req.context is None
    assert req.system_state is None
    assert req.aircraft_id is None


def test_explain_request_all_fields():
    aid = uuid4()
    req = ExplainRequest(
        topic="EGT spike",
        context="Su-30MKI cold start",
        system_state={"engine_n1": "23%"},
        aircraft_id=aid,
    )
    assert req.aircraft_id == aid
    assert req.system_state == {"engine_n1": "23%"}


def test_explain_response_structure():
    resp = ExplainResponse(
        explanation="EGT spikes because...",
        grounded="strong",
        sources=[],
        suggestions=[],
        moderation=None,
    )
    assert resp.grounded == "strong"
    assert resp.moderation is None
```

- [ ] **Step 2.2: Run tests to verify they fail**

```
.venv/Scripts/python.exe -m pytest tests/unit/test_explain_service.py -k "explain_request or explain_response" -v
```

Expected: `ImportError: cannot import name 'ExplainRequest'`

- [ ] **Step 2.3: Add `ExplainRequest` and `ExplainResponse` to `app/modules/rag/schemas.py`**

Append at the end of the file:

```python
class ExplainRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=2000)
    context: str | None = None
    system_state: dict | None = None
    aircraft_id: UUID | None = None


class ExplainResponse(BaseModel):
    explanation: str
    grounded: str  # strong | soft | refused | blocked
    sources: list[SourceOut] = []
    suggestions: list[SourceOut] = []
    moderation: dict | None = None
```

- [ ] **Step 2.4: Run tests to verify they pass**

```
.venv/Scripts/python.exe -m pytest tests/unit/test_explain_service.py -k "explain_request or explain_response" -v
```

Expected: 4 passed

- [ ] **Step 2.5: Lint**

```
.venv/Scripts/python.exe -m ruff check app/modules/rag/schemas.py tests/unit/test_explain_service.py
```

- [ ] **Step 2.6: Commit**

```bash
git add app/modules/rag/schemas.py tests/unit/test_explain_service.py
git commit -m "$(cat <<'EOF'
feat(rag): add ExplainRequest and ExplainResponse schemas

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Refactor service.py helpers to module-level + add ExplainService

**Files:**
- Modify: `app/modules/rag/service.py`

**Context:** `_aircraft_context_label` and `_resolve_sources` are currently instance methods on `RAGService`. Both ExplainService and RAGService need them. Refactor them to module-level async functions and update RAGService to call them directly (passing `db`). `_build_cfg` is already module-level — no change needed.

The moderator (`app.modules.rag.moderator`) does not exist on this branch (it lives in `feat/content-moderation-shreyansh`). ExplainService must import it lazily and fall back to a pass-through if the module is absent. This makes F3 safe to merge independently.

- [ ] **Step 3.1: Write failing ExplainService unit tests**

Append to `tests/unit/test_explain_service.py`:

```python
import json
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Shared fake types ────────────────────────────────────────────────────────

@dataclass
class FakeHit:
    score: float
    citation_keys: list
    content: str = "content"
    chunk_id: str = "cid"
    section_id: str = "sid"
    page_number: int | None = None
    mmr_rank: int = 0
    included: bool = False


class FakeUser:
    id = "user-123"
    roles = ["trainee"]


class FakeInstructor:
    id = "instr-456"
    roles = ["instructor"]


# ── ExplainService import ────────────────────────────────────────────────────

from app.modules.rag.service import ExplainService


# ── Query construction ───────────────────────────────────────────────────────

def test_retrieval_query_topic_only():
    """Without context, retrieval query == topic."""
    topic = "EGT spike during engine start"
    context = None
    expected = topic
    result = topic if not context else f"{topic} ({context})"
    assert result == expected


def test_retrieval_query_with_context():
    """With context, retrieval query appends context in parens."""
    topic = "EGT spike during engine start"
    context = "Su-30MKI, AL-31FP engine, cold weather start"
    result = topic if not context else f"{topic} ({context})"
    assert result == "EGT spike during engine start (Su-30MKI, AL-31FP engine, cold weather start)"


# ── Refusal short-circuit ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_explain_refusal_short_circuit():
    """When grounder returns refused, ExplainService skips LLM and returns refusal shape."""
    fake_db = MagicMock()

    svc = ExplainService(fake_db)

    refused_decision = {
        "grounded": "refused",
        "citation_keys": [],
        "included_hits": [],
        "suggestions": [{"citation_key": "ABC-1", "score": 0.55, "content": "x", "page_number": None}],
    }

    with (
        patch("app.modules.rag.service.retrieve", new=AsyncMock(return_value=([], {}))),
        patch("app.modules.rag.service.decide", return_value=refused_decision),
        patch.object(svc, "_resolve_sources", new=AsyncMock(return_value=[])),
    ):
        result = await svc.explain(
            topic="unknown topic",
            context=None,
            system_state=None,
            aircraft_id=None,
            user=FakeUser(),
        )

    assert result["grounded"] == "refused"
    assert result["sources"] == []
    assert result["moderation"] is None
    assert "don't have approved source material" in result["explanation"].lower() or result["explanation"]


# ── Prompt formatting ────────────────────────────────────────────────────────

def test_prompt_formats_trainee_audience():
    from app.modules.rag.prompts import EXPLAIN_WHY_SYSTEM_PROMPT
    rendered = EXPLAIN_WHY_SYSTEM_PROMPT.format(
        audience_label="trainee",
        aircraft_context="general aviation",
        system_state_summary="(none)",
    )
    assert "trainee" in rendered
    assert "general aviation" in rendered
    assert "(none)" in rendered


def test_prompt_formats_instructor_audience():
    from app.modules.rag.prompts import EXPLAIN_WHY_SYSTEM_PROMPT
    rendered = EXPLAIN_WHY_SYSTEM_PROMPT.format(
        audience_label="instructor",
        aircraft_context="Su-30MKI",
        system_state_summary='{"engine_n1": "23%"}',
    )
    assert "instructor" in rendered
    assert "Su-30MKI" in rendered


def test_audience_label_derivation_trainee():
    user = FakeUser()
    user_roles = set(getattr(user, "roles", []))
    label = "instructor" if user_roles & {"admin", "instructor"} else "trainee"
    assert label == "trainee"


def test_audience_label_derivation_instructor():
    user = FakeInstructor()
    user_roles = set(getattr(user, "roles", []))
    label = "instructor" if user_roles & {"admin", "instructor"} else "trainee"
    assert label == "instructor"


def test_system_state_summary_none():
    system_state = None
    summary = json.dumps(system_state) if system_state else "(none)"
    assert summary == "(none)"


def test_system_state_summary_dict():
    system_state = {"engine_n1": "23%", "oil_temp": "low"}
    summary = json.dumps(system_state) if system_state else "(none)"
    assert "engine_n1" in summary
    assert "oil_temp" in summary
```

- [ ] **Step 3.2: Run tests to verify they fail**

```
.venv/Scripts/python.exe -m pytest tests/unit/test_explain_service.py -k "ExplainService or refusal or prompt or audience or system_state or retrieval_query" -v
```

Expected: `ImportError` on `ExplainService` or `AttributeError`

- [ ] **Step 3.3: Refactor service.py — promote helpers to module-level**

In `app/modules/rag/service.py`, do the following:

**a)** After the existing `_build_cfg` and `_system_prompt` functions (around line 47), add these two module-level async functions (copy the logic from the RAGService methods, add `db` parameter):

```python
async def _aircraft_context_label(db: AsyncSession, aircraft_id: UUID | None) -> str:
    if not aircraft_id:
        return "general aviation"
    from app.modules.content.models import Aircraft
    result = await db.execute(select(Aircraft).where(Aircraft.id == aircraft_id))
    a = result.scalar_one_or_none()
    return a.display_name if a else "general aviation"


async def _resolve_sources(
    db: AsyncSession, citation_keys: list[str], scores_by_key: dict[str, float]
) -> list[dict]:
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
```

**b)** Update `RAGService._aircraft_context_label` and `RAGService._resolve_sources` to delegate to module-level functions:

```python
    async def _aircraft_context_label(self, aircraft_id: UUID | None) -> str:
        return await _aircraft_context_label(self.db, aircraft_id)

    async def _resolve_sources(self, citation_keys: list[str], scores_by_key: dict[str, float]) -> list[dict]:
        return await _resolve_sources(self.db, citation_keys, scores_by_key)
```

**c)** Add the `ExplainService` class at the bottom of `service.py` (after `RAGService`):

```python
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
        import json

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

        # 5. Build messages + call gateway
        aircraft_label = await self._aircraft_context_label(aircraft_id)
        user_roles = set(getattr(user, "roles", []))
        audience_label = "instructor" if user_roles & {"admin", "instructor"} else "trainee"
        sys_state_summary = json.dumps(system_state) if system_state else "(none)"

        from app.modules.rag.prompts import EXPLAIN_WHY_SYSTEM_PROMPT
        sys_prompt = EXPLAIN_WHY_SYSTEM_PROMPT.format(
            audience_label=audience_label,
            aircraft_context=aircraft_label,
            system_state_summary=sys_state_summary,
        )
        messages = [
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

        # 6. Moderate — lazy import; pass-through if moderator not installed yet
        try:
            from app.modules.rag.moderator import moderate as _moderate
            mod_result = await _moderate(
                ai_result["response"], decision["grounded"], decision["citation_keys"], self.db,
            )
        except ImportError:
            # Moderator not available in this branch — treat as pass
            from dataclasses import dataclass, field as dc_field

            @dataclass
            class _PassResult:
                action: str = "pass"
                primary: object = None
                redacted_text: str | None = None
                all: list = dc_field(default_factory=list)

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
```

Also add `import json` at the top of the explain method (already inside the method above — keep it there to avoid global import side effects on import time), and make sure `EXPLAIN_WHY_SYSTEM_PROMPT` is in the deferred import inside the method.

- [ ] **Step 3.4: Run unit tests**

```
.venv/Scripts/python.exe -m pytest tests/unit/test_explain_service.py -v
```

Expected: all tests pass. If `test_explain_refusal_short_circuit` fails because of mock patching, check that the patch targets match the import bindings: `app.modules.rag.service.retrieve` and `app.modules.rag.service.decide`.

- [ ] **Step 3.5: Run existing RAGService unit tests to verify no regression**

```
.venv/Scripts/python.exe -m pytest tests/unit/test_rag_grounder.py tests/unit/test_rag_mmr.py tests/unit/test_rag_rewriter.py -v
```

Expected: all pass

- [ ] **Step 3.6: Lint**

```
.venv/Scripts/python.exe -m ruff check app/modules/rag/service.py tests/unit/test_explain_service.py
```

- [ ] **Step 3.7: Commit**

```bash
git add app/modules/rag/service.py tests/unit/test_explain_service.py
git commit -m "$(cat <<'EOF'
feat(rag): add ExplainService with module-level helper refactor

Refactors _aircraft_context_label and _resolve_sources to module-level
helpers shared between RAGService and ExplainService. Moderator call
uses lazy import with pass-through fallback until F2 branch merges.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Add `POST /explain` endpoint to `router.py`

**Files:**
- Modify: `app/modules/ai_assistant/router.py`

- [ ] **Step 4.1: Write failing integration tests**

Create `tests/integration/test_explain_endpoint.py`:

```python
"""Integration tests for POST /api/v1/ai-assistant/explain (F3)."""
import asyncio
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.modules.content.models import ContentReference
from app.modules.rag.tasks import embed_source
from tests.fixtures.synthetic_fcom import seed_synthetic_fcom


# ── Helpers ──────────────────────────────────────────────────────────────────

async def fake_embed_factory(*args, **kwargs):
    texts = args[0] if args else kwargs.get("texts", [])
    return {
        "embeddings": [[0.1] * 1536 for _ in texts],
        "model": "text-embedding-3-small",
        "usage": {"total_tokens": 100},
    }


async def _ingest(db_session):
    source = await seed_synthetic_fcom(db_session)
    await db_session.commit()
    with patch("app.modules.ai.service.AIService") as mock_ai:
        mock_ai.return_value.embed = AsyncMock(side_effect=fake_embed_factory)
        await asyncio.to_thread(embed_source, str(source.id))
    refs = (await db_session.execute(
        select(ContentReference).where(ContentReference.source_id == source.id)
    )).scalars().all()
    return source, [r.citation_key for r in refs]


def _fake_complete_factory(primary_key: str):
    async def fake_complete(req, user_id):
        return {
            "response": f"EGT spikes because of fuel introduction. [{primary_key}]",
            "provider": "gemini",
            "model": "gemini-1.5-pro",
            "cached": False,
            "usage": {"prompt_tokens": 10, "completion_tokens": 30, "cost_usd": 0.0001},
            "citations": req.context_citations,
            "request_id": "req_explain_1",
        }
    return fake_complete


# ── Tests ─────────────────────────────────────────────────────────────────────

async def test_explain_returns_grounded_explanation(client, db_session):
    """Happy path: grounded explanation with sources returned."""
    _source, citation_keys = await _ingest(db_session)
    primary_key = citation_keys[0]

    from app.main import app
    from app.modules.auth.deps import get_current_user
    from app.modules.auth.models import User
    from app.modules.auth.schemas import CurrentUser

    real_user = User(
        id=uuid.uuid4(),
        email=f"test-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="x",
        full_name="Explain Test User",
    )
    db_session.add(real_user)
    await db_session.commit()
    fake_user = CurrentUser(id=str(real_user.id), roles=["trainee"], jti="")
    app.dependency_overrides[get_current_user] = lambda: fake_user

    try:
        with (
            patch("app.modules.ai.service.AIService") as mock_ai_cls,
            patch("app.modules.rag.service.AIService", new=mock_ai_cls),
        ):
            instance = mock_ai_cls.return_value
            instance.embed = AsyncMock(side_effect=fake_embed_factory)
            instance.complete = AsyncMock(side_effect=_fake_complete_factory(primary_key))

            resp = await client.post(
                "/api/v1/ai-assistant/explain",
                json={"topic": "EGT spike during engine start"},
            )
            assert resp.status_code == 200, resp.text
            data = resp.json()["data"]
            assert "explanation" in data
            assert data["grounded"] in ("strong", "soft")
            assert primary_key in data["explanation"]
            returned_keys = {s["citation_key"] for s in data["sources"]}
            assert returned_keys & set(citation_keys)
    finally:
        app.dependency_overrides.pop(get_current_user, None)


async def test_explain_no_aircraft_searches_general(client, db_session):
    """Without aircraft_id, retrieval proceeds with no scope filter."""
    _source, citation_keys = await _ingest(db_session)
    primary_key = citation_keys[0]

    from app.main import app
    from app.modules.auth.deps import get_current_user
    from app.modules.auth.models import User
    from app.modules.auth.schemas import CurrentUser

    real_user = User(
        id=uuid.uuid4(),
        email=f"test-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="x",
        full_name="No Aircraft User",
    )
    db_session.add(real_user)
    await db_session.commit()
    fake_user = CurrentUser(id=str(real_user.id), roles=["trainee"], jti="")
    app.dependency_overrides[get_current_user] = lambda: fake_user

    try:
        with (
            patch("app.modules.ai.service.AIService") as mock_ai_cls,
            patch("app.modules.rag.service.AIService", new=mock_ai_cls),
        ):
            instance = mock_ai_cls.return_value
            instance.embed = AsyncMock(side_effect=fake_embed_factory)
            instance.complete = AsyncMock(side_effect=_fake_complete_factory(primary_key))

            resp = await client.post(
                "/api/v1/ai-assistant/explain",
                json={"topic": "bleed valve before takeoff"},
                # no aircraft_id
            )
            assert resp.status_code == 200, resp.text
            data = resp.json()["data"]
            assert data["grounded"] in ("strong", "soft", "refused")
    finally:
        app.dependency_overrides.pop(get_current_user, None)


async def test_explain_empty_topic_returns_400(client, db_session):
    """Empty topic must return 400 before hitting RAG."""
    from app.main import app
    from app.modules.auth.deps import get_current_user
    from app.modules.auth.models import User
    from app.modules.auth.schemas import CurrentUser

    real_user = User(
        id=uuid.uuid4(),
        email=f"test-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="x",
        full_name="Empty Topic User",
    )
    db_session.add(real_user)
    await db_session.commit()
    fake_user = CurrentUser(id=str(real_user.id), roles=["trainee"], jti="")
    app.dependency_overrides[get_current_user] = lambda: fake_user

    try:
        resp = await client.post(
            "/api/v1/ai-assistant/explain",
            json={"topic": "   "},  # whitespace only — trimmed to empty
        )
        assert resp.status_code == 400, resp.text
        assert "topic" in resp.json()["detail"].lower()
    finally:
        app.dependency_overrides.pop(get_current_user, None)


async def test_explain_unauthenticated_returns_401(client, db_session):
    """No auth header → 401."""
    resp = await client.post(
        "/api/v1/ai-assistant/explain",
        json={"topic": "EGT spike"},
    )
    assert resp.status_code == 401, resp.text


async def test_explain_blocked_by_moderator_returns_blocked_shape(client, db_session):
    """When moderator blocks, response grounded=blocked with moderation field."""
    _source, citation_keys = await _ingest(db_session)
    primary_key = citation_keys[0]

    from app.main import app
    from app.modules.auth.deps import get_current_user
    from app.modules.auth.models import User
    from app.modules.auth.schemas import CurrentUser
    from dataclasses import dataclass, field as dc_field

    real_user = User(
        id=uuid.uuid4(),
        email=f"test-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="x",
        full_name="Blocked Test User",
    )
    db_session.add(real_user)
    await db_session.commit()
    fake_user = CurrentUser(id=str(real_user.id), roles=["trainee"], jti="")
    app.dependency_overrides[get_current_user] = lambda: fake_user

    @dataclass
    class FakeViolation:
        category: str = "classification"
        severity: str = "critical"
        action: str = "block"

    @dataclass
    class FakeModResult:
        action: str = "block"
        primary: FakeViolation = None
        redacted_text: str | None = None
        all: list = dc_field(default_factory=list)

        def __post_init__(self):
            if self.primary is None:
                self.primary = FakeViolation()

    try:
        with (
            patch("app.modules.ai.service.AIService") as mock_ai_cls,
            patch("app.modules.rag.service.AIService", new=mock_ai_cls),
            patch("app.modules.rag.service.ExplainService.explain") as mock_explain,
        ):
            mock_explain.return_value = {
                "explanation": "This response was blocked by the content moderation layer.",
                "grounded": "blocked",
                "sources": [],
                "suggestions": [],
                "moderation": {"violation_type": "classification", "severity": "critical"},
            }

            instance = mock_ai_cls.return_value
            instance.embed = AsyncMock(side_effect=fake_embed_factory)

            resp = await client.post(
                "/api/v1/ai-assistant/explain",
                json={"topic": "TOP SECRET engine specs"},
            )
            assert resp.status_code == 200, resp.text
            data = resp.json()["data"]
            assert data["grounded"] == "blocked"
            assert data["moderation"] is not None
            assert data["moderation"]["violation_type"] == "classification"
    finally:
        app.dependency_overrides.pop(get_current_user, None)
```

- [ ] **Step 4.2: Run integration tests to verify they fail**

```
.venv/Scripts/python.exe -m pytest tests/integration/test_explain_endpoint.py -v --no-header 2>&1 | head -30
```

Expected: `404 Not Found` on the endpoint or `AttributeError`

- [ ] **Step 4.3: Add the `/explain` endpoint to `app/modules/ai_assistant/router.py`**

Add imports for `ExplainService`, `ExplainRequest`, `ExplainResponse`, and `SourceOut` (already imported) at the top of the file. Then add the endpoint after the `send_message` endpoint:

**Add to imports** (modify the existing import block):

```python
from app.modules.rag.schemas import (
    AssistantMessage,
    ChatTurnResponse,
    CreateSessionRequest,
    ExplainRequest,
    ExplainResponse,
    SessionOut,
    SourceOut,
    UserMessage,
)
from app.modules.rag.service import ExplainService, RAGService
```

**Add the endpoint** (insert after `send_message`, before `get_history`):

```python
@router.post(
    "/explain",
    response_model=dict,
    summary="One-shot grounded explanation of an aircraft system behavior",
    description=(
        "Stateless 'explain-why' endpoint for cockpit overlays and module pages. "
        "No session, no history. Returns a grounded educational explanation with citations.\n\n"
        "Only `topic` is required. Optionally pass `context` (e.g., aircraft type + conditions), "
        "`system_state` (live telemetry dict), and `aircraft_id` to scope retrieval."
    ),
    responses={
        400: {"description": "topic is empty or whitespace"},
        401: {"description": "Not authenticated"},
        502: {"description": "All LLM providers unreachable"},
    },
    operation_id="ai_assistant_explain",
)
async def explain(
    body: ExplainRequest,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if not body.topic.strip():
        raise HTTPException(status_code=400, detail="topic is required")

    svc = ExplainService(db)
    result = await svc.explain(
        topic=body.topic.strip(),
        context=body.context,
        system_state=body.system_state,
        aircraft_id=body.aircraft_id,
        user=current_user,
    )

    sources = [SourceOut(**s) for s in result["sources"]]
    suggestions = [SourceOut(**s) for s in result["suggestions"]]

    return {
        "data": ExplainResponse(
            explanation=result["explanation"],
            grounded=result["grounded"],
            sources=sources,
            suggestions=suggestions,
            moderation=result.get("moderation"),
        ).model_dump(mode="json")
    }
```

- [ ] **Step 4.4: Run integration tests**

```
.venv/Scripts/python.exe -m pytest tests/integration/test_explain_endpoint.py -v
```

Expected: all 5 pass. If `test_explain_empty_topic_returns_400` fails — Pydantic `min_length=1` on `ExplainRequest.topic` already rejects empty strings with 422. The whitespace-only case (`"   "`) passes Pydantic but is caught by the endpoint's `if not body.topic.strip()` guard (returns 400). Verify the guard is present.

If `test_explain_unauthenticated_returns_401` returns 422 instead of 401: ensure the `get_current_user` dependency raises `HTTPException(401)` before Pydantic body validation. This is the existing behavior in the project — should work.

- [ ] **Step 4.5: Run all unit tests too**

```
.venv/Scripts/python.exe -m pytest tests/unit/ -v
```

Expected: all pass

- [ ] **Step 4.6: Run full lint**

```
.venv/Scripts/python.exe -m ruff check app/ tests/
```

Expected: no errors

- [ ] **Step 4.7: Commit**

```bash
git add app/modules/ai_assistant/router.py tests/integration/test_explain_endpoint.py
git commit -m "$(cat <<'EOF'
feat(ai-assistant): add POST /explain endpoint (F3 explain-why)

Stateless one-shot grounded educational explanation. Reuses RAG
retriever + grounder + AIService. Moderator path is lazy-import with
pass-through fallback until content-moderation branch merges.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Final verification + push

- [ ] **Step 5.1: Run the full test suite**

```
.venv/Scripts/python.exe -m pytest tests/unit/ tests/integration/test_explain_endpoint.py -v
```

Expected: all pass (skip integration tests that need a live DB if not available locally — CI will pick them up)

- [ ] **Step 5.2: Run ruff on entire app + tests**

```
.venv/Scripts/python.exe -m ruff check app/ tests/
```

Expected: no errors

- [ ] **Step 5.3: Push branch**

```bash
git push -u origin feat/explain-why-shreyansh
```

- [ ] **Step 5.4: Open PR**

```bash
gh pr create \
  --base main \
  --title "Explain-Why System Behavior--shreyansh" \
  --body "$(cat <<'EOF'
## Summary

- Adds `POST /api/v1/ai-assistant/explain` — stateless, one-shot grounded educational explanation endpoint (F3)
- `ExplainService` reuses RAG retriever + grounder + AIService; moderator call is lazy-import with pass-through until content-moderation branch merges
- Response shape mirrors `assistantMessage` from the chat endpoint so the frontend citation renderer reuses the same component

**Spec:** [`docs/superpowers/specs/2026-04-29-explain-why-design.md`](docs/superpowers/specs/2026-04-29-explain-why-design.md)

> **Depends on PR #1 (RAG foundation) and PR #2 (content moderation) merging first — diff will collapse to F3-only changes once those land.**

## Test plan

- [ ] `tests/unit/test_explain_service.py` — prompt placeholders, query construction, refusal short-circuit, audience label derivation, system_state serialization
- [ ] `tests/integration/test_explain_endpoint.py` — grounded happy path, no-aircraft general search, empty topic 400, blocked-by-moderator shape, unauthenticated 401
- [ ] `tests/unit/test_rag_grounder.py` / `test_rag_mmr.py` / `test_rag_rewriter.py` — no regression on existing RAG unit tests
- [ ] Ruff lint passes on `app/` and `tests/`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review Against Spec

| Spec section | Covered? | Task |
|---|---|---|
| §3 Architecture: embed → retrieve → ground → AIService → moderate → return | Yes | Task 3 (ExplainService.explain) |
| §4 Request body: topic, context, system_state, aircraft_id | Yes | Task 2 (ExplainRequest) |
| §4 Response: explanation, grounded, sources, suggestions, moderation | Yes | Task 2 (ExplainResponse) |
| §4 Auth: any authenticated user | Yes | Task 4 (endpoint uses get_current_user, no role gate) |
| §6 EXPLAIN_WHY_SYSTEM_PROMPT with 3 placeholders | Yes | Task 1 |
| §7 ExplainService.explain — query construction | Yes | Task 3 + unit test |
| §7 Refusal short-circuit | Yes | Task 3 + unit test |
| §7 Moderator call | Yes | Task 3 (lazy import fallback) |
| §8 topic empty/whitespace → 400 | Yes | Task 4 endpoint guard + integration test |
| §8 grounder refused → refusal shape | Yes | Task 3 unit test |
| §8 moderator BLOCK → blocked shape | Yes | Integration test (mocked ExplainService.explain) |
| §9 Unit: instantiation, query construction, refusal, prompt formatting | Yes | Task 1 + 3 |
| §9 Integration: happy path, no-aircraft, empty 400, blocked, 401 | Yes | Task 4 |
| No new migrations | Yes | No migration tasks |
| Module-level helper refactor for DRY | Yes | Task 3 (refactor RAGService methods) |
