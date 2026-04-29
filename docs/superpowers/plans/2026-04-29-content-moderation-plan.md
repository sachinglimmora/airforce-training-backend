# Content Moderation Layer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Output-side content moderation for AI responses with database-backed rules, Redis caching, tiered actions (BLOCK / REDACT / LOG), and admin CRUD endpoints.

**Architecture:** Moderator module (`app/modules/rag/moderator.py`) called from `RAGService.answer()` after `AIService.complete()`. 5 detectors (4 rule-based + 1 heuristic for ungrounded). Rules in Postgres, cached in Redis with explicit invalidation on writes. Admin CRUD endpoints under `/rag/moderation/*`.

**Tech Stack:** FastAPI · SQLAlchemy 2.0 async · Postgres + pgvector (already enabled) · Redis · Celery (existing) · pytest-asyncio.

**Spec:** [`docs/superpowers/specs/2026-04-29-content-moderation-design.md`](../specs/2026-04-29-content-moderation-design.md)

---

## Reference

### Naming + types used throughout

```python
# app/modules/rag/moderator.py
from dataclasses import dataclass

Category = Literal["classification", "banned_phrase", "ungrounded", "profanity", "casual"]
Action = Literal["block", "redact", "log", "pass"]
Severity = Literal["critical", "high", "medium", "low"]

@dataclass
class Violation:
    category: Category
    rule_id: uuid.UUID | None  # None for the ungrounded heuristic
    matched_text: str
    action: Action
    severity: Severity
    start: int
    end: int

@dataclass
class CompiledRule:
    rule: ModerationRule  # ORM model
    compiled: re.Pattern

@dataclass
class ModerationResult:
    action: Action  # "block" | "redact" | "log" | "pass"
    primary: Violation | None  # the violation that drove the action (BLOCK/REDACT only)
    redacted_text: str | None  # populated only when action == "redact"
    all: list[Violation]  # every violation that matched (for logging)
```

### File map

```
Create:
  app/modules/rag/moderator.py
  migrations/versions/<auto>_create_moderation_tables.py
  tests/unit/test_moderation.py
  tests/integration/test_moderation_endpoints.py

Modify:
  app/modules/rag/models.py        (+ ModerationRule, ModerationLog)
  app/modules/rag/schemas.py       (+ moderation schemas)
  app/modules/rag/router.py        (+ admin CRUD endpoints, + audit logs view)
  app/modules/rag/service.py       (RAGService.answer wires moderator in)
  app/config.py                    (+ MODERATION_* settings)
```

### Database connection note

All SQL/CLI commands use `.venv/Scripts/python.exe -m <cmd>`. The dev DB is the Render-hosted Postgres (per `.env`). All migrations are additive.

---

# Phase A — Plumbing

## Task A1: Add `ModerationRule` + `ModerationLog` models

**Files:**
- Modify: `app/modules/rag/models.py`

- [ ] **Step 1: Open `app/modules/rag/models.py` and find the import block**

The file currently has `ContentChunk` and `RetrievalLog`. We add two new tables.

- [ ] **Step 2: Append the two new model classes to the end of `app/modules/rag/models.py`**

```python
class ModerationRule(Base):
    __tablename__ = "moderation_rules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    category: Mapped[str] = mapped_column(
        Enum("classification", "banned_phrase", "profanity", "casual", name="moderation_category"),
        nullable=False, index=True,
    )
    pattern: Mapped[str] = mapped_column(Text, nullable=False)
    pattern_type: Mapped[str] = mapped_column(
        Enum("regex", "literal", name="moderation_pattern_type"),
        default="regex", nullable=False,
    )
    action: Mapped[str] = mapped_column(
        Enum("block", "redact", "log", name="moderation_action"),
        nullable=False,
    )
    severity: Mapped[str] = mapped_column(
        Enum("critical", "high", "medium", "low", name="moderation_severity"),
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )


class ModerationLog(Base):
    __tablename__ = "moderation_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_sessions.id"), nullable=True, index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    rule_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("moderation_rules.id"), nullable=True
    )
    category: Mapped[str] = mapped_column(
        Enum("classification", "banned_phrase", "ungrounded", "profanity", "casual",
             name="moderation_log_category"),
        nullable=False,
    )
    matched_text: Mapped[str] = mapped_column(Text, nullable=False)
    original_response: Mapped[str] = mapped_column(Text, nullable=False)
    action_taken: Mapped[str] = mapped_column(
        Enum("block", "redact", "log", name="moderation_action_taken"),
        nullable=False,
    )
    severity: Mapped[str] = mapped_column(
        Enum("critical", "high", "medium", "low", name="moderation_log_severity"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False, index=True
    )
```

- [ ] **Step 3: Verify the module imports cleanly**

Run: `.venv/Scripts/python.exe -c "from app.modules.rag.models import ModerationRule, ModerationLog; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add app/modules/rag/models.py
git commit -m "feat(moderation): add ModerationRule and ModerationLog SQLAlchemy models"
```

---

## Task A2: Alembic migration for moderation tables + seed default rules

**Files:**
- Create: `migrations/versions/<auto>_create_moderation_tables.py`

- [ ] **Step 1: Generate empty migration**

Run: `.venv/Scripts/python.exe -m alembic revision -m "create_moderation_tables"`
Note the generated file path + revision id.

- [ ] **Step 2: Edit the migration's `upgrade()` and `downgrade()` — full body**

Replace the auto-generated stubs. Imports at top should already include `from alembic import op` and `import sqlalchemy as sa`. Add `from sqlalchemy.dialects import postgresql` if missing.

```python
def upgrade() -> None:
    # Enums
    op.execute("CREATE TYPE moderation_category AS ENUM ('classification', 'banned_phrase', 'profanity', 'casual')")
    op.execute("CREATE TYPE moderation_pattern_type AS ENUM ('regex', 'literal')")
    op.execute("CREATE TYPE moderation_action AS ENUM ('block', 'redact', 'log')")
    op.execute("CREATE TYPE moderation_severity AS ENUM ('critical', 'high', 'medium', 'low')")
    op.execute("CREATE TYPE moderation_log_category AS ENUM ('classification', 'banned_phrase', 'ungrounded', 'profanity', 'casual')")
    op.execute("CREATE TYPE moderation_action_taken AS ENUM ('block', 'redact', 'log')")
    op.execute("CREATE TYPE moderation_log_severity AS ENUM ('critical', 'high', 'medium', 'low')")

    # moderation_rules
    op.execute(
        """
        CREATE TABLE moderation_rules (
            id UUID PRIMARY KEY,
            category moderation_category NOT NULL,
            pattern TEXT NOT NULL,
            pattern_type moderation_pattern_type NOT NULL DEFAULT 'regex',
            action moderation_action NOT NULL,
            severity moderation_severity NOT NULL,
            description TEXT NULL,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            created_by UUID NULL REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.create_index("ix_moderation_rules_category", "moderation_rules", ["category"])
    op.create_index("ix_moderation_rules_active", "moderation_rules", ["active"])
    op.create_index("ix_moderation_rules_category_active", "moderation_rules", ["category", "active"])

    # moderation_logs
    op.execute(
        """
        CREATE TABLE moderation_logs (
            id UUID PRIMARY KEY,
            request_id VARCHAR(36) NULL,
            session_id UUID NULL REFERENCES chat_sessions(id),
            user_id UUID NULL,
            rule_id UUID NULL REFERENCES moderation_rules(id),
            category moderation_log_category NOT NULL,
            matched_text TEXT NOT NULL,
            original_response TEXT NOT NULL,
            action_taken moderation_action_taken NOT NULL,
            severity moderation_log_severity NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.create_index("ix_moderation_logs_request_id", "moderation_logs", ["request_id"])
    op.create_index("ix_moderation_logs_session_id", "moderation_logs", ["session_id"])
    op.create_index("ix_moderation_logs_created_at", "moderation_logs", ["created_at"])
    op.create_index("ix_moderation_logs_severity_created_at", "moderation_logs", ["severity", "created_at"])

    # Seed default rules — classification (BLOCK, critical)
    op.execute(
        """
        INSERT INTO moderation_rules (id, category, pattern, pattern_type, action, severity, description, active) VALUES
            (gen_random_uuid(), 'classification', '\\bSECRET//\\w+', 'regex', 'block', 'critical', 'US classification marker SECRET//', TRUE),
            (gen_random_uuid(), 'classification', '\\bTOP\\s+SECRET\\b', 'regex', 'block', 'critical', 'US classification marker TOP SECRET', TRUE),
            (gen_random_uuid(), 'classification', '\\bTS//SCI\\b', 'regex', 'block', 'critical', 'US classification marker TS//SCI', TRUE),
            (gen_random_uuid(), 'classification', '\\bNOFORN\\b', 'regex', 'block', 'critical', 'US classification dissemination control NOFORN', TRUE),
            (gen_random_uuid(), 'classification', '\\bREL\\s+TO\\s+\\w+', 'regex', 'block', 'critical', 'US classification dissemination control REL TO', TRUE),
            (gen_random_uuid(), 'classification', '\\bCONFIDENTIAL//\\w+', 'regex', 'block', 'critical', 'US classification marker CONFIDENTIAL//', TRUE)
        """
    )

    # Seed default rules — profanity (REDACT, medium) — minimal English list
    op.execute(
        """
        INSERT INTO moderation_rules (id, category, pattern, pattern_type, action, severity, description, active) VALUES
            (gen_random_uuid(), 'profanity', '\\bdamn\\b', 'regex', 'redact', 'medium', 'Mild profanity', TRUE),
            (gen_random_uuid(), 'profanity', '\\bhell\\b', 'regex', 'redact', 'medium', 'Mild profanity', TRUE),
            (gen_random_uuid(), 'profanity', '\\bcrap\\b', 'regex', 'redact', 'medium', 'Mild profanity', TRUE),
            (gen_random_uuid(), 'profanity', '\\bshit\\b', 'regex', 'redact', 'medium', 'Profanity', TRUE),
            (gen_random_uuid(), 'profanity', '\\bfuck\\w*', 'regex', 'redact', 'medium', 'Profanity', TRUE),
            (gen_random_uuid(), 'profanity', '\\bbitch\\b', 'regex', 'redact', 'medium', 'Profanity', TRUE),
            (gen_random_uuid(), 'profanity', '\\bass\\b', 'regex', 'redact', 'medium', 'Profanity', TRUE)
        """
    )

    # Seed default rules — casual register (LOG, low)
    op.execute(
        """
        INSERT INTO moderation_rules (id, category, pattern, pattern_type, action, severity, description, active) VALUES
            (gen_random_uuid(), 'casual', '\\b(lol|lmao|haha|hehe)\\b', 'regex', 'log', 'low', 'Casual interjection', TRUE),
            (gen_random_uuid(), 'casual', '\\b(dude|guys)\\b', 'regex', 'log', 'low', 'Informal address', TRUE),
            (gen_random_uuid(), 'casual', '\\b(gonna|wanna|kinda|gotta)\\b', 'regex', 'log', 'low', 'Informal contraction', TRUE)
        """
    )


def downgrade() -> None:
    op.drop_index("ix_moderation_logs_severity_created_at", table_name="moderation_logs")
    op.drop_index("ix_moderation_logs_created_at", table_name="moderation_logs")
    op.drop_index("ix_moderation_logs_session_id", table_name="moderation_logs")
    op.drop_index("ix_moderation_logs_request_id", table_name="moderation_logs")
    op.execute("DROP TABLE moderation_logs")
    op.drop_index("ix_moderation_rules_category_active", table_name="moderation_rules")
    op.drop_index("ix_moderation_rules_active", table_name="moderation_rules")
    op.drop_index("ix_moderation_rules_category", table_name="moderation_rules")
    op.execute("DROP TABLE moderation_rules")
    op.execute("DROP TYPE moderation_log_severity")
    op.execute("DROP TYPE moderation_action_taken")
    op.execute("DROP TYPE moderation_log_category")
    op.execute("DROP TYPE moderation_severity")
    op.execute("DROP TYPE moderation_action")
    op.execute("DROP TYPE moderation_pattern_type")
    op.execute("DROP TYPE moderation_category")
```

- [ ] **Step 3: Run migration**

Run: `.venv/Scripts/python.exe -m alembic upgrade head`
Expected: `Running upgrade ... -> <new_rev>, create_moderation_tables`

- [ ] **Step 4: Verify tables + seed rows**

Run:
```
.venv/Scripts/python.exe -c "
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from app.config import get_settings
async def chk():
    e = create_async_engine(get_settings().DATABASE_URL)
    async with e.connect() as c:
        for tbl in ('moderation_rules', 'moderation_logs'):
            cnt = (await c.execute(text(f'SELECT count(*) FROM {tbl}'))).scalar()
            print(f'{tbl}: {cnt} rows')
        cats = (await c.execute(text('SELECT category, count(*) FROM moderation_rules GROUP BY category ORDER BY category'))).all()
        print('by category:', list(cats))
    await e.dispose()
asyncio.run(chk())
"
```
Expected: `moderation_rules: 16 rows`, `moderation_logs: 0 rows`, `by category: [('casual', 3), ('classification', 6), ('profanity', 7)]`

- [ ] **Step 5: Commit**

```bash
git add migrations/versions/<rev>_create_moderation_tables.py
git commit -m "feat(moderation): alembic migration for moderation tables + seed default rules"
```

---

## Task A3: Add moderation Pydantic schemas

**Files:**
- Modify: `app/modules/rag/schemas.py`

- [ ] **Step 1: Append to `app/modules/rag/schemas.py`**

```python
# ─── Moderation ──────────────────────────────────────────────────────────


class ModerationRuleIn(BaseModel):
    category: str = Field(pattern="^(classification|banned_phrase|profanity|casual)$")
    pattern: str = Field(min_length=1, max_length=500)
    pattern_type: str = Field(default="regex", pattern="^(regex|literal)$")
    action: str = Field(pattern="^(block|redact|log)$")
    severity: str = Field(pattern="^(critical|high|medium|low)$")
    description: str | None = None
    active: bool = True


class ModerationRuleUpdate(BaseModel):
    category: str | None = Field(default=None, pattern="^(classification|banned_phrase|profanity|casual)$")
    pattern: str | None = Field(default=None, min_length=1, max_length=500)
    pattern_type: str | None = Field(default=None, pattern="^(regex|literal)$")
    action: str | None = Field(default=None, pattern="^(block|redact|log)$")
    severity: str | None = Field(default=None, pattern="^(critical|high|medium|low)$")
    description: str | None = None
    active: bool | None = None


class ModerationRuleOut(BaseModel):
    id: UUID
    category: str
    pattern: str
    pattern_type: str
    action: str
    severity: str
    description: str | None
    active: bool
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ModerationLogOut(BaseModel):
    id: UUID
    request_id: str | None
    session_id: UUID | None
    user_id: UUID | None
    rule_id: UUID | None
    category: str
    matched_text: str
    original_response: str
    action_taken: str
    severity: str
    created_at: datetime

    model_config = {"from_attributes": True}
```

- [ ] **Step 2: Verify imports**

Run: `.venv/Scripts/python.exe -c "from app.modules.rag.schemas import ModerationRuleIn, ModerationRuleOut, ModerationRuleUpdate, ModerationLogOut; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add app/modules/rag/schemas.py
git commit -m "feat(moderation): add ModerationRuleIn/Out + ModerationLogOut schemas"
```

---

## Task A4: Add MODERATION_* settings to `app/config.py`

**Files:**
- Modify: `app/config.py`

- [ ] **Step 1: Add the moderation settings block to the `Settings` class**

Find the `# ─── RAG ──` block we added previously. Append AFTER all the existing RAG settings (e.g., after `CHAT_SESSION_AUTO_CLOSE_DAYS`):

```python
    # ─── Moderation ─────────────────────────────────────────────────────────
    MODERATION_ENABLED: bool = True
    MODERATION_CACHE_TTL_S: int = 60
    MODERATION_FAIL_OPEN: bool = True
    MODERATION_LOG_TRUNCATE_RESPONSE: int = 4000
    MODERATION_LOG_TRUNCATE_MATCH: int = 500
```

- [ ] **Step 2: Verify config loads**

Run: `.venv/Scripts/python.exe -c "from app.config import get_settings; s=get_settings(); print(s.MODERATION_ENABLED, s.MODERATION_CACHE_TTL_S, s.MODERATION_FAIL_OPEN)"`
Expected: `True 60 True`

- [ ] **Step 3: Commit**

```bash
git add app/config.py
git commit -m "feat(config): add MODERATION_* settings"
```

---

# Phase B — Core moderation logic (TDD)

## Task B1: Create `moderator.py` skeleton with dataclasses

**Files:**
- Create: `app/modules/rag/moderator.py`

- [ ] **Step 1: Create the file with dataclasses + module-level constants**

```python
"""Output-side content moderation for AI responses. See spec §1-§9."""

import re
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Literal

import structlog

from app.config import get_settings

log = structlog.get_logger()
_settings = get_settings()

Category = Literal["classification", "banned_phrase", "ungrounded", "profanity", "casual"]
Action = Literal["block", "redact", "log", "pass"]
Severity = Literal["critical", "high", "medium", "low"]

_SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}
_CITATION_RE = re.compile(r"\[([\w\-\.]+)\]")
_CACHE_KEY = "moderation_rules:v1"


@dataclass
class Violation:
    category: Category
    rule_id: uuid.UUID | None  # None for the ungrounded heuristic
    matched_text: str
    action: Action
    severity: Severity
    start: int
    end: int


@dataclass
class CompiledRule:
    rule_id: uuid.UUID
    category: Category
    action: Action
    severity: Severity
    compiled: re.Pattern


@dataclass
class ModerationResult:
    action: Action
    primary: Violation | None = None
    redacted_text: str | None = None
    all: list[Violation] = field(default_factory=list)


# Detector + orchestration functions defined in subsequent tasks
async def moderate(text: str, grounded_state: str, citations: list[str], db) -> ModerationResult:
    raise NotImplementedError  # implemented in Task B8
```

- [ ] **Step 2: Verify import**

Run: `.venv/Scripts/python.exe -c "from app.modules.rag.moderator import Violation, CompiledRule, ModerationResult, moderate; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add app/modules/rag/moderator.py
git commit -m "feat(moderation): scaffold moderator module with dataclasses"
```

---

## Task B2: Pattern-based detector for classification + banned_phrase

**Files:**
- Modify: `app/modules/rag/moderator.py`
- Create: `tests/unit/test_moderation.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_moderation.py` with:

```python
import re
import uuid

import pytest

from app.modules.rag.moderator import CompiledRule, Violation, _check_pattern_category


def _rule(category, action, severity, pattern_str):
    return CompiledRule(
        rule_id=uuid.uuid4(),
        category=category,
        action=action,
        severity=severity,
        compiled=re.compile(pattern_str, re.IGNORECASE),
    )


def test_pattern_no_match_returns_empty():
    rules = [_rule("classification", "block", "critical", r"\bSECRET//\w+")]
    assert _check_pattern_category("clean text here", rules) == []


def test_pattern_single_match_returns_one_violation():
    rules = [_rule("classification", "block", "critical", r"\bSECRET//\w+")]
    out = _check_pattern_category("contents marked SECRET//NOFORN here", rules)
    assert len(out) == 1
    v = out[0]
    assert v.category == "classification"
    assert v.action == "block"
    assert v.severity == "critical"
    assert v.matched_text == "SECRET//NOFORN"
    assert v.start == 16


def test_pattern_multiple_matches_in_one_text():
    rules = [_rule("classification", "block", "critical", r"\bSECRET//\w+")]
    out = _check_pattern_category("SECRET//A and SECRET//B both", rules)
    assert len(out) == 2


def test_pattern_multiple_rules_same_text():
    rules = [
        _rule("classification", "block", "critical", r"\bNOFORN\b"),
        _rule("classification", "block", "critical", r"\bREL\s+TO\s+\w+"),
    ]
    out = _check_pattern_category("NOFORN and REL TO USA both fire", rules)
    assert len(out) == 2
    cats = {v.matched_text for v in out}
    assert cats == {"NOFORN", "REL TO USA"}


def test_pattern_empty_rules_list():
    assert _check_pattern_category("anything", []) == []
```

- [ ] **Step 2: Run, expect FAIL (function not defined yet)**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_moderation.py -v --no-cov`
Expected: ImportError on `_check_pattern_category`.

- [ ] **Step 3: Implement `_check_pattern_category` in `app/modules/rag/moderator.py`**

Add this function ABOVE the `moderate` stub:

```python
def _check_pattern_category(text: str, rules: list[CompiledRule]) -> list[Violation]:
    """Generic pattern detector — used for both classification and banned_phrase categories."""
    violations: list[Violation] = []
    for cr in rules:
        for match in cr.compiled.finditer(text):
            violations.append(Violation(
                category=cr.category,
                rule_id=cr.rule_id,
                matched_text=match.group(0),
                action=cr.action,
                severity=cr.severity,
                start=match.start(),
                end=match.end(),
            ))
    return violations
```

- [ ] **Step 4: Run tests, expect PASS**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_moderation.py -v --no-cov`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add app/modules/rag/moderator.py tests/unit/test_moderation.py
git commit -m "feat(moderation): _check_pattern_category detector for classification + banned_phrase"
```

---

## Task B3: Ungrounded-output heuristic

**Files:**
- Modify: `app/modules/rag/moderator.py`
- Modify: `tests/unit/test_moderation.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/unit/test_moderation.py`:

```python
from app.modules.rag.moderator import _check_ungrounded


def test_ungrounded_strong_with_brackets_returns_empty():
    out = _check_ungrounded("Per [FCOM-3.2.1], engine start...", "strong", ["FCOM-3.2.1"])
    assert out == []


def test_ungrounded_strong_without_brackets_returns_block_violation():
    out = _check_ungrounded("Engine starts when you press the button.", "strong", ["FCOM-3.2.1"])
    assert len(out) == 1
    v = out[0]
    assert v.category == "ungrounded"
    assert v.action == "block"
    assert v.severity == "high"
    assert v.rule_id is None


def test_ungrounded_soft_grounding_no_check():
    out = _check_ungrounded("Engine starts.", "soft", ["FCOM-3.2.1"])
    assert out == []


def test_ungrounded_no_citations_no_check():
    out = _check_ungrounded("anything", "strong", [])
    assert out == []


def test_ungrounded_refused_state_no_check():
    out = _check_ungrounded("anything", "refused", ["FCOM-3.2.1"])
    assert out == []
```

- [ ] **Step 2: Run, expect FAIL**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_moderation.py -v --no-cov -k ungrounded`
Expected: ImportError on `_check_ungrounded`.

- [ ] **Step 3: Implement `_check_ungrounded` in `moderator.py`**

Add below `_check_pattern_category`:

```python
def _check_ungrounded(text: str, grounded_state: str, citations: list[str]) -> list[Violation]:
    """Heuristic: when grounded='strong', the response must contain at least one [citation_key].

    Skipped for 'soft' (already caveated) and 'refused' (no LLM response to check).
    """
    if grounded_state != "strong" or not citations:
        return []
    refs_found = _CITATION_RE.findall(text)
    if refs_found:
        return []
    return [Violation(
        category="ungrounded",
        rule_id=None,
        matched_text="",
        action="block",
        severity="high",
        start=0,
        end=0,
    )]
```

- [ ] **Step 4: Run, expect PASS**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_moderation.py -v --no-cov`
Expected: 10 passed (5 + 5).

- [ ] **Step 5: Commit**

```bash
git add app/modules/rag/moderator.py tests/unit/test_moderation.py
git commit -m "feat(moderation): _check_ungrounded heuristic for strong-grounding citations"
```

---

## Task B4: Profanity detector (REDACT — modifies text)

**Files:**
- Modify: `app/modules/rag/moderator.py`
- Modify: `tests/unit/test_moderation.py`

- [ ] **Step 1: Append failing tests**

```python
from app.modules.rag.moderator import _check_profanity


def test_profanity_no_match_returns_text_unchanged():
    rules = [_rule("profanity", "redact", "medium", r"\bdamn\b")]
    redacted, viols = _check_profanity("clean engine start", rules)
    assert redacted == "clean engine start"
    assert viols == []


def test_profanity_single_match_replaces_with_stars():
    rules = [_rule("profanity", "redact", "medium", r"\bdamn\b")]
    redacted, viols = _check_profanity("the damn engine", rules)
    assert redacted == "the **** engine"
    assert len(viols) == 1
    assert viols[0].matched_text == "damn"


def test_profanity_multiple_matches_all_redacted():
    rules = [_rule("profanity", "redact", "medium", r"\bdamn\b")]
    redacted, viols = _check_profanity("damn this damn engine", rules)
    assert redacted == "**** this **** engine"
    assert len(viols) == 2


def test_profanity_multiple_rules_chained():
    rules = [
        _rule("profanity", "redact", "medium", r"\bdamn\b"),
        _rule("profanity", "redact", "medium", r"\bhell\b"),
    ]
    redacted, viols = _check_profanity("damn hell yes", rules)
    assert "*" in redacted
    assert "damn" not in redacted
    assert "hell" not in redacted
    assert len(viols) == 2
```

- [ ] **Step 2: Run, expect FAIL**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_moderation.py -v --no-cov -k profanity`
Expected: ImportError on `_check_profanity`.

- [ ] **Step 3: Implement `_check_profanity`**

Add below `_check_ungrounded`:

```python
def _check_profanity(text: str, rules: list[CompiledRule]) -> tuple[str, list[Violation]]:
    """Profanity detector — returns (redacted_text, violations).

    Each match is replaced with '*' of equal length so the response stays the same shape.
    """
    violations: list[Violation] = []
    redacted = text
    for cr in rules:
        def _replace(m: re.Match, _cr=cr) -> str:
            violations.append(Violation(
                category=_cr.category,
                rule_id=_cr.rule_id,
                matched_text=m.group(0),
                action=_cr.action,
                severity=_cr.severity,
                start=m.start(),
                end=m.end(),
            ))
            return "*" * len(m.group(0))
        redacted = cr.compiled.sub(_replace, redacted)
    return redacted, violations
```

- [ ] **Step 4: Run, expect PASS**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_moderation.py -v --no-cov`
Expected: 14 passed (10 + 4).

- [ ] **Step 5: Commit**

```bash
git add app/modules/rag/moderator.py tests/unit/test_moderation.py
git commit -m "feat(moderation): _check_profanity detector with REDACT replacement"
```

---

## Task B5: Casual register detector (LOG only)

**Files:**
- Modify: `app/modules/rag/moderator.py`
- Modify: `tests/unit/test_moderation.py`

- [ ] **Step 1: Append failing tests**

```python
from app.modules.rag.moderator import _check_casual


def test_casual_no_match_returns_empty():
    rules = [_rule("casual", "log", "low", r"\blol\b")]
    assert _check_casual("formal text", rules) == []


def test_casual_match_returns_log_violations():
    rules = [_rule("casual", "log", "low", r"\b(lol|haha)\b")]
    out = _check_casual("yeah lol haha that's funny", rules)
    assert len(out) == 2
    assert all(v.category == "casual" for v in out)
    assert all(v.action == "log" for v in out)
    assert all(v.severity == "low" for v in out)
```

- [ ] **Step 2: Run, expect FAIL**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_moderation.py -v --no-cov -k casual`
Expected: ImportError on `_check_casual`.

- [ ] **Step 3: Implement `_check_casual`**

Casual is identical to `_check_pattern_category` semantically (no text mutation, just emit violations). Just call `_check_pattern_category`. Add a thin wrapper for clarity:

```python
def _check_casual(text: str, rules: list[CompiledRule]) -> list[Violation]:
    """Casual register detector — same shape as pattern category but always action='log'."""
    return _check_pattern_category(text, rules)
```

- [ ] **Step 4: Run, expect PASS**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_moderation.py -v --no-cov`
Expected: 16 passed (14 + 2).

- [ ] **Step 5: Commit**

```bash
git add app/modules/rag/moderator.py tests/unit/test_moderation.py
git commit -m "feat(moderation): _check_casual detector (LOG only)"
```

---

## Task B6: Action precedence resolver

**Files:**
- Modify: `app/modules/rag/moderator.py`
- Modify: `tests/unit/test_moderation.py`

- [ ] **Step 1: Append failing tests**

```python
from app.modules.rag.moderator import _resolve_action


def test_resolve_no_violations_returns_pass():
    out = _resolve_action([], "original text")
    assert out.action == "pass"
    assert out.primary is None
    assert out.all == []


def test_resolve_block_wins_over_redact_and_log():
    block = Violation("classification", uuid.uuid4(), "X", "block", "critical", 0, 1)
    redact = Violation("profanity", uuid.uuid4(), "Y", "redact", "medium", 1, 2)
    out = _resolve_action([redact, block], "original text")
    assert out.action == "block"
    assert out.primary is block


def test_resolve_most_severe_block_wins_when_multiple_blocks():
    high = Violation("banned_phrase", uuid.uuid4(), "A", "block", "high", 0, 1)
    critical = Violation("classification", uuid.uuid4(), "B", "block", "critical", 1, 2)
    out = _resolve_action([high, critical], "original text")
    assert out.action == "block"
    assert out.primary is critical


def test_resolve_redact_uses_redacted_text_when_provided():
    redact = Violation("profanity", uuid.uuid4(), "damn", "redact", "medium", 4, 8)
    out = _resolve_action([redact], "the **** word", redacted_text="the **** word")
    assert out.action == "redact"
    assert out.redacted_text == "the **** word"


def test_resolve_log_only_when_no_block_or_redact():
    log_v = Violation("casual", uuid.uuid4(), "lol", "log", "low", 0, 3)
    out = _resolve_action([log_v], "original text")
    assert out.action == "log"
    assert out.primary is None
    assert log_v in out.all


def test_resolve_all_violations_in_result_regardless_of_action():
    block = Violation("classification", uuid.uuid4(), "X", "block", "critical", 0, 1)
    redact = Violation("profanity", uuid.uuid4(), "Y", "redact", "medium", 1, 2)
    log_v = Violation("casual", uuid.uuid4(), "Z", "log", "low", 2, 3)
    out = _resolve_action([block, redact, log_v], "original text")
    assert out.action == "block"
    assert len(out.all) == 3
```

- [ ] **Step 2: Run, expect FAIL**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_moderation.py -v --no-cov -k resolve`
Expected: ImportError on `_resolve_action`.

- [ ] **Step 3: Implement `_resolve_action` in `moderator.py`**

```python
def _resolve_action(
    violations: list[Violation],
    original_text: str,
    redacted_text: str | None = None,
) -> ModerationResult:
    """Action precedence: BLOCK > REDACT > LOG > PASS.

    Multiple BLOCKs: most-severe wins. All violations are returned in `all` regardless
    of which action drove the result, so they all get logged.
    """
    if not violations:
        return ModerationResult(action="pass", all=[])
    blocks = [v for v in violations if v.action == "block"]
    if blocks:
        primary = max(blocks, key=lambda v: _SEVERITY_RANK.get(v.severity, 0))
        return ModerationResult(action="block", primary=primary, all=violations)
    redacts = [v for v in violations if v.action == "redact"]
    if redacts:
        return ModerationResult(
            action="redact",
            primary=None,
            redacted_text=redacted_text if redacted_text is not None else original_text,
            all=violations,
        )
    return ModerationResult(action="log", primary=None, all=violations)
```

- [ ] **Step 4: Run, expect PASS**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_moderation.py -v --no-cov`
Expected: 22 passed (16 + 6).

- [ ] **Step 5: Commit**

```bash
git add app/modules/rag/moderator.py tests/unit/test_moderation.py
git commit -m "feat(moderation): _resolve_action precedence (BLOCK > REDACT > LOG)"
```

---

## Task B7: Rule loading + Redis cache

**Files:**
- Modify: `app/modules/rag/moderator.py`
- Modify: `tests/unit/test_moderation.py`

- [ ] **Step 1: Append failing tests** (uses mocks for DB + redis)

```python
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.rag.moderator import load_rules, invalidate_cache


def _row(category, pattern, action, severity, pattern_type="regex", active=True):
    r = MagicMock()
    r.id = uuid.uuid4()
    r.category = category
    r.pattern = pattern
    r.pattern_type = pattern_type
    r.action = action
    r.severity = severity
    r.active = active
    return r


async def test_load_rules_from_db_when_cache_miss():
    rows = [_row("classification", r"\bSECRET\b", "block", "critical")]
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(scalars=lambda: MagicMock(all=lambda: rows)))
    with patch("app.modules.rag.moderator._cache_get", new=AsyncMock(return_value=None)) as mock_get, \
         patch("app.modules.rag.moderator._cache_set", new=AsyncMock()) as mock_set:
        out = await load_rules(db)
        assert "classification" in out
        assert len(out["classification"]) == 1
        assert isinstance(out["classification"][0].compiled, re.Pattern)
        mock_get.assert_awaited_once()
        mock_set.assert_awaited_once()


async def test_load_rules_skips_invalid_regex():
    bad = _row("classification", r"[unclosed", "block", "critical")
    good = _row("classification", r"\bSECRET\b", "block", "critical")
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(scalars=lambda: MagicMock(all=lambda: [bad, good])))
    with patch("app.modules.rag.moderator._cache_get", new=AsyncMock(return_value=None)), \
         patch("app.modules.rag.moderator._cache_set", new=AsyncMock()):
        out = await load_rules(db)
        # bad rule skipped, good one kept
        assert len(out["classification"]) == 1


async def test_load_rules_handles_literal_pattern_type():
    row = _row("banned_phrase", "verbatim phrase", "block", "high", pattern_type="literal")
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(scalars=lambda: MagicMock(all=lambda: [row])))
    with patch("app.modules.rag.moderator._cache_get", new=AsyncMock(return_value=None)), \
         patch("app.modules.rag.moderator._cache_set", new=AsyncMock()):
        out = await load_rules(db)
        cr = out["banned_phrase"][0]
        assert cr.compiled.search("contains verbatim phrase here")


async def test_invalidate_cache_calls_redis_del():
    with patch("app.modules.rag.moderator._cache_del", new=AsyncMock()) as mock_del:
        await invalidate_cache()
        mock_del.assert_awaited_once_with(_cache_key())


def _cache_key():
    from app.modules.rag.moderator import _CACHE_KEY
    return _CACHE_KEY
```

- [ ] **Step 2: Run, expect FAIL**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_moderation.py -v --no-cov -k "load_rules or invalidate"`
Expected: ImportError on `load_rules`, `invalidate_cache`.

- [ ] **Step 3: Implement loading + cache helpers in `moderator.py`**

Add:

```python
async def _cache_get(key: str) -> bytes | None:
    import redis.asyncio as aioredis
    try:
        r = aioredis.from_url(_settings.REDIS_URL)
        raw = await r.get(key)
        await r.aclose()
        return raw
    except Exception as exc:
        log.warning("moderation_cache_read_error", error=str(exc))
        return None


async def _cache_set(key: str, value: bytes, ttl: int) -> None:
    import redis.asyncio as aioredis
    try:
        r = aioredis.from_url(_settings.REDIS_URL)
        await r.setex(key, ttl, value)
        await r.aclose()
    except Exception as exc:
        log.warning("moderation_cache_write_error", error=str(exc))


async def _cache_del(key: str) -> None:
    import redis.asyncio as aioredis
    try:
        r = aioredis.from_url(_settings.REDIS_URL)
        await r.delete(key)
        await r.aclose()
    except Exception as exc:
        log.warning("moderation_cache_del_error", error=str(exc))


def _compile_one(pattern: str, pattern_type: str) -> re.Pattern:
    if pattern_type == "literal":
        return re.compile(re.escape(pattern), re.IGNORECASE)
    return re.compile(pattern, re.IGNORECASE)


async def load_rules(db) -> dict[Category, list[CompiledRule]]:
    """Load active rules grouped by category. Compiled patterns are NOT cached
    (re.Pattern doesn't pickle cleanly); the cache stores rule dicts, and
    re-compilation runs on each load. Cheap (~50 patterns max in practice)."""
    import json
    from sqlalchemy import select
    from app.modules.rag.models import ModerationRule

    cached = await _cache_get(_CACHE_KEY)
    if cached:
        try:
            rule_dicts = json.loads(cached)
            return _build_compiled(rule_dicts)
        except Exception as exc:
            log.warning("moderation_cache_decode_error", error=str(exc))

    result = await db.execute(select(ModerationRule).where(ModerationRule.active == True))  # noqa: E712
    rows = result.scalars().all()
    rule_dicts = [
        {
            "id": str(r.id),
            "category": r.category,
            "pattern": r.pattern,
            "pattern_type": r.pattern_type,
            "action": r.action,
            "severity": r.severity,
        }
        for r in rows
    ]

    try:
        await _cache_set(_CACHE_KEY, json.dumps(rule_dicts).encode(), _settings.MODERATION_CACHE_TTL_S)
    except Exception:
        pass  # cache write failure is non-fatal; we still return the loaded rules

    return _build_compiled(rule_dicts)


def _build_compiled(rule_dicts: list[dict]) -> dict[Category, list[CompiledRule]]:
    out: dict[Category, list[CompiledRule]] = defaultdict(list)
    for r in rule_dicts:
        try:
            compiled = _compile_one(r["pattern"], r["pattern_type"])
        except re.error as exc:
            log.error("moderation_rule_compile_failed", rule_id=r["id"], pattern=r["pattern"], error=str(exc))
            continue
        out[r["category"]].append(CompiledRule(
            rule_id=uuid.UUID(r["id"]),
            category=r["category"],
            action=r["action"],
            severity=r["severity"],
            compiled=compiled,
        ))
    return out


async def invalidate_cache() -> None:
    await _cache_del(_CACHE_KEY)
```

- [ ] **Step 4: Run, expect PASS**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_moderation.py -v --no-cov`
Expected: 26 passed (22 + 4).

- [ ] **Step 5: Commit**

```bash
git add app/modules/rag/moderator.py tests/unit/test_moderation.py
git commit -m "feat(moderation): rule loading + Redis cache + invalidation"
```

---

## Task B8: Public `moderate()` orchestration + ENABLED kill switch + FAIL_OPEN behavior

**Files:**
- Modify: `app/modules/rag/moderator.py`
- Modify: `tests/unit/test_moderation.py`

- [ ] **Step 1: Append failing tests**

```python
async def test_moderate_returns_pass_when_disabled():
    with patch.object(_settings, "MODERATION_ENABLED", False):
        out = await moderate("anything", "strong", ["FCOM-3.2.1"], db=None)
        assert out.action == "pass"


async def test_moderate_returns_pass_when_no_rules_and_grounded_with_citation():
    with patch("app.modules.rag.moderator.load_rules", new=AsyncMock(return_value={})):
        out = await moderate("Per [FCOM-3.2.1] start engine.", "strong", ["FCOM-3.2.1"], db=MagicMock())
        assert out.action == "pass"


async def test_moderate_blocks_classification_match():
    rule = _rule("classification", "block", "critical", r"\bSECRET//\w+")
    rules = {"classification": [rule]}
    with patch("app.modules.rag.moderator.load_rules", new=AsyncMock(return_value=rules)):
        out = await moderate("contents SECRET//NOFORN", "strong", [], db=MagicMock())
        assert out.action == "block"
        assert out.primary.category == "classification"


async def test_moderate_redacts_profanity():
    rule = _rule("profanity", "redact", "medium", r"\bdamn\b")
    rules = {"profanity": [rule]}
    with patch("app.modules.rag.moderator.load_rules", new=AsyncMock(return_value=rules)):
        out = await moderate("the damn thing", "strong", [], db=MagicMock())
        assert out.action == "redact"
        assert out.redacted_text == "the **** thing"


async def test_moderate_blocks_ungrounded_strong_response():
    with patch("app.modules.rag.moderator.load_rules", new=AsyncMock(return_value={})):
        out = await moderate("no citation here.", "strong", ["FCOM-3.2.1"], db=MagicMock())
        assert out.action == "block"
        assert out.primary.category == "ungrounded"


async def test_moderate_fail_open_passes_when_db_error():
    failing_db = MagicMock()
    with patch("app.modules.rag.moderator.load_rules", new=AsyncMock(side_effect=Exception("db down"))), \
         patch.object(_settings, "MODERATION_FAIL_OPEN", True):
        out = await moderate("response", "strong", ["FCOM-3.2.1"], db=failing_db)
        # ungrounded heuristic still fires (it doesn't need rules), but the rule-based
        # detectors are skipped. So we get a block from the heuristic, NOT pass.
        # Instead test that fail-open works when grounded='soft' (no heuristic):
        out = await moderate("response", "soft", ["FCOM-3.2.1"], db=failing_db)
        assert out.action == "pass"


async def test_moderate_fail_closed_raises_when_db_error():
    failing_db = MagicMock()
    with patch("app.modules.rag.moderator.load_rules", new=AsyncMock(side_effect=Exception("db down"))), \
         patch.object(_settings, "MODERATION_FAIL_OPEN", False):
        with pytest.raises(Exception):
            await moderate("response", "soft", ["FCOM-3.2.1"], db=failing_db)
```

- [ ] **Step 2: Run, expect FAIL** (NotImplementedError on `moderate`)

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_moderation.py -v --no-cov -k "moderate_"`
Expected: failures with NotImplementedError or related.

- [ ] **Step 3: Implement `moderate()` in `moderator.py`**

Replace the `moderate` stub:

```python
async def moderate(text: str, grounded_state: str, citations: list[str], db) -> ModerationResult:
    """Run all output moderation checks on `text` and return the resolved action.

    See spec §3 for the call shape inside RAGService.answer."""
    if not _settings.MODERATION_ENABLED:
        return ModerationResult(action="pass", all=[])

    # Heuristic check is rule-independent — always run it
    heuristic_violations = _check_ungrounded(text, grounded_state, citations)

    # Rule-based checks — fail-open if rule loading errors
    rule_violations: list[Violation] = []
    redacted_text = text
    try:
        rules_by_cat = await load_rules(db)
    except Exception as exc:
        log.error("moderation_rule_load_failed", error=str(exc))
        if not _settings.MODERATION_FAIL_OPEN:
            raise
        rules_by_cat = {}

    rule_violations += _check_pattern_category(text, rules_by_cat.get("classification", []))
    rule_violations += _check_pattern_category(text, rules_by_cat.get("banned_phrase", []))
    redacted_text, profanity_v = _check_profanity(text, rules_by_cat.get("profanity", []))
    rule_violations += profanity_v
    rule_violations += _check_casual(text, rules_by_cat.get("casual", []))

    all_violations = heuristic_violations + rule_violations
    return _resolve_action(all_violations, text, redacted_text=redacted_text if profanity_v else None)
```

- [ ] **Step 4: Run all moderation tests, expect PASS**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_moderation.py -v --no-cov`
Expected: 33 passed (26 + 7).

- [ ] **Step 5: Commit**

```bash
git add app/modules/rag/moderator.py tests/unit/test_moderation.py
git commit -m "feat(moderation): public moderate() orchestration with kill switch + fail-open"
```

---

# Phase C — Integration into RAGService

## Task C1: Wire `moderate()` into `RAGService.answer()` + add `blocked` grounded state + `moderation` field

**Files:**
- Modify: `app/modules/rag/service.py`
- Modify: `app/modules/rag/schemas.py`
- Modify: `app/modules/ai_assistant/models.py` (extend `grounded_state` enum)
- Create: `migrations/versions/<auto>_add_blocked_to_grounded_state.py`

- [ ] **Step 1: Generate migration to add 'blocked' to the `grounded_state` enum**

Run: `.venv/Scripts/python.exe -m alembic revision -m "add_blocked_to_grounded_state"`

Edit `upgrade()`/`downgrade()`:

```python
def upgrade() -> None:
    op.execute("ALTER TYPE grounded_state ADD VALUE IF NOT EXISTS 'blocked'")


def downgrade() -> None:
    # PostgreSQL has no DROP VALUE for enums prior to v16; this is intentionally a no-op.
    # If you need to roll back, drop and recreate the enum on a new chat_messages migration.
    pass
```

Run migration: `.venv/Scripts/python.exe -m alembic upgrade head`
Expected: `Running upgrade ... -> <new_rev>, add_blocked_to_grounded_state`

- [ ] **Step 2: Update the model's enum literal in `app/modules/ai_assistant/models.py`**

Find `ChatMessage.grounded` and update the Enum values to include `"blocked"`:

```python
    grounded: Mapped[str | None] = mapped_column(
        Enum("strong", "soft", "refused", "blocked", name="grounded_state"), nullable=True
    )
```

Verify: `.venv/Scripts/python.exe -c "from app.modules.ai_assistant.models import ChatMessage; print('ok')"`

- [ ] **Step 3: Add `moderation` field to `AssistantMessage` schema in `app/modules/rag/schemas.py`**

Find `class AssistantMessage(BaseModel):` and add the optional field:

```python
class AssistantMessage(BaseModel):
    id: str
    role: str
    content: str
    timestamp: datetime
    grounded: str | None = None
    sources: list[SourceOut] = []
    suggestions: list[SourceOut] = []
    moderation: dict | None = None  # populated when block/redact fires
```

- [ ] **Step 4: Wire moderator into `RAGService.answer()` in `app/modules/rag/service.py`**

Find the section AFTER `ai_result = await ai_svc.complete(...)` and BEFORE the `assistant_msg = ChatMessage(...)` insertion. Insert the moderation step. Replace this whole section (around lines 160-185 in the current file — inspect first, then replace the equivalent block):

Old block (find it):

```python
        t0 = time.monotonic()
        ai_svc = AIService(self.db)
        ai_result = await ai_svc.complete(
            ...
        )
        latency["llm"] = int((time.monotonic() - t0) * 1000)

        assistant_msg = ChatMessage(
            session_id=session_id, role="assistant", content=ai_result["response"],
            citations=decision["citation_keys"], grounded=decision["grounded"],
        )
        self.db.add(assistant_msg)
```

Replace with:

```python
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

        # ── Output moderation ───────────────────────────────────────────────
        from app.modules.rag.moderator import moderate as _moderate
        mod_result = await _moderate(
            ai_result["response"],
            decision["grounded"],
            decision["citation_keys"],
            self.db,
        )

        assistant_content: str
        assistant_grounded: str
        moderation_field: dict | None = None

        if mod_result.action == "block":
            assistant_content = (
                "This response was blocked by the content moderation layer. "
                "Please rephrase or contact your instructor."
            )
            assistant_grounded = "blocked"
            moderation_field = {
                "violation_type": mod_result.primary.category if mod_result.primary else None,
                "severity": mod_result.primary.severity if mod_result.primary else None,
                "rule_id": str(mod_result.primary.rule_id) if mod_result.primary and mod_result.primary.rule_id else None,
            }
        elif mod_result.action == "redact":
            assistant_content = mod_result.redacted_text or ai_result["response"]
            assistant_grounded = decision["grounded"]
            moderation_field = {
                "redactions_applied": sum(1 for v in mod_result.all if v.action == "redact"),
                "categories": sorted({v.category for v in mod_result.all if v.action == "redact"}),
            }
        else:  # log or pass
            assistant_content = ai_result["response"]
            assistant_grounded = decision["grounded"]
            # No moderation field surfaced for log/pass

        assistant_msg = ChatMessage(
            session_id=session_id, role="assistant", content=assistant_content,
            citations=decision["citation_keys"] if mod_result.action != "block" else [],
            grounded=assistant_grounded,
        )
        self.db.add(assistant_msg)

        # Persist moderation_logs for every violation
        if mod_result.all:
            from app.modules.rag.models import ModerationLog
            trunc_resp = _settings.MODERATION_LOG_TRUNCATE_RESPONSE
            trunc_match = _settings.MODERATION_LOG_TRUNCATE_MATCH
            original_truncated = ai_result["response"][:trunc_resp]
            for v in mod_result.all:
                self.db.add(ModerationLog(
                    request_id=ai_result.get("request_id"),
                    session_id=session_id,
                    user_id=getattr(user, "id", None),
                    rule_id=v.rule_id,
                    category=v.category,
                    matched_text=(v.matched_text or "")[:trunc_match],
                    original_response=original_truncated,
                    action_taken=v.action if v.action != "pass" else "log",
                    severity=v.severity,
                ))
```

Then ALSO update the return statement at the end of `answer()` to include the moderation field on the assistant_message-shaped output. Find the final `return {...}` and add a `moderation_field` carry-through:

Replace the final return with:

```python
        sources = await self._resolve_sources(decision["citation_keys"], scores_by_key) if mod_result.action != "block" else []
        await self.db.commit()

        return {
            "user_message": user_msg, "assistant_message": assistant_msg,
            "decision": decision, "hits": hits, "rewritten_query": rewritten,
            "skipped_rewrite": skipped, "sources": sources, "suggestions": [],
            "moderation": moderation_field,  # NEW — None | block dict | redact dict
        }
```

- [ ] **Step 5: Update `app/modules/ai_assistant/router.py` to surface `moderation` in the response**

Find the response-building section that constructs `AssistantMessage`. Add the moderation field carry-through:

```python
            assistantMessage=AssistantMessage(
                id=str(asst_msg.id), role="assistant", content=asst_msg.content,
                timestamp=asst_msg.created_at,
                grounded=asst_msg.grounded,
                sources=sources, suggestions=suggestions,
                moderation=result.get("moderation"),  # NEW
            ),
```

- [ ] **Step 6: Verify app starts + unit tests still green**

Run: `.venv/Scripts/python.exe -c "from app.main import app; print('ok')"`
Expected: `ok`

Run: `.venv/Scripts/python.exe -m pytest tests/unit/ --no-cov -q`
Expected: all unit tests pass (count grows by the moderation tests; previous tests unaffected).

- [ ] **Step 7: Commit**

```bash
git add app/modules/rag/service.py app/modules/rag/schemas.py app/modules/ai_assistant/models.py app/modules/ai_assistant/router.py migrations/versions/<rev>_add_blocked_to_grounded_state.py
git commit -m "feat(rag): wire moderator into RAGService.answer + add 'blocked' grounded state"
```

---

# Phase D — Admin endpoints

## Task D1: CRUD endpoints for moderation_rules in `app/modules/rag/router.py`

**Files:**
- Modify: `app/modules/rag/router.py`

- [ ] **Step 1: Append the 5 CRUD endpoints to `app/modules/rag/router.py`**

Add at the bottom of the file (after the existing `rag_query` route):

```python
# ─── Moderation admin endpoints ──────────────────────────────────────────────


def _require_admin_or_instructor(current_user: CurrentUser) -> None:
    if not (set(current_user.roles) & {"admin", "instructor"}):
        raise HTTPException(status_code=403, detail="Admin or instructor required")


def _require_admin(current_user: CurrentUser) -> None:
    if "admin" not in current_user.roles:
        raise HTTPException(status_code=403, detail="Admin required")


@router.get(
    "/moderation/rules",
    response_model=dict,
    summary="List moderation rules (admin/instructor)",
    operation_id="moderation_rules_list",
)
async def list_moderation_rules(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    category: str | None = None,
    active: bool | None = None,
    limit: int = 100,
    offset: int = 0,
):
    _require_admin_or_instructor(current_user)
    from sqlalchemy import select
    from app.modules.rag.models import ModerationRule
    from app.modules.rag.schemas import ModerationRuleOut
    q = select(ModerationRule)
    if category is not None:
        q = q.where(ModerationRule.category == category)
    if active is not None:
        q = q.where(ModerationRule.active == active)
    q = q.order_by(ModerationRule.created_at.desc()).limit(limit).offset(offset)
    rows = (await db.execute(q)).scalars().all()
    return {"data": [ModerationRuleOut.model_validate(r).model_dump(mode="json") for r in rows]}


@router.post(
    "/moderation/rules",
    response_model=dict,
    status_code=201,
    summary="Create a moderation rule (admin/instructor)",
    operation_id="moderation_rules_create",
)
async def create_moderation_rule(
    body: dict,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    _require_admin_or_instructor(current_user)
    import re as _re
    from app.modules.rag.models import ModerationRule
    from app.modules.rag.moderator import invalidate_cache
    from app.modules.rag.schemas import ModerationRuleIn, ModerationRuleOut

    payload = ModerationRuleIn.model_validate(body)
    # Validate the regex compiles before persisting (prevents bad patterns sneaking in)
    if payload.pattern_type == "regex":
        try:
            _re.compile(payload.pattern)
        except _re.error as exc:
            raise HTTPException(status_code=400, detail=f"Invalid regex: {exc}")

    rule = ModerationRule(
        category=payload.category,
        pattern=payload.pattern,
        pattern_type=payload.pattern_type,
        action=payload.action,
        severity=payload.severity,
        description=payload.description,
        active=payload.active,
        created_by=uuid.UUID(str(current_user.id)),
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    await invalidate_cache()
    return {"data": ModerationRuleOut.model_validate(rule).model_dump(mode="json")}


@router.get(
    "/moderation/rules/{rule_id}",
    response_model=dict,
    summary="Get a single moderation rule (admin/instructor)",
    operation_id="moderation_rules_get",
)
async def get_moderation_rule(
    rule_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    _require_admin_or_instructor(current_user)
    from sqlalchemy import select
    from app.modules.rag.models import ModerationRule
    from app.modules.rag.schemas import ModerationRuleOut
    rule = (await db.execute(select(ModerationRule).where(ModerationRule.id == rule_id))).scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"data": ModerationRuleOut.model_validate(rule).model_dump(mode="json")}


@router.patch(
    "/moderation/rules/{rule_id}",
    response_model=dict,
    summary="Update a moderation rule (admin/instructor)",
    operation_id="moderation_rules_update",
)
async def update_moderation_rule(
    rule_id: uuid.UUID,
    body: dict,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    _require_admin_or_instructor(current_user)
    import re as _re
    from sqlalchemy import select
    from app.modules.rag.models import ModerationRule
    from app.modules.rag.moderator import invalidate_cache
    from app.modules.rag.schemas import ModerationRuleOut, ModerationRuleUpdate

    payload = ModerationRuleUpdate.model_validate(body)
    rule = (await db.execute(select(ModerationRule).where(ModerationRule.id == rule_id))).scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    update_data = payload.model_dump(exclude_unset=True)
    # Validate new regex if pattern is being updated
    new_pattern = update_data.get("pattern", rule.pattern)
    new_pattern_type = update_data.get("pattern_type", rule.pattern_type)
    if "pattern" in update_data or "pattern_type" in update_data:
        if new_pattern_type == "regex":
            try:
                _re.compile(new_pattern)
            except _re.error as exc:
                raise HTTPException(status_code=400, detail=f"Invalid regex: {exc}")

    for k, v in update_data.items():
        setattr(rule, k, v)
    await db.commit()
    await db.refresh(rule)
    await invalidate_cache()
    return {"data": ModerationRuleOut.model_validate(rule).model_dump(mode="json")}


@router.delete(
    "/moderation/rules/{rule_id}",
    response_model=dict,
    summary="Delete a moderation rule (soft by default; ?hard=true requires admin)",
    operation_id="moderation_rules_delete",
)
async def delete_moderation_rule(
    rule_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    hard: bool = False,
):
    _require_admin_or_instructor(current_user)
    from sqlalchemy import select
    from app.modules.rag.models import ModerationRule
    from app.modules.rag.moderator import invalidate_cache
    rule = (await db.execute(select(ModerationRule).where(ModerationRule.id == rule_id))).scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    if hard:
        _require_admin(current_user)  # hard delete: admin only
        await db.delete(rule)
    else:
        rule.active = False
    await db.commit()
    await invalidate_cache()
    return {"data": {"id": str(rule_id), "deleted": "hard" if hard else "soft"}}
```

Make sure the file imports include `uuid` at the top — add `import uuid` if not present.

- [ ] **Step 2: Verify app starts + new endpoints registered**

```bash
.venv/Scripts/python.exe -c "
from app.main import app
ops = {r['operation_id'] for r in app.openapi()['paths'].values() for r in r.values() if isinstance(r, dict) and 'operationId' in r}
expected = {'moderation_rules_list','moderation_rules_create','moderation_rules_get','moderation_rules_update','moderation_rules_delete'}
print('all registered:', expected.issubset(ops))
"
```

If this prints False, dump app.openapi() and find the gap.

- [ ] **Step 3: Commit**

```bash
git add app/modules/rag/router.py
git commit -m "feat(moderation): admin CRUD endpoints for moderation_rules"
```

---

## Task D2: Audit-log read endpoint

**Files:**
- Modify: `app/modules/rag/router.py`

- [ ] **Step 1: Append the audit endpoint**

```python
@router.get(
    "/moderation/logs",
    response_model=dict,
    summary="List moderation log entries (admin/instructor audit view)",
    operation_id="moderation_logs_list",
)
async def list_moderation_logs(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    category: str | None = None,
    severity: str | None = None,
    session_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    limit: int = 100,
    offset: int = 0,
):
    _require_admin_or_instructor(current_user)
    from sqlalchemy import select
    from app.modules.rag.models import ModerationLog
    from app.modules.rag.schemas import ModerationLogOut
    q = select(ModerationLog)
    if category is not None:
        q = q.where(ModerationLog.category == category)
    if severity is not None:
        q = q.where(ModerationLog.severity == severity)
    if session_id is not None:
        q = q.where(ModerationLog.session_id == session_id)
    if user_id is not None:
        q = q.where(ModerationLog.user_id == user_id)
    q = q.order_by(ModerationLog.created_at.desc()).limit(limit).offset(offset)
    rows = (await db.execute(q)).scalars().all()
    return {"data": [ModerationLogOut.model_validate(r).model_dump(mode="json") for r in rows]}
```

- [ ] **Step 2: Smoke check**

```bash
.venv/Scripts/python.exe -c "
from app.main import app
ops = {r['operation_id'] for r in app.openapi()['paths'].values() for r in r.values() if isinstance(r, dict) and 'operationId' in r}
print('moderation_logs_list registered:', 'moderation_logs_list' in ops)
"
```

- [ ] **Step 3: Commit**

```bash
git add app/modules/rag/router.py
git commit -m "feat(moderation): GET /moderation/logs audit endpoint"
```

---

# Phase E — Integration tests + final polish

## Task E1: End-to-end integration test for blocked response

**Files:**
- Create: `tests/integration/test_moderation_endpoints.py`

- [ ] **Step 1: Write the integration test**

Create `tests/integration/test_moderation_endpoints.py`:

```python
import asyncio
import re
import uuid
from unittest.mock import AsyncMock, patch

from sqlalchemy import select

from app.modules.auth.models import User
from app.modules.rag.models import ModerationRule
from app.modules.rag.tasks import embed_source
from tests.fixtures.synthetic_fcom import seed_synthetic_fcom


async def _fake_embed(texts, *args, **kwargs):
    return {"embeddings": [[0.1] * 1536 for _ in texts], "model": "x", "usage": {"total_tokens": 1}}


async def _ingest(db_session):
    source = await seed_synthetic_fcom(db_session)
    await db_session.commit()
    with patch("app.modules.ai.service.AIService") as mock_ai:
        mock_ai.return_value.embed = AsyncMock(side_effect=_fake_embed)
        await asyncio.to_thread(embed_source, str(source.id))
    return source


async def _make_test_user(db_session, role="trainee"):
    user = User(
        id=uuid.uuid4(),
        email=f"test-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="x",
        full_name="Test User",
    )
    db_session.add(user)
    await db_session.commit()
    return user


async def test_moderation_blocks_classification_marker_in_response(client, db_session):
    """End-to-end: AI emits a classification marker; moderator blocks; response shape reflects it."""
    await _ingest(db_session)
    real_user = await _make_test_user(db_session)

    # AI completion that emits a classification marker
    async def fake_complete(req, user_id):
        return {
            "response": "Per [SYN-FCOM-3.1], details marked SECRET//NOFORN about engine.",
            "provider": "gemini", "model": "gemini-1.5-pro", "cached": False,
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "cost_usd": 0},
            "citations": req.context_citations, "request_id": "req_x",
        }

    from app.main import app
    from app.modules.auth.deps import get_current_user
    from app.modules.auth.schemas import CurrentUser
    fake_user = CurrentUser(id=str(real_user.id), roles=["trainee"], jti="")
    app.dependency_overrides[get_current_user] = lambda: fake_user

    try:
        with (
            patch("app.modules.ai.service.AIService") as mock_ai_cls,
            patch("app.modules.rag.service.AIService", new=mock_ai_cls),
            patch("app.modules.rag.rewriter.AIService", new=mock_ai_cls),
        ):
            inst = mock_ai_cls.return_value
            inst.embed = AsyncMock(side_effect=_fake_embed)
            inst.complete = AsyncMock(side_effect=fake_complete)
            resp = await client.post(
                "/api/v1/ai-assistant/message", json={"content": "engine details?"}
            )
            assert resp.status_code == 200, resp.text
            body = resp.json()["data"]
            assistant = body["assistantMessage"]
            assert assistant["grounded"] == "blocked"
            assert "blocked by the content moderation layer" in assistant["content"]
            assert assistant["moderation"]["violation_type"] == "classification"
            assert assistant["moderation"]["severity"] == "critical"
    finally:
        app.dependency_overrides.pop(get_current_user, None)


async def test_moderation_admin_create_rule_invalidates_cache_and_blocks_next_message(client, db_session):
    """Admin POSTs a banned-phrase rule; the next AI response containing that phrase gets blocked."""
    await _ingest(db_session)
    real_user = await _make_test_user(db_session)

    from app.main import app
    from app.modules.auth.deps import get_current_user
    from app.modules.auth.schemas import CurrentUser
    instructor_user = CurrentUser(id=str(real_user.id), roles=["instructor"], jti="")
    app.dependency_overrides[get_current_user] = lambda: instructor_user

    try:
        # Add a rule that bans the literal phrase 'WIDGET-X42'
        rule_body = {
            "category": "banned_phrase",
            "pattern": "WIDGET-X42",
            "pattern_type": "literal",
            "action": "block",
            "severity": "high",
            "description": "Test banned phrase",
            "active": True,
        }
        resp = await client.post("/api/v1/rag/moderation/rules", json=rule_body)
        assert resp.status_code == 201, resp.text

        # Now have the AI emit a response containing that phrase
        async def fake_complete(req, user_id):
            return {
                "response": "Per [SYN-FCOM-3.1], the WIDGET-X42 specification details ...",
                "provider": "gemini", "model": "gemini-1.5-pro", "cached": False,
                "usage": {}, "citations": req.context_citations, "request_id": "req_y",
            }

        with (
            patch("app.modules.ai.service.AIService") as mock_ai_cls,
            patch("app.modules.rag.service.AIService", new=mock_ai_cls),
            patch("app.modules.rag.rewriter.AIService", new=mock_ai_cls),
        ):
            inst = mock_ai_cls.return_value
            inst.embed = AsyncMock(side_effect=_fake_embed)
            inst.complete = AsyncMock(side_effect=fake_complete)
            resp = await client.post(
                "/api/v1/ai-assistant/message", json={"content": "describe widget"}
            )
            assert resp.status_code == 200, resp.text
            body = resp.json()["data"]
            assistant = body["assistantMessage"]
            assert assistant["grounded"] == "blocked"
            assert assistant["moderation"]["violation_type"] == "banned_phrase"
    finally:
        app.dependency_overrides.pop(get_current_user, None)


async def test_moderation_admin_endpoints_require_role(client, db_session):
    """Trainee gets 403 on POST /moderation/rules."""
    real_user = await _make_test_user(db_session)
    from app.main import app
    from app.modules.auth.deps import get_current_user
    from app.modules.auth.schemas import CurrentUser
    trainee = CurrentUser(id=str(real_user.id), roles=["trainee"], jti="")
    app.dependency_overrides[get_current_user] = lambda: trainee
    try:
        resp = await client.post(
            "/api/v1/rag/moderation/rules",
            json={"category": "casual", "pattern": "yolo", "action": "log", "severity": "low"},
        )
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)
```

- [ ] **Step 2: Run all tests (locally will fail on DB unavail; CI will run them)**

Run: `.venv/Scripts/python.exe -m pytest tests/integration/test_moderation_endpoints.py --collect-only --no-cov 2>&1 | tail -10`
Expected: 3 tests collected, no errors.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_moderation_endpoints.py
git commit -m "test(moderation): integration tests for blocked classification + admin CRUD + role gate"
```

---

## Task E2: Final ruff + unit suite + push

**Files:** none (verification + push)

- [ ] **Step 1: Run ruff with auto-fix**

Run: `.venv/Scripts/python.exe -m ruff check . --fix 2>&1 | tail -3`
Expected: ideally `All checks passed!` after fix; if remaining errors, manually address as in PR #1's lint cleanup phase.

- [ ] **Step 2: Run unit tests**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/ --no-cov -q 2>&1 | tail -3`
Expected: all unit tests pass (now ~60 total: 27 pre-existing + ~33 moderation).

- [ ] **Step 3: Verify app starts**

Run: `.venv/Scripts/python.exe -c "from app.main import app; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Push branch + verify CI**

```bash
git push -u origin feat/content-moderation-shreyansh
```

Then watch CI:
```bash
sleep 90 && gh run list --branch feat/content-moderation-shreyansh --limit 1
```

If CI fails, follow the same triage pattern from PR #1: `gh run view <id> --log-failed`, dispatch Sonnet with the failure summary + fix.

- [ ] **Step 5: Open the draft PR**

```bash
gh pr create --draft --title "Content Moderation Layer--shreyansh" --body "$(cat <<'EOF'
## Summary

Output-side content moderation for AI responses with database-backed rules,
Redis-cached lookups, tiered actions (BLOCK / REDACT / LOG), and admin CRUD endpoints.

Implements Excel R53 (P1) per the design at
docs/superpowers/specs/2026-04-29-content-moderation-design.md.

### What's included
- 2 new tables: `moderation_rules` (DB-backed, admin-managed) + `moderation_logs`
  (audit trail joinable to `ai_requests`)
- `moderate()` orchestrator + 5 detectors (4 rule-based + 1 ungrounded heuristic)
- Tiered actions: BLOCK > REDACT > LOG with severity-based precedence
- Admin CRUD: GET/POST/GET-by-id/PATCH/DELETE on `/rag/moderation/rules` +
  GET `/rag/moderation/logs` (instructor or admin role; hard delete = admin only)
- Redis cache with explicit invalidation on writes; falls back to DB on cache miss
- New `blocked` value added to `grounded_state` enum (for `chat_messages.grounded`)
- New `moderation` field on `AssistantMessage` response (only present for block/redact)
- Configurable kill switch (`MODERATION_ENABLED`), fail-open on infra error
  (`MODERATION_FAIL_OPEN`), and log-truncation limits

### Default seed rules (from migration)
- 6 classification markers (BLOCK, critical) — SECRET//, TOP SECRET, TS//SCI,
  NOFORN, REL TO, CONFIDENTIAL//
- 7 profanity patterns (REDACT, medium)
- 3 casual register patterns (LOG, low)
- 0 banned phrases — admin populates via API

### Coordination
- This branch is stacked on `feat/rag-foundation` (PR #1) — RAG models are a
  hard dependency. Will rebase onto `main` once PR #1 merges.
- @sachinglimmora — touches `app/modules/ai_assistant/models.py` (extends the
  `grounded_state` enum). Migration is additive (`ALTER TYPE … ADD VALUE`).
  Lmk if you want a different naming.
- @ira — moderation rule store is independent of your PII filter (input vs
  output direction); no overlap.

## Test plan
- [x] 33 unit tests for detectors + cache + orchestration
- [x] 3 integration tests: end-to-end block, admin create-then-block, role gate
- [x] Ruff clean
- [x] App starts; new endpoints registered in OpenAPI
- [ ] CI green on PR (verify after push)
- [ ] Coordinate with Sachin before un-drafting

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 6: Final commit if any cleanup**

If CI surfaces issues, follow the dispatch-Sonnet pattern from PR #1.

---

## Self-review notes

- **Spec coverage:** all 17 spec sections map to a task above (data model → A1+A2; cache → B7; detectors → B2-B5; orchestration → B8; integration → C1; admin → D1-D2; tests → B*+E1; failure modes → covered in B7-B8 tests + C1 wiring).
- **Type consistency:** `Violation`, `CompiledRule`, `ModerationResult` defined once in B1 and used identically in B2-B8 + C1.
- **No placeholders.** All code blocks contain working code.

---

## Coordination after this branch lands

- Sachin: extending the `grounded_state` enum (additive migration only) — flag in PR body
- Future: rule sync to a write-through Postgres LISTEN channel for sub-second cache invalidation across instances (currently 60s TTL is fine for single-instance Render dev)
