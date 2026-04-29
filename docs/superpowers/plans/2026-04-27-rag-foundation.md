# RAG Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the backend RAG layer (`app/modules/rag/`) that turns approved aerospace content into citation-grounded answers for the Trainee + Instructor AI Assistants.

**Architecture:** Slot into Sachin's citation-key-driven AI gateway. RAG produces ranked `citation_key`s; gateway resolves them to section text, runs PII filter, calls LLMs with cache + fallback. No LangChain — use Sachin's `LLMProvider` Protocol directly via `AIService.embed/complete`. pgvector for storage; Celery for async ingestion; structural-primary chunking; dual-threshold grounding with soft-include rescue; conversational query rewriting.

**Tech Stack:** FastAPI · SQLAlchemy 2.0 async · Postgres 16 + pgvector · Alembic · Celery · Redis · pytest-asyncio · tiktoken · OpenAI/Gemini (via gateway).

**Spec:** [`docs/superpowers/specs/2026-04-27-rag-foundation-design.md`](../specs/2026-04-27-rag-foundation-design.md)

---

## Reference

### Naming conventions used throughout

**Module functions/classes:**
- `app.modules.rag.chunker`: `chunk_section_tree(source) -> list[ChunkRecord]`, `count_tokens(text) -> int`
- `app.modules.rag.embedder`: `embed_and_validate(texts) -> list[list[float]]`, `EmbedDimensionMismatch`
- `app.modules.rag.retriever`: `retrieve(db, query, aircraft_id, cfg) -> list[Hit]`
- `app.modules.rag.grounder`: `decide(hits, cfg) -> Decision` (subclasses `Strong`, `Soft`, `Refused`)
- `app.modules.rag.rewriter`: `rewrite(msg, history, turn) -> str`
- `app.modules.rag.service`: `RAGService.answer(db, query, session_id, user) -> AnswerResult`
- `app.modules.rag.tasks`: Celery `embed_source`, `reembed_source`, `reembed_all_dim_mismatch`, `auto_close_idle_sessions`

**SQLAlchemy models** (all inherit `app.database.Base`):
- `ContentChunk` (`app.modules.rag.models`)
- `RetrievalLog` (`app.modules.rag.models`)
- `ChatSession`, `ChatMessage` (`app.modules.ai_assistant.models`)

**Endpoints (added):**
- `POST /api/v1/rag/query` (debug/standalone)
- `POST /api/v1/content/sources/{id}/reembed` (admin)
- `POST /api/v1/ai-assistant/sessions` (create session with optional aircraft_id)
- `POST /api/v1/ai-assistant/message` (refactored — RAG-backed)
- `GET /api/v1/ai-assistant/history` (refactored — reads from DB)
- `DELETE /api/v1/ai-assistant/history` (refactored — closes session)

**Celery task names** (full registered name):
- `rag.embed_source`
- `rag.reembed_source`
- `rag.reembed_all_dim_mismatch`
- `rag.auto_close_idle_sessions`

### File structure

```
Created:
  app/modules/rag/__init__.py
  app/modules/rag/models.py
  app/modules/rag/schemas.py
  app/modules/rag/router.py
  app/modules/rag/service.py
  app/modules/rag/chunker.py
  app/modules/rag/embedder.py
  app/modules/rag/retriever.py
  app/modules/rag/grounder.py
  app/modules/rag/rewriter.py
  app/modules/rag/tasks.py
  app/modules/rag/prompts.py
  app/modules/rag/README.md
  app/modules/ai_assistant/__init__.py        (if missing)
  app/modules/ai_assistant/models.py
  migrations/versions/<rev>_enable_pgvector.py
  migrations/versions/<rev>_create_content_chunks.py
  migrations/versions/<rev>_create_chat_tables.py
  migrations/versions/<rev>_create_retrieval_logs.py
  migrations/versions/<rev>_add_embedding_status.py
  tests/unit/test_rag_chunker.py
  tests/unit/test_rag_grounder.py
  tests/unit/test_rag_rewriter.py
  tests/unit/test_rag_mmr.py
  tests/unit/test_rag_embedder.py
  tests/integration/test_rag_ingestion.py
  tests/integration/test_rag_retrieval.py
  tests/integration/test_ai_assistant_message.py
  tests/fixtures/synthetic_fcom.py

Modified:
  pyproject.toml                              (add deps)
  app/config.py                               (RAG settings block)
  app/main.py                                 (startup hook + new router)
  app/worker.py                               (register rag.* tasks + beat schedule)
  app/modules/content/service.py              (hook approve_source -> embed_source.delay)
  app/modules/content/router.py               (add reembed endpoint)
  app/modules/ai_assistant/router.py          (full refactor)
  app/modules/ai/service.py                   (fix N+1 in _resolve_citations)
```

### Configuration constants (added to `app/config.py`)

```python
# RAG core
EMBEDDING_DIM: int = 1536
EMBEDDING_MODEL_HINT: str = "text-embedding-3-small"
RAG_CHUNK_TOKENS_MAX: int = 800
RAG_CHUNK_OVERLAP_TOKENS: int = 100
RAG_CHUNK_TOKENS_MIN_MERGE: int = 100
RAG_TOP_K: int = 10
RAG_MAX_CHUNKS: int = 5
RAG_INCLUDE_THRESHOLD: float = 0.65
RAG_SOFT_INCLUDE_THRESHOLD: float = 0.60
RAG_SUGGEST_THRESHOLD: float = 0.50
RAG_MMR_LAMBDA: float = 0.5
RAG_USE_RERANKER: bool = False

# Query rewriter
RAG_REWRITER_MODEL: str = "gemini-1.5-flash"
RAG_REWRITER_TIMEOUT_S: int = 5
RAG_REWRITER_MAX_TOKENS: int = 100
RAG_REWRITER_HISTORY_WINDOW: int = 6
RAG_REWRITER_CACHE_TTL_S: int = 3600

# Chat session
CHAT_SESSION_AUTO_CLOSE_DAYS: int = 30
```

---

# Phase A — Plumbing

Goal: schemas + module skeleton in place. App still starts. No new behavior yet.

## Task A1: Add new dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Edit `pyproject.toml` — add three deps to the `[project] dependencies` list**

Add these three lines anywhere in the `dependencies = [...]` list:

```toml
    "pgvector>=0.3.0",
    "tiktoken>=0.7.0",
    "langchain-text-splitters>=0.2.0",
```

- [ ] **Step 2: Reinstall in editable mode**

Run: `pip install -e ".[dev]"`
Expected: clean install, no errors. New packages resolved: `pgvector`, `tiktoken`, `langchain-text-splitters`.

- [ ] **Step 3: Verify imports**

Run: `python -c "import pgvector, tiktoken, langchain_text_splitters; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "chore(rag): add pgvector, tiktoken, langchain-text-splitters deps"
```

---

## Task A2: Migration — enable pgvector extension

**Files:**
- Create: `migrations/versions/<auto>_enable_pgvector.py`

- [ ] **Step 1: Generate empty migration**

Run: `alembic revision -m "enable_pgvector_extension"`
Expected: prints path like `Generating migrations/versions/<rev>_enable_pgvector_extension.py`. Note the revision id.

- [ ] **Step 2: Edit the new migration — replace the `upgrade()` and `downgrade()` bodies**

```python
def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS vector")
```

- [ ] **Step 3: Run migration**

Run: `alembic upgrade head`
Expected: `INFO  [alembic.runtime.migration] Running upgrade ... -> <rev>, enable_pgvector_extension`

- [ ] **Step 4: Verify extension exists**

Run: `psql "$DATABASE_URL" -c "SELECT extname FROM pg_extension WHERE extname='vector';"`
Expected: one row with `vector`.

- [ ] **Step 5: Commit**

```bash
git add migrations/versions/<rev>_enable_pgvector_extension.py
git commit -m "feat(rag): alembic migration to enable pgvector extension"
```

---

## Task A3: Define ChatSession + ChatMessage models

**Files:**
- Create: `app/modules/ai_assistant/__init__.py` (if missing — check first)
- Create: `app/modules/ai_assistant/models.py`

- [ ] **Step 1: Ensure `app/modules/ai_assistant/__init__.py` exists**

Run: `test -f app/modules/ai_assistant/__init__.py || touch app/modules/ai_assistant/__init__.py`

- [ ] **Step 2: Create `app/modules/ai_assistant/models.py`**

```python
import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

_now = lambda: datetime.now(UTC)


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    aircraft_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("aircraft.id"), nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        Enum("active", "closed", name="chat_session_status"), default="active", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False, index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    messages: Mapped[list["ChatMessage"]] = relationship(
        "ChatMessage", back_populates="session", cascade="all, delete-orphan", order_by="ChatMessage.created_at"
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("chat_sessions.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(Enum("user", "assistant", name="chat_message_role"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    grounded: Mapped[str | None] = mapped_column(
        Enum("strong", "soft", "refused", name="grounded_state"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    session: Mapped["ChatSession"] = relationship("ChatSession", back_populates="messages")
```

- [ ] **Step 3: Import models in `app/main.py` so Alembic auto-gen sees them**

Edit `app/main.py` — add this import alongside existing module imports (around line 32):

```python
from app.modules.ai_assistant.models import ChatSession, ChatMessage  # noqa: F401  (registers tables)
```

- [ ] **Step 4: Verify import doesn't break app**

Run: `python -c "from app.main import app; print('ok')"`
Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add app/modules/ai_assistant/models.py app/modules/ai_assistant/__init__.py app/main.py
git commit -m "feat(ai_assistant): define ChatSession and ChatMessage models"
```

---

## Task A4: Migration — content_chunks table with pgvector + ivfflat index

**Files:**
- Create: `migrations/versions/<auto>_create_content_chunks.py`

This table can't be auto-generated (Alembic doesn't know about `Vector` until we declare the SQLAlchemy column in Task B5). So write it manually.

- [ ] **Step 1: Generate empty migration**

Run: `alembic revision -m "create_content_chunks"`
Expected: prints path. Note the revision id.

- [ ] **Step 2: Edit `upgrade()` and `downgrade()`**

```python
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "<auto>"
down_revision: Union[str, None] = "<previous-rev>"  # leave Alembic's value
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE content_chunks (
            id UUID PRIMARY KEY,
            source_id UUID NOT NULL REFERENCES content_sources(id),
            section_id UUID NOT NULL REFERENCES content_sections(id),
            citation_keys JSONB NOT NULL,
            content TEXT NOT NULL,
            token_count INTEGER NOT NULL,
            ordinal INTEGER NOT NULL DEFAULT 0,
            embedding vector(1536) NOT NULL,
            embedding_model VARCHAR(64) NOT NULL,
            embedding_dim INTEGER NOT NULL,
            superseded_by_source_id UUID NULL REFERENCES content_sources(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.create_index("ix_content_chunks_source_id", "content_chunks", ["source_id"])
    op.create_index("ix_content_chunks_section_id", "content_chunks", ["section_id"])
    op.create_index("ix_content_chunks_superseded_by", "content_chunks", ["superseded_by_source_id"])
    op.create_index("ix_content_chunks_source_ordinal", "content_chunks", ["source_id", "ordinal"])
    op.execute(
        "CREATE INDEX ix_content_chunks_embedding ON content_chunks "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_content_chunks_embedding")
    op.drop_index("ix_content_chunks_source_ordinal", table_name="content_chunks")
    op.drop_index("ix_content_chunks_superseded_by", table_name="content_chunks")
    op.drop_index("ix_content_chunks_section_id", table_name="content_chunks")
    op.drop_index("ix_content_chunks_source_id", table_name="content_chunks")
    op.execute("DROP TABLE content_chunks")
```

- [ ] **Step 3: Run migration**

Run: `alembic upgrade head`
Expected: `Running upgrade ... -> <rev>, create_content_chunks`

- [ ] **Step 4: Verify table + index exist**

Run: `psql "$DATABASE_URL" -c "\d content_chunks"`
Expected: 12 columns including `embedding vector(1536)`, indexes including `ix_content_chunks_embedding USING ivfflat`.

- [ ] **Step 5: Commit**

```bash
git add migrations/versions/<rev>_create_content_chunks.py
git commit -m "feat(rag): alembic migration for content_chunks (pgvector + ivfflat)"
```

---

## Task A5: Migration — chat_sessions + chat_messages (auto-gen)

**Files:**
- Create: `migrations/versions/<auto>_create_chat_tables.py`

- [ ] **Step 1: Auto-generate from models**

Run: `alembic revision --autogenerate -m "create_chat_tables"`
Expected: file generated with `op.create_table('chat_sessions', ...)` and `op.create_table('chat_messages', ...)`. Verify the generated migration includes both tables and indexes.

- [ ] **Step 2: Sanity-check the generated file**

Open `migrations/versions/<rev>_create_chat_tables.py`. Confirm:
- `chat_sessions` table created with columns matching `app/modules/ai_assistant/models.py`
- `chat_messages` table created with FK to `chat_sessions`
- Index on `chat_sessions.last_activity_at`
- Index on `chat_messages.session_id`
- Enum types `chat_session_status`, `chat_message_role`, `grounded_state` created

If anything's missing (autogen sometimes misses indexes), add `op.create_index(...)` calls manually.

- [ ] **Step 3: Run migration**

Run: `alembic upgrade head`
Expected: `Running upgrade ... -> <rev>, create_chat_tables`

- [ ] **Step 4: Verify tables**

Run: `psql "$DATABASE_URL" -c "\dt chat_*"`
Expected: `chat_sessions`, `chat_messages` listed.

- [ ] **Step 5: Commit**

```bash
git add migrations/versions/<rev>_create_chat_tables.py
git commit -m "feat(ai_assistant): alembic migration for chat_sessions and chat_messages"
```

---

## Task A6: Migration — retrieval_logs table

**Files:**
- Create: `migrations/versions/<auto>_create_retrieval_logs.py`

This table will be auto-generated once the model lands in Task D6, but we create the migration manually now to keep migrations grouped in Phase A.

- [ ] **Step 1: Generate empty migration**

Run: `alembic revision -m "create_retrieval_logs"`

- [ ] **Step 2: Edit `upgrade()` and `downgrade()`**

```python
def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE retrieval_logs (
            id UUID PRIMARY KEY,
            request_id VARCHAR(36) NULL,
            session_id UUID NULL REFERENCES chat_sessions(id),
            user_id UUID NULL,
            original_query TEXT NOT NULL,
            rewritten_query TEXT NULL,
            query_skipped_rewrite BOOLEAN NOT NULL DEFAULT FALSE,
            aircraft_scope_id UUID NULL,
            top_k INTEGER NOT NULL,
            hits JSONB NOT NULL,
            grounded VARCHAR(16) NOT NULL,
            latency_ms JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.create_index("ix_retrieval_logs_request_id", "retrieval_logs", ["request_id"])
    op.create_index("ix_retrieval_logs_session_id", "retrieval_logs", ["session_id"])
    op.create_index("ix_retrieval_logs_created_at", "retrieval_logs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_retrieval_logs_created_at", table_name="retrieval_logs")
    op.drop_index("ix_retrieval_logs_session_id", table_name="retrieval_logs")
    op.drop_index("ix_retrieval_logs_request_id", table_name="retrieval_logs")
    op.execute("DROP TABLE retrieval_logs")
```

- [ ] **Step 3: Run + verify**

Run: `alembic upgrade head && psql "$DATABASE_URL" -c "\d retrieval_logs"`
Expected: table created, three indexes present.

- [ ] **Step 4: Commit**

```bash
git add migrations/versions/<rev>_create_retrieval_logs.py
git commit -m "feat(rag): alembic migration for retrieval_logs telemetry table"
```

---

## Task A7: Migration — add embedding_status to content_sources

**Files:**
- Create: `migrations/versions/<auto>_add_embedding_status.py`

- [ ] **Step 1: Generate empty migration**

Run: `alembic revision -m "add_embedding_status_to_content_sources"`

- [ ] **Step 2: Edit `upgrade()` and `downgrade()`**

```python
def upgrade() -> None:
    op.execute("CREATE TYPE embedding_status AS ENUM ('pending', 'succeeded', 'failed')")
    op.add_column(
        "content_sources",
        sa.Column(
            "embedding_status",
            postgresql.ENUM("pending", "succeeded", "failed", name="embedding_status", create_type=False),
            nullable=False,
            server_default="pending",
        ),
    )


def downgrade() -> None:
    op.drop_column("content_sources", "embedding_status")
    op.execute("DROP TYPE embedding_status")
```

- [ ] **Step 3: Run + verify**

Run: `alembic upgrade head && psql "$DATABASE_URL" -c "\d content_sources" | grep embedding_status`
Expected: one line showing `embedding_status` column with `embedding_status` type, default `pending`.

- [ ] **Step 4: Mirror the column in `ContentSource` model**

Edit `app/modules/content/models.py` — add to `ContentSource` class after `status`:

```python
    embedding_status: Mapped[str] = mapped_column(
        Enum("pending", "succeeded", "failed", name="embedding_status"),
        default="pending",
        nullable=False,
    )
```

- [ ] **Step 5: Commit**

```bash
git add migrations/versions/<rev>_add_embedding_status.py app/modules/content/models.py
git commit -m "feat(content): add embedding_status column to content_sources"
```

---

## Task A8: Add RAG settings to `app/config.py`

**Files:**
- Modify: `app/config.py`

- [ ] **Step 1: Open `app/config.py` and find the `Settings` class**

- [ ] **Step 2: Add the full RAG settings block (immediately after the existing AI/cache settings, before `class Config:`)**

```python
    # ─── RAG ────────────────────────────────────────────────────────────────
    # Embedding
    EMBEDDING_DIM: int = 1536
    EMBEDDING_MODEL_HINT: str = "text-embedding-3-small"

    # Chunking
    RAG_CHUNK_TOKENS_MAX: int = 800
    RAG_CHUNK_OVERLAP_TOKENS: int = 100
    RAG_CHUNK_TOKENS_MIN_MERGE: int = 100

    # Retrieval / grounding
    RAG_TOP_K: int = 10
    RAG_MAX_CHUNKS: int = 5
    RAG_INCLUDE_THRESHOLD: float = 0.65
    RAG_SOFT_INCLUDE_THRESHOLD: float = 0.60
    RAG_SUGGEST_THRESHOLD: float = 0.50
    RAG_MMR_LAMBDA: float = 0.5
    RAG_USE_RERANKER: bool = False

    # Query rewriter
    RAG_REWRITER_MODEL: str = "gemini-1.5-flash"
    RAG_REWRITER_TIMEOUT_S: int = 5
    RAG_REWRITER_MAX_TOKENS: int = 100
    RAG_REWRITER_HISTORY_WINDOW: int = 6
    RAG_REWRITER_CACHE_TTL_S: int = 3600

    # Chat session
    CHAT_SESSION_AUTO_CLOSE_DAYS: int = 30
```

- [ ] **Step 3: Verify config loads**

Run: `python -c "from app.config import get_settings; s=get_settings(); print(s.EMBEDDING_DIM, s.RAG_INCLUDE_THRESHOLD)"`
Expected: `1536 0.65`

- [ ] **Step 4: Commit**

```bash
git add app/config.py
git commit -m "feat(config): add RAG configuration settings"
```

---

## Task A9: Scaffold `app/modules/rag/`

**Files:**
- Create: `app/modules/rag/__init__.py`
- Create: `app/modules/rag/models.py`
- Create: `app/modules/rag/schemas.py`
- Create: `app/modules/rag/chunker.py`
- Create: `app/modules/rag/embedder.py`
- Create: `app/modules/rag/retriever.py`
- Create: `app/modules/rag/grounder.py`
- Create: `app/modules/rag/rewriter.py`
- Create: `app/modules/rag/service.py`
- Create: `app/modules/rag/router.py`
- Create: `app/modules/rag/tasks.py`
- Create: `app/modules/rag/prompts.py`

- [ ] **Step 1: Create `app/modules/rag/__init__.py`** (empty file)

```python
```

- [ ] **Step 2: Create `app/modules/rag/models.py` (full SQLAlchemy models)**

```python
import uuid
from datetime import UTC, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

_now = lambda: datetime.now(UTC)


class ContentChunk(Base):
    __tablename__ = "content_chunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("content_sources.id"), nullable=False, index=True)
    section_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("content_sections.id"), nullable=False, index=True)
    citation_keys: Mapped[list] = mapped_column(JSONB, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(1536), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding_dim: Mapped[int] = mapped_column(Integer, nullable=False)
    superseded_by_source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content_sources.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class RetrievalLog(Base):
    __tablename__ = "retrieval_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("chat_sessions.id"), nullable=True, index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    original_query: Mapped[str] = mapped_column(Text, nullable=False)
    rewritten_query: Mapped[str | None] = mapped_column(Text, nullable=True)
    query_skipped_rewrite: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    aircraft_scope_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    top_k: Mapped[int] = mapped_column(Integer, nullable=False)
    hits: Mapped[list] = mapped_column(JSONB, nullable=False)
    grounded: Mapped[str] = mapped_column(String(16), nullable=False)
    latency_ms: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False, index=True)
```

- [ ] **Step 3: Create `app/modules/rag/schemas.py` (full Pydantic schemas)**

```python
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class RagQueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    aircraft_id: UUID | None = None
    top_k: int | None = None  # override config default if needed


class HitOut(BaseModel):
    citation_key: str
    score: float
    included: bool
    mmr_rank: int


class RagQueryResponse(BaseModel):
    grounded: str  # strong | soft | refused
    citation_keys: list[str]
    hits: list[HitOut]
    suggestions: list[HitOut]


class SourceOut(BaseModel):
    citation_key: str
    display_label: str
    page_number: int | None
    score: float
    source_type: str
    source_version: str
    snippet: str


class AssistantMessage(BaseModel):
    id: str
    role: str
    content: str
    timestamp: datetime
    grounded: str | None = None
    sources: list[SourceOut] = []
    suggestions: list[SourceOut] = []


class UserMessage(BaseModel):
    id: str
    role: str
    content: str
    timestamp: datetime


class ChatTurnResponse(BaseModel):
    userMessage: UserMessage
    assistantMessage: AssistantMessage


class CreateSessionRequest(BaseModel):
    aircraft_id: UUID | None = None
    title: str | None = None


class SessionOut(BaseModel):
    id: UUID
    aircraft_id: UUID | None
    title: str | None
    status: str
    created_at: datetime
    last_activity_at: datetime
```

- [ ] **Step 4: Create stub files for the remaining modules**

Each stub raises `NotImplementedError` so any accidental call surfaces immediately. Replace `<filename>` with each name.

`app/modules/rag/chunker.py`:
```python
"""Section tree -> ContentChunk records (3-rule hybrid). See spec §7."""


def count_tokens(text: str) -> int:
    raise NotImplementedError


def chunk_section_tree(source) -> list:
    raise NotImplementedError
```

`app/modules/rag/embedder.py`:
```python
"""Wraps AIService.embed() + dim validation. See spec §8."""


class EmbedDimensionMismatch(Exception):
    pass


async def embed_and_validate(texts: list[str]) -> list[list[float]]:
    raise NotImplementedError
```

`app/modules/rag/retriever.py`:
```python
"""Vector search + MMR + threshold filter. See spec §9."""


async def retrieve(db, query: str, aircraft_id, cfg) -> list:
    raise NotImplementedError
```

`app/modules/rag/grounder.py`:
```python
"""Grounding decision: strong | soft | refused. See spec §10."""


async def decide(hits: list, cfg) -> dict:
    raise NotImplementedError
```

`app/modules/rag/rewriter.py`:
```python
"""Conversational query rewriting. See spec §11."""


async def rewrite(msg: str, history: list, turn: int) -> str:
    raise NotImplementedError
```

`app/modules/rag/service.py`:
```python
"""RAG orchestration: rewrite -> retrieve -> ground -> AIService.complete -> persist."""


class RAGService:
    def __init__(self, db):
        self.db = db

    async def answer(self, query: str, session_id, user) -> dict:
        raise NotImplementedError
```

`app/modules/rag/router.py`:
```python
from fastapi.routing import APIRouter

router = APIRouter()
```

`app/modules/rag/tasks.py`:
```python
"""Celery tasks: embed_source, reembed_source, reembed_all_dim_mismatch, auto_close_idle_sessions."""

from app.worker import celery_app


@celery_app.task(name="rag.embed_source")
def embed_source(source_id: str):
    raise NotImplementedError


@celery_app.task(name="rag.reembed_source")
def reembed_source(source_id: str):
    raise NotImplementedError


@celery_app.task(name="rag.reembed_all_dim_mismatch")
def reembed_all_dim_mismatch():
    raise NotImplementedError


@celery_app.task(name="rag.auto_close_idle_sessions")
def auto_close_idle_sessions():
    raise NotImplementedError
```

`app/modules/rag/prompts.py`:
```python
"""System prompt + refusal templates. See spec §13."""

TRAINEE_SYSTEM_PROMPT = ""  # filled in Task C4
INSTRUCTOR_SYSTEM_PROMPT = ""  # filled in Task C4
SOFT_GROUNDED_PREFIX = ""  # filled in Task C4
REFUSAL_TEMPLATE = ""  # filled in Task C4
REWRITER_PROMPT = ""  # filled in Task D1
```

- [ ] **Step 5: Wire models into `app/main.py` so Alembic + ORM see them**

Edit `app/main.py` — add alongside the existing module imports (around line 32):

```python
from app.modules.rag.models import ContentChunk, RetrievalLog  # noqa: F401
```

- [ ] **Step 6: Register `rag.tasks` with the Celery worker**

Edit `app/worker.py` — modify the existing `celery_app.conf.update(...)` call by adding an `imports` key:

```python
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    imports=("app.modules.rag.tasks",),  # ensures rag.* tasks register on worker start
)
```

Without this line, the Celery worker process imports only `app.worker` and never sees `rag.embed_source` / `rag.reembed_source` / etc., so `.delay()` calls would silently never run.

- [ ] **Step 7: Verify app still starts AND tasks are registered**

Run: `python -c "from app.main import app; print('ok')"`
Expected: `ok`

Run: `python -c "from app.worker import celery_app; import app.modules.rag.tasks; print(sorted(t for t in celery_app.tasks if t.startswith('rag.')))"`
Expected: `['rag.auto_close_idle_sessions', 'rag.embed_source', 'rag.reembed_all_dim_mismatch', 'rag.reembed_source']`

- [ ] **Step 8: Commit**

```bash
git add app/modules/rag/ app/main.py app/worker.py
git commit -m "feat(rag): scaffold module skeleton with stubs + worker task registration"
```

---

## Task A10: Embedding-dim startup health check

**Files:**
- Modify: `app/main.py`

- [ ] **Step 1: Edit `app/modules/rag/embedder.py` — implement `embed_and_validate` with a startup-friendly path**

Replace the stub with:

```python
"""Wraps AIService.embed() + dim validation. See spec §8."""

from app.config import get_settings

_settings = get_settings()


class EmbedDimensionMismatch(Exception):
    pass


async def embed_and_validate(texts: list[str]) -> list[list[float]]:
    """Embed texts via the AI gateway. Raises EmbedDimensionMismatch on dim mismatch."""
    from app.database import AsyncSessionLocal
    from app.modules.ai.service import AIService

    async with AsyncSessionLocal() as db:
        svc = AIService(db)
        result = await svc.embed(texts, model=_settings.EMBEDDING_MODEL_HINT)

    embeddings = result["embeddings"]
    for i, vec in enumerate(embeddings):
        if len(vec) != _settings.EMBEDDING_DIM:
            raise EmbedDimensionMismatch(
                f"Expected dim={_settings.EMBEDDING_DIM}, got dim={len(vec)} "
                f"from model={result['model']}, text index {i}"
            )
    return embeddings
```

- [ ] **Step 2: Add startup hook to `app/main.py`**

Inside `create_app()`, add a new startup handler **after** the existing `@app.on_event("startup") async def startup():`:

```python
    @app.on_event("startup")
    async def _validate_embedding_dim():
        if not (settings.OPENAI_API_KEY or settings.GEMINI_API_KEY):
            log.warning("embedding_dim_check_skipped", reason="no_api_keys")
            return
        try:
            from app.modules.rag.embedder import embed_and_validate
            vec = await embed_and_validate(["dimension check"])
            log.info("embedding_dim_validated", dim=len(vec[0]))
        except Exception as exc:
            log.error("embedding_dim_check_failed", error=str(exc))
            raise
```

- [ ] **Step 3: Verify app starts (with API key)**

Run (assuming `.env` has `OPENAI_API_KEY` set): `uvicorn app.main:app --port 8001 &` then `sleep 3 && curl -s http://localhost:8001/health && kill %1`
Expected: `{"status":"ok"}` and a log line `embedding_dim_validated dim=1536`.

If no API key is set: log `embedding_dim_check_skipped` and app starts normally. Both behaviors acceptable.

- [ ] **Step 4: Commit**

```bash
git add app/modules/rag/embedder.py app/main.py
git commit -m "feat(rag): implement embed_and_validate + startup dim health check"
```

---

# Phase B — Ingestion

Goal: approving a content source produces embedded chunks in pgvector.

## Task B1: Implement token counter

**Files:**
- Modify: `app/modules/rag/chunker.py`
- Create: `tests/unit/test_rag_chunker.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_rag_chunker.py`:

```python
from app.modules.rag.chunker import count_tokens


def test_count_tokens_returns_zero_for_empty():
    assert count_tokens("") == 0


def test_count_tokens_returns_positive_for_text():
    assert count_tokens("hello world") > 0


def test_count_tokens_grows_with_length():
    assert count_tokens("a b c d e f g h") > count_tokens("a b")
```

- [ ] **Step 2: Run — expect FAIL**

Run: `pytest tests/unit/test_rag_chunker.py::test_count_tokens_returns_zero_for_empty -v`
Expected: `NotImplementedError`

- [ ] **Step 3: Implement `count_tokens` (replace stub at top of `chunker.py`)**

Replace the existing `chunker.py` content with:

```python
"""Section tree -> ContentChunk records (3-rule hybrid). See spec §7."""

import tiktoken

_ENCODER = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    if not text:
        return 0
    return len(_ENCODER.encode(text))


def chunk_section_tree(source) -> list:
    raise NotImplementedError
```

- [ ] **Step 4: Run — expect PASS**

Run: `pytest tests/unit/test_rag_chunker.py -v -k count_tokens`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add app/modules/rag/chunker.py tests/unit/test_rag_chunker.py
git commit -m "feat(rag): tiktoken-based count_tokens"
```

---

## Task B2: Implement structural-primary + recursive sub-split chunking

**Files:**
- Modify: `app/modules/rag/chunker.py`
- Modify: `tests/unit/test_rag_chunker.py`

- [ ] **Step 1: Write failing tests for chunking**

Append to `tests/unit/test_rag_chunker.py`:

```python
from dataclasses import dataclass, field
from uuid import uuid4

from app.modules.rag.chunker import chunk_section_tree


@dataclass
class FakeRef:
    citation_key: str


@dataclass
class FakeSection:
    id: object
    section_number: str
    title: str
    content_markdown: str
    page_number: int | None = None
    children: list = field(default_factory=list)
    parent_section_id: object | None = None
    reference: FakeRef | None = None
    ordinal: int = 0


@dataclass
class FakeSource:
    id: object
    sections: list


def _section(num, title, body, key, page=1):
    sid = uuid4()
    return FakeSection(
        id=sid, section_number=num, title=title, content_markdown=body,
        page_number=page, reference=FakeRef(citation_key=key),
    )


def test_small_section_becomes_one_chunk():
    src = FakeSource(id=uuid4(), sections=[_section("3.2.1", "Engine Start", "Short body.", "K-3.2.1")])
    chunks = chunk_section_tree(src)
    assert len(chunks) == 1
    assert chunks[0]["citation_keys"] == ["K-3.2.1"]
    assert chunks[0]["section_id"] == src.sections[0].id
    assert chunks[0]["ordinal"] == 0
    assert "Engine Start" in chunks[0]["content"]


def test_large_section_is_sub_split():
    big_body = "lorem ipsum " * 800  # >> 800 tokens
    src = FakeSource(id=uuid4(), sections=[_section("3.2.1", "Big", big_body, "K-3.2.1")])
    chunks = chunk_section_tree(src)
    assert len(chunks) > 1
    assert all(c["citation_keys"] == ["K-3.2.1"] for c in chunks)
    assert [c["ordinal"] for c in chunks] == list(range(len(chunks)))


def test_walks_children():
    parent = _section("3", "Parent", "Parent body.", "K-3")
    child = _section("3.1", "Child", "Child body.", "K-3.1")
    parent.children = [child]
    src = FakeSource(id=uuid4(), sections=[parent])
    chunks = chunk_section_tree(src)
    keys = sorted({k for c in chunks for k in c["citation_keys"]})
    assert keys == ["K-3", "K-3.1"]
```

- [ ] **Step 2: Run — expect FAIL**

Run: `pytest tests/unit/test_rag_chunker.py -v`
Expected: new tests fail with `NotImplementedError`.

- [ ] **Step 3: Implement `chunk_section_tree` in `chunker.py`**

Replace the `chunker.py` content with the full implementation:

```python
"""Section tree -> ContentChunk records (3-rule hybrid). See spec §7."""

from dataclasses import dataclass, field

import tiktoken
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import get_settings

_ENCODER = tiktoken.get_encoding("cl100k_base")
_settings = get_settings()


def count_tokens(text: str) -> int:
    if not text:
        return 0
    return len(_ENCODER.encode(text))


def _heading_prefix(section) -> str:
    return f"## {section.section_number} {section.title}\n\n"


def _format_chunk(text: str, section) -> str:
    return f"{_heading_prefix(section)}{text}".strip()


def _splitter():
    return RecursiveCharacterTextSplitter(
        separators=["\n\n", "\n", ". ", " "],
        chunk_size=_settings.RAG_CHUNK_TOKENS_MAX * 4,        # rough char budget for token target
        chunk_overlap=_settings.RAG_CHUNK_OVERLAP_TOKENS * 4,
        length_function=len,
    )


def _chunk_one_section(section, ordinal_start: int) -> list[dict]:
    body = section.content_markdown or ""
    if not body.strip():
        return []
    if section.reference is None:
        # No citation key -> can't be cited, skip
        return []

    if count_tokens(body) <= _settings.RAG_CHUNK_TOKENS_MAX:
        return [{
            "section_id": section.id,
            "citation_keys": [section.reference.citation_key],
            "content": _format_chunk(body, section),
            "token_count": count_tokens(_format_chunk(body, section)),
            "ordinal": ordinal_start,
            "page_number": section.page_number,
        }]

    splitter = _splitter()
    pieces = splitter.split_text(body)
    chunks = []
    for i, piece in enumerate(pieces):
        formatted = _format_chunk(piece, section)
        chunks.append({
            "section_id": section.id,
            "citation_keys": [section.reference.citation_key],
            "content": formatted,
            "token_count": count_tokens(formatted),
            "ordinal": ordinal_start + i,
            "page_number": section.page_number,
        })
    return chunks


def chunk_section_tree(source) -> list[dict]:
    """Walk the section tree and produce a flat list of chunk dicts.

    Each dict has: section_id, citation_keys (list[str]), content, token_count,
    ordinal, page_number.
    """
    chunks: list[dict] = []

    def walk(sections):
        for sec in sections:
            new = _chunk_one_section(sec, ordinal_start=len(chunks))
            chunks.extend(new)
            if getattr(sec, "children", None):
                walk(sec.children)

    walk(source.sections)
    return chunks
```

- [ ] **Step 4: Run — expect PASS**

Run: `pytest tests/unit/test_rag_chunker.py -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/modules/rag/chunker.py tests/unit/test_rag_chunker.py
git commit -m "feat(rag): structural-primary + recursive sub-split chunking"
```

---

## Task B3: Sibling-merge sweep

**Files:**
- Modify: `app/modules/rag/chunker.py`
- Modify: `tests/unit/test_rag_chunker.py`

- [ ] **Step 1: Write failing test**

Append to `tests/unit/test_rag_chunker.py`:

```python
def test_tiny_adjacent_siblings_merge():
    parent = _section("3", "Parent", "", "K-3")
    a = _section("3.1", "A", "tiny.", "K-3.1")
    b = _section("3.2", "B", "also tiny.", "K-3.2")
    parent.children = [a, b]
    src = FakeSource(id=uuid4(), sections=[parent])
    chunks = chunk_section_tree(src)
    # parent has empty body -> 0 chunks; a and b should merge
    merged = [c for c in chunks if len(c["citation_keys"]) > 1]
    assert len(merged) == 1
    assert sorted(merged[0]["citation_keys"]) == ["K-3.1", "K-3.2"]
```

- [ ] **Step 2: Run — expect FAIL**

Run: `pytest tests/unit/test_rag_chunker.py::test_tiny_adjacent_siblings_merge -v`
Expected: FAIL — currently produces 2 separate small chunks.

- [ ] **Step 3: Add `_merge_small_siblings` and call it from `chunk_section_tree`**

Edit `app/modules/rag/chunker.py` — add this helper and update `chunk_section_tree`:

```python
def _merge_small_siblings(chunks: list[dict]) -> list[dict]:
    threshold = _settings.RAG_CHUNK_TOKENS_MIN_MERGE
    merged: list[dict] = []
    i = 0
    while i < len(chunks):
        current = chunks[i]
        # only merge consecutive single-citation chunks both under threshold
        if (
            i + 1 < len(chunks)
            and current["token_count"] < threshold
            and chunks[i + 1]["token_count"] < threshold
            and len(current["citation_keys"]) == 1
            and len(chunks[i + 1]["citation_keys"]) == 1
        ):
            nxt = chunks[i + 1]
            merged.append({
                "section_id": current["section_id"],  # arbitrary; first wins
                "citation_keys": current["citation_keys"] + nxt["citation_keys"],
                "content": current["content"] + "\n\n" + nxt["content"],
                "token_count": current["token_count"] + nxt["token_count"],
                "ordinal": current["ordinal"],
                "page_number": current["page_number"],
            })
            i += 2
        else:
            merged.append(current)
            i += 1
    # Re-sequence ordinals
    for idx, c in enumerate(merged):
        c["ordinal"] = idx
    return merged
```

Then update the bottom of `chunk_section_tree`:

```python
def chunk_section_tree(source) -> list[dict]:
    chunks: list[dict] = []

    def walk(sections):
        for sec in sections:
            new = _chunk_one_section(sec, ordinal_start=len(chunks))
            chunks.extend(new)
            if getattr(sec, "children", None):
                walk(sec.children)

    walk(source.sections)
    return _merge_small_siblings(chunks)
```

- [ ] **Step 4: Run — expect PASS**

Run: `pytest tests/unit/test_rag_chunker.py -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/modules/rag/chunker.py tests/unit/test_rag_chunker.py
git commit -m "feat(rag): sibling-merge sweep for tiny adjacent chunks"
```

---

## Task B4: Embedder dim-validation tests

**Files:**
- Create: `tests/unit/test_rag_embedder.py`

- [ ] **Step 1: Write the test**

```python
import pytest
from unittest.mock import AsyncMock, patch

from app.modules.rag.embedder import EmbedDimensionMismatch, embed_and_validate


async def test_embed_and_validate_passes_when_dim_matches():
    fake_result = {
        "embeddings": [[0.1] * 1536, [0.2] * 1536],
        "model": "text-embedding-3-small",
        "usage": {"total_tokens": 4},
    }
    with patch("app.modules.rag.embedder.AsyncSessionLocal") as mock_session, \
         patch("app.modules.rag.embedder.AIService") as MockAI:
        instance = MockAI.return_value
        instance.embed = AsyncMock(return_value=fake_result)
        mock_session.return_value.__aenter__.return_value = AsyncMock()
        out = await embed_and_validate(["foo", "bar"])
        assert len(out) == 2
        assert all(len(v) == 1536 for v in out)


async def test_embed_and_validate_raises_on_dim_mismatch():
    fake_result = {
        "embeddings": [[0.1] * 768],   # wrong dim
        "model": "text-embedding-004",
        "usage": {"total_tokens": 2},
    }
    with patch("app.modules.rag.embedder.AsyncSessionLocal") as mock_session, \
         patch("app.modules.rag.embedder.AIService") as MockAI:
        instance = MockAI.return_value
        instance.embed = AsyncMock(return_value=fake_result)
        mock_session.return_value.__aenter__.return_value = AsyncMock()
        with pytest.raises(EmbedDimensionMismatch):
            await embed_and_validate(["foo"])
```

- [ ] **Step 2: Run — expect PASS** (embedder is already implemented from Task A10)

Run: `pytest tests/unit/test_rag_embedder.py -v`
Expected: 2 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_rag_embedder.py
git commit -m "test(rag): embedder dim-validation tests"
```

---

## Task B5: Synthetic FCOM fixture for integration tests

**Files:**
- Create: `tests/fixtures/__init__.py`
- Create: `tests/fixtures/synthetic_fcom.py`

- [ ] **Step 1: Create `tests/fixtures/__init__.py`** (empty)

```python
```

- [ ] **Step 2: Create `tests/fixtures/synthetic_fcom.py`**

```python
"""Synthetic FCOM-shaped section tree for RAG integration tests.

Builds real ContentSource + ContentSection + ContentReference rows so the
ingestion pipeline can be tested without Sachin's real parsers.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.content.models import ContentReference, ContentSection, ContentSource


async def seed_synthetic_fcom(db: AsyncSession, aircraft_id: uuid.UUID | None = None) -> ContentSource:
    """Insert one approved FCOM-shaped source with 4 sections, return the source."""
    source = ContentSource(
        id=uuid.uuid4(),
        source_type="fcom",
        aircraft_id=aircraft_id,
        title="Synthetic FCOM",
        version="Rev 1",
        effective_date=datetime.now(UTC).date(),
        status="approved",
        approved_by=None,
        approved_at=datetime.now(UTC),
    )
    db.add(source)
    await db.flush()

    sections_data = [
        ("3", "Engines", 0, None,
         "Engine systems overview. " * 5,
         "SYN-FCOM-3", 100),
        ("3.1", "Engine Start - Normal", 0, None,
         "Place ENG MASTER to ON. Verify N1 rises above 25% before introducing fuel. " * 30,
         "SYN-FCOM-3.1", 105),
        ("3.2", "Engine Start - Cold Weather", 1, None,
         "Below 0 degC OAT, motor the engine for 30 seconds prior to fuel introduction. " * 30,
         "SYN-FCOM-3.2", 108),
        ("4", "Hydraulics", 1, None,
         "Two independent hydraulic systems supply flight controls. " * 25,
         "SYN-FCOM-4", 200),
    ]

    parent_section = None
    for sec_num, title, ordinal, _parent_idx, body, citation_key, page in sections_data:
        section = ContentSection(
            id=uuid.uuid4(),
            source_id=source.id,
            parent_section_id=None,  # flat for simplicity
            section_number=sec_num,
            title=title,
            content_markdown=body,
            page_number=page,
            ordinal=ordinal,
        )
        db.add(section)
        await db.flush()

        ref = ContentReference(
            id=uuid.uuid4(),
            source_id=source.id,
            section_id=section.id,
            citation_key=citation_key,
            display_label=f"FCOM §{sec_num} - {title}",
        )
        db.add(ref)

    await db.flush()
    return source
```

- [ ] **Step 3: Smoke-check the fixture**

Run: `pytest --collect-only tests/fixtures 2>&1 | head -5`
Expected: collected 0 (it's a fixture file, not tests). No import errors.

- [ ] **Step 4: Commit**

```bash
git add tests/fixtures/
git commit -m "test(rag): synthetic FCOM fixture for integration tests"
```

---

## Task B6: Implement `embed_source` Celery task

**Files:**
- Modify: `app/modules/rag/tasks.py`
- Create: `tests/integration/test_rag_ingestion.py`

- [ ] **Step 1: Write failing integration test**

```python
import asyncio
import uuid
from unittest.mock import patch, AsyncMock

import pytest
from sqlalchemy import select

from app.modules.content.models import ContentSource
from app.modules.rag.models import ContentChunk
from app.modules.rag.tasks import embed_source
from tests.fixtures.synthetic_fcom import seed_synthetic_fcom


async def test_embed_source_creates_chunks(db_session):
    source = await seed_synthetic_fcom(db_session)
    await db_session.commit()

    fake_embeddings = {"embeddings": [[0.1] * 1536] * 50, "model": "text-embedding-3-small", "usage": {"total_tokens": 100}}
    with patch("app.modules.rag.embedder.AIService") as MockAI:
        instance = MockAI.return_value
        instance.embed = AsyncMock(return_value=fake_embeddings)
        await asyncio.to_thread(embed_source, str(source.id))

    rows = (await db_session.execute(select(ContentChunk).where(ContentChunk.source_id == source.id))).scalars().all()
    assert len(rows) >= 4  # one per non-empty section, possibly more if any over budget
    keys_seen = {k for c in rows for k in c.citation_keys}
    assert keys_seen >= {"SYN-FCOM-3.1", "SYN-FCOM-3.2", "SYN-FCOM-4"}
    assert all(c.embedding_dim == 1536 for c in rows)
    assert all(len(c.embedding) == 1536 for c in rows)

    # source status updated
    src_after = (await db_session.execute(select(ContentSource).where(ContentSource.id == source.id))).scalar_one()
    assert src_after.embedding_status == "succeeded"
```

- [ ] **Step 2: Run — expect FAIL** (`embed_source` raises NotImplementedError)

Run: `pytest tests/integration/test_rag_ingestion.py -v`
Expected: NotImplementedError.

- [ ] **Step 3: Implement `embed_source` in `app/modules/rag/tasks.py`**

Replace the file content with:

```python
"""Celery tasks: embed_source, reembed_source, reembed_all_dim_mismatch, auto_close_idle_sessions."""

import asyncio

import structlog
from celery import group
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.modules.content.models import ContentSection, ContentSource
from app.modules.rag.chunker import chunk_section_tree
from app.modules.rag.embedder import embed_and_validate
from app.modules.rag.models import ContentChunk
from app.worker import celery_app

log = structlog.get_logger()
_settings = get_settings()
_BATCH_SIZE = 50


async def _load_source_with_tree(db, source_id: str) -> ContentSource | None:
    result = await db.execute(
        select(ContentSource)
        .where(ContentSource.id == source_id)
        .options(
            selectinload(ContentSource.sections).selectinload(ContentSection.children),
            selectinload(ContentSource.sections).selectinload(ContentSection.reference),
        )
    )
    return result.scalar_one_or_none()


async def _embed_source_async(source_id: str) -> int:
    async with AsyncSessionLocal() as db:
        source = await _load_source_with_tree(db, source_id)
        if not source:
            log.warning("embed_source_missing", source_id=source_id)
            return 0

        existing_count = (await db.execute(
            select(ContentChunk).where(ContentChunk.source_id == source.id).limit(1)
        )).first()
        if existing_count:
            log.info("embed_source_skipped_existing", source_id=source_id)
            return 0

        chunks = chunk_section_tree(source)
        if not chunks:
            log.warning("embed_source_no_chunks", source_id=source_id)
            source.embedding_status = "succeeded"
            await db.commit()
            return 0

        # Batched embedding
        for i in range(0, len(chunks), _BATCH_SIZE):
            batch = chunks[i : i + _BATCH_SIZE]
            try:
                vectors = await embed_and_validate([c["content"] for c in batch])
            except Exception as exc:
                log.error("embed_source_failed", source_id=source_id, error=str(exc))
                source.embedding_status = "failed"
                await db.commit()
                raise
            for chunk_dict, vec in zip(batch, vectors, strict=True):
                db.add(ContentChunk(
                    source_id=source.id,
                    section_id=chunk_dict["section_id"],
                    citation_keys=chunk_dict["citation_keys"],
                    content=chunk_dict["content"],
                    token_count=chunk_dict["token_count"],
                    ordinal=chunk_dict["ordinal"],
                    embedding=vec,
                    embedding_model=_settings.EMBEDDING_MODEL_HINT,
                    embedding_dim=_settings.EMBEDDING_DIM,
                ))

        # Supersedence sweep
        prior = (await db.execute(
            select(ContentSource).where(
                ContentSource.source_type == source.source_type,
                ContentSource.aircraft_id == source.aircraft_id,
                ContentSource.title == source.title,
                ContentSource.id != source.id,
                ContentSource.status == "approved",
            )
        )).scalars().all()
        for old in prior:
            old.status = "archived"
            await db.execute(
                ContentChunk.__table__.update()
                .where(ContentChunk.source_id == old.id)
                .values(superseded_by_source_id=source.id)
            )

        source.embedding_status = "succeeded"
        await db.commit()
        return len(chunks)


@celery_app.task(name="rag.embed_source", autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def embed_source(source_id: str) -> int:
    return asyncio.run(_embed_source_async(source_id))


@celery_app.task(name="rag.reembed_source")
def reembed_source(source_id: str) -> int:
    raise NotImplementedError


@celery_app.task(name="rag.reembed_all_dim_mismatch")
def reembed_all_dim_mismatch() -> int:
    raise NotImplementedError


@celery_app.task(name="rag.auto_close_idle_sessions")
def auto_close_idle_sessions() -> int:
    raise NotImplementedError
```

- [ ] **Step 4: Run — expect PASS**

Run: `pytest tests/integration/test_rag_ingestion.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add app/modules/rag/tasks.py tests/integration/test_rag_ingestion.py
git commit -m "feat(rag): embed_source Celery task with idempotency + supersedence"
```

---

## Task B7: Hook `embed_source` into `approve_source`

**Files:**
- Modify: `app/modules/content/service.py`
- Modify: `tests/integration/test_rag_ingestion.py`

- [ ] **Step 1: Write failing test**

Append to `tests/integration/test_rag_ingestion.py`:

```python
async def test_approve_source_enqueues_embed_task(db_session):
    source = await seed_synthetic_fcom(db_session)
    source.status = "draft"
    await db_session.commit()

    from app.modules.content.service import ContentService
    svc = ContentService(db_session)
    with patch("app.modules.content.service.embed_source") as mock_task:
        await svc.approve_source(str(source.id), uuid.uuid4())
        mock_task.delay.assert_called_once_with(str(source.id))
```

- [ ] **Step 2: Run — expect FAIL** (no `embed_source` import in service.py yet)

Run: `pytest tests/integration/test_rag_ingestion.py::test_approve_source_enqueues_embed_task -v`
Expected: FAIL or AttributeError.

- [ ] **Step 3: Edit `app/modules/content/service.py`**

Add this import at the top:

```python
from app.modules.rag.tasks import embed_source
```

Replace `approve_source` method body:

```python
    async def approve_source(self, source_id: str, approver_id: str) -> ContentSource:
        from datetime import UTC, datetime
        source = await self.get_source(source_id)
        source.approved_by = approver_id
        source.approved_at = datetime.now(UTC)
        source.status = "approved"
        await self.db.flush()
        embed_source.delay(str(source.id))
        log.info("approve_source_enqueued_embed", source_id=str(source.id))
        return source
```

- [ ] **Step 4: Run — expect PASS**

Run: `pytest tests/integration/test_rag_ingestion.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add app/modules/content/service.py tests/integration/test_rag_ingestion.py
git commit -m "feat(content): enqueue embed_source on approve_source"
```

---

## Task B8: Reembed endpoint + task

**Files:**
- Modify: `app/modules/rag/tasks.py`
- Modify: `app/modules/content/router.py`

- [ ] **Step 1: Implement `reembed_source` task**

In `app/modules/rag/tasks.py`, add this helper above `_embed_source_async`:

```python
async def _delete_chunks(db, source_id: str) -> int:
    from sqlalchemy import delete
    result = await db.execute(delete(ContentChunk).where(ContentChunk.source_id == source_id))
    return result.rowcount or 0


async def _reembed_source_async(source_id: str) -> int:
    async with AsyncSessionLocal() as db:
        deleted = await _delete_chunks(db, source_id)
        await db.commit()
        log.info("reembed_source_deleted", source_id=source_id, count=deleted)
    # Now run normal ingestion
    return await _embed_source_async(source_id)
```

Replace the stub `reembed_source` task:

```python
@celery_app.task(name="rag.reembed_source", autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def reembed_source(source_id: str) -> int:
    return asyncio.run(_reembed_source_async(source_id))
```

- [ ] **Step 2: Add the admin endpoint to `app/modules/content/router.py`**

Add after `approve_source` route:

```python
@router.post(
    "/sources/{source_id}/reembed",
    status_code=202,
    response_model=dict,
    summary="Force re-embedding of a source (admin)",
    description=(
        "Deletes existing chunks for the source_id and re-runs the embedding worker. "
        "Use after chunker improvements or model changes.\n\n"
        "**Required permission:** `content:approve` (admin/instructor)."
    ),
    responses={**_401, **_403, **_404},
    operation_id="content_sources_reembed",
)
async def reembed_source_endpoint(
    source_id: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if current_user.role not in ("admin", "instructor"):
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Admin or instructor required")
    svc = ContentService(db)
    src = await svc.get_source(source_id)  # 404s if missing
    from app.modules.rag.tasks import reembed_source
    reembed_source.delay(str(src.id))
    return {"data": {"source_id": str(src.id), "status": "reembedding"}}
```

- [ ] **Step 3: Smoke test by running the app**

Run: `uvicorn app.main:app --port 8001 &` then `sleep 2 && curl -s http://localhost:8001/api/v1/docs/openapi.json | python -c "import json, sys; ops=[r['operationId'] for p in json.load(sys.stdin)['paths'].values() for r in p.values()]; print('content_sources_reembed' in ops)"; kill %1`
Expected: `True`

- [ ] **Step 4: Commit**

```bash
git add app/modules/rag/tasks.py app/modules/content/router.py
git commit -m "feat(rag): reembed_source task + admin reembed endpoint"
```

---

## Task B9: Bulk reembed task `reembed_all_dim_mismatch`

**Files:**
- Modify: `app/modules/rag/tasks.py`

- [ ] **Step 1: Implement `reembed_all_dim_mismatch`**

In `app/modules/rag/tasks.py`, add helper + replace stub:

```python
async def _reembed_all_dim_mismatch_async() -> int:
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(ContentChunk.source_id)
            .where(ContentChunk.embedding_dim != _settings.EMBEDDING_DIM)
            .distinct()
        )).scalars().all()
    count = 0
    for source_id in rows:
        reembed_source.delay(str(source_id))
        count += 1
    log.info("reembed_all_dim_mismatch_enqueued", count=count)
    return count


@celery_app.task(name="rag.reembed_all_dim_mismatch")
def reembed_all_dim_mismatch() -> int:
    return asyncio.run(_reembed_all_dim_mismatch_async())
```

- [ ] **Step 2: Manual smoke**

Run: `python -c "from app.modules.rag.tasks import reembed_all_dim_mismatch; print(reembed_all_dim_mismatch.run())"`
Expected: prints `0` (no chunks with mismatched dim in fresh test DB).

- [ ] **Step 3: Commit**

```bash
git add app/modules/rag/tasks.py
git commit -m "feat(rag): bulk reembed_all_dim_mismatch task"
```

---

# Phase C — Retrieval

Goal: pure retrieval works. Standalone `POST /rag/query` returns ranked citation_keys.

## Task C1: Vector search SQL function

**Files:**
- Modify: `app/modules/rag/retriever.py`
- Create: `tests/integration/test_rag_retrieval.py`

- [ ] **Step 1: Write failing test**

```python
import uuid
from unittest.mock import patch, AsyncMock

import pytest

from app.modules.rag.tasks import _embed_source_async
from app.modules.rag.retriever import _vector_search
from tests.fixtures.synthetic_fcom import seed_synthetic_fcom


async def test_vector_search_returns_chunks_with_scores(db_session):
    source = await seed_synthetic_fcom(db_session)
    await db_session.commit()
    fake = {"embeddings": [[0.1] * 1536] * 50, "model": "x", "usage": {"total_tokens": 1}}
    with patch("app.modules.rag.embedder.AIService") as MockAI:
        MockAI.return_value.embed = AsyncMock(return_value=fake)
        await _embed_source_async(str(source.id))

    qvec = [0.1] * 1536
    rows = await _vector_search(db_session, qvec, top_k=5, aircraft_id=None)
    assert len(rows) > 0
    assert all("citation_keys" in r for r in rows)
    assert all("cosine_score" in r for r in rows)
    # all chunks have the same vector so all scores ≈ 1.0
    assert all(r["cosine_score"] > 0.99 for r in rows)
```

- [ ] **Step 2: Run — expect FAIL**

Run: `pytest tests/integration/test_rag_retrieval.py -v`
Expected: ImportError on `_vector_search`.

- [ ] **Step 3: Implement `_vector_search` in `app/modules/rag/retriever.py`**

Replace the stub with:

```python
"""Vector search + MMR + threshold filter. See spec §9."""

from dataclasses import dataclass
from uuid import UUID

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings

log = structlog.get_logger()
_settings = get_settings()


@dataclass
class Hit:
    chunk_id: UUID
    section_id: UUID
    citation_keys: list[str]
    content: str
    page_number: int | None
    score: float
    mmr_rank: int = -1
    included: bool = False


async def _vector_search(
    db: AsyncSession,
    qvec: list[float],
    top_k: int,
    aircraft_id: UUID | None,
) -> list[dict]:
    """Raw pgvector search. Returns ranked candidate dicts."""
    sql = text("""
        SELECT
            c.id AS chunk_id,
            c.section_id,
            c.citation_keys,
            c.content,
            sec.page_number,
            1 - (c.embedding <=> CAST(:qvec AS vector)) AS cosine_score
        FROM content_chunks c
        JOIN content_sources s ON s.id = c.source_id
        JOIN content_sections sec ON sec.id = c.section_id
        WHERE c.superseded_by_source_id IS NULL
          AND s.status = 'approved'
          AND (s.aircraft_id = :aircraft_id OR s.aircraft_id IS NULL)
        ORDER BY c.embedding <=> CAST(:qvec AS vector)
        LIMIT :top_k
    """)
    result = await db.execute(sql, {
        "qvec": str(qvec),
        "aircraft_id": str(aircraft_id) if aircraft_id else None,
        "top_k": top_k,
    })
    return [dict(row._mapping) for row in result]


async def retrieve(db: AsyncSession, query: str, aircraft_id: UUID | None, cfg: dict | None = None) -> list[Hit]:
    raise NotImplementedError  # implemented in Task C3
```

- [ ] **Step 4: Run — expect PASS**

Run: `pytest tests/integration/test_rag_retrieval.py::test_vector_search_returns_chunks_with_scores -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add app/modules/rag/retriever.py tests/integration/test_rag_retrieval.py
git commit -m "feat(rag): pgvector cosine search with aircraft scoping"
```

---

## Task C2: MMR diversification

**Files:**
- Modify: `app/modules/rag/retriever.py`
- Create: `tests/unit/test_rag_mmr.py`

- [ ] **Step 1: Write failing tests**

```python
import math

from app.modules.rag.retriever import _mmr_rerank


def _vec(*xs):
    return list(xs)


def test_mmr_returns_all_when_few_candidates():
    cands = [
        {"id": "a", "embedding": _vec(1, 0, 0), "score": 0.9},
        {"id": "b", "embedding": _vec(0, 1, 0), "score": 0.8},
    ]
    out = _mmr_rerank(cands, lambda_=0.5, qvec=_vec(1, 0, 0))
    assert {c["id"] for c in out} == {"a", "b"}


def test_mmr_prefers_diversity_when_lambda_low():
    cands = [
        {"id": "a", "embedding": _vec(1, 0, 0), "score": 0.99},
        {"id": "a2", "embedding": _vec(0.99, 0.01, 0), "score": 0.98},  # near-duplicate of a
        {"id": "b", "embedding": _vec(0, 1, 0), "score": 0.50},          # very different
    ]
    out = _mmr_rerank(cands, lambda_=0.0, qvec=_vec(1, 0, 0))
    # With lambda=0 (pure diversity) the second pick should be "b" not "a2"
    assert out[0]["id"] == "a"
    assert out[1]["id"] == "b"


def test_mmr_pure_relevance_when_lambda_one():
    cands = [
        {"id": "a", "embedding": _vec(1, 0, 0), "score": 0.99},
        {"id": "b", "embedding": _vec(0, 1, 0), "score": 0.80},
        {"id": "c", "embedding": _vec(0, 0, 1), "score": 0.70},
    ]
    out = _mmr_rerank(cands, lambda_=1.0, qvec=_vec(1, 0, 0))
    # lambda=1 -> pure score order
    assert [c["id"] for c in out] == ["a", "b", "c"]
```

- [ ] **Step 2: Run — expect FAIL**

Run: `pytest tests/unit/test_rag_mmr.py -v`
Expected: ImportError on `_mmr_rerank`.

- [ ] **Step 3: Implement `_mmr_rerank` in `app/modules/rag/retriever.py`**

Add to `retriever.py`:

```python
def _cosine(a: list[float], b: list[float]) -> float:
    import math
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _mmr_rerank(candidates: list[dict], lambda_: float, qvec: list[float]) -> list[dict]:
    """Greedy Maximum Marginal Relevance.

    candidates: list of dicts with at least 'embedding' (list[float]) and 'score' (float).
    Returns reordered list, same length, with no duplicates.
    """
    if not candidates:
        return []
    selected: list[dict] = []
    remaining = list(candidates)
    # First pick = highest score
    remaining.sort(key=lambda c: -c["score"])
    selected.append(remaining.pop(0))

    while remaining:
        best_idx = 0
        best_mmr = -float("inf")
        for i, cand in enumerate(remaining):
            sim_to_query = cand["score"]
            sim_to_selected = max(_cosine(cand["embedding"], s["embedding"]) for s in selected)
            mmr = lambda_ * sim_to_query - (1 - lambda_) * sim_to_selected
            if mmr > best_mmr:
                best_mmr = mmr
                best_idx = i
        selected.append(remaining.pop(best_idx))
    return selected
```

- [ ] **Step 4: Run — expect PASS**

Run: `pytest tests/unit/test_rag_mmr.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add app/modules/rag/retriever.py tests/unit/test_rag_mmr.py
git commit -m "feat(rag): MMR greedy reranker with unit tests"
```

---

## Task C3: `retrieve()` orchestration + extend `_vector_search` to return embedding

**Files:**
- Modify: `app/modules/rag/retriever.py`

- [ ] **Step 1: Update `_vector_search` SELECT to also return `embedding`** (needed for MMR)

In `retriever.py`, edit the SQL to add `c.embedding` to the SELECT:

```python
sql = text("""
    SELECT
        c.id AS chunk_id,
        c.section_id,
        c.citation_keys,
        c.content,
        c.embedding,
        sec.page_number,
        1 - (c.embedding <=> CAST(:qvec AS vector)) AS cosine_score
    FROM content_chunks c
    JOIN content_sources s ON s.id = c.source_id
    JOIN content_sections sec ON sec.id = c.section_id
    WHERE c.superseded_by_source_id IS NULL
      AND s.status = 'approved'
      AND (s.aircraft_id = :aircraft_id OR s.aircraft_id IS NULL)
    ORDER BY c.embedding <=> CAST(:qvec AS vector)
    LIMIT :top_k
""")
```

The pgvector driver returns `embedding` as a numpy array; convert to list inside the result loop:

```python
out = []
for row in result:
    d = dict(row._mapping)
    d["embedding"] = list(d["embedding"])
    out.append(d)
return out
```

- [ ] **Step 2: Implement `retrieve()`**

Replace the stub `retrieve` in `retriever.py`:

```python
async def retrieve(
    db: AsyncSession,
    query: str,
    aircraft_id: UUID | None,
    cfg: dict | None = None,
) -> tuple[list[Hit], dict]:
    """Embed query, vector search, MMR diversify, return Hit list + latency dict."""
    import time
    from app.modules.rag.embedder import embed_and_validate

    cfg = cfg or {
        "top_k": _settings.RAG_TOP_K,
        "mmr_lambda": _settings.RAG_MMR_LAMBDA,
    }
    latency: dict[str, int] = {}

    t0 = time.monotonic()
    qvec = (await embed_and_validate([query]))[0]
    latency["embed"] = int((time.monotonic() - t0) * 1000)

    t0 = time.monotonic()
    candidates = await _vector_search(db, qvec, cfg["top_k"], aircraft_id)
    latency["vector_search"] = int((time.monotonic() - t0) * 1000)

    t0 = time.monotonic()
    diversified = _mmr_rerank(candidates, cfg["mmr_lambda"], qvec)
    latency["mmr"] = int((time.monotonic() - t0) * 1000)

    hits = []
    for rank, c in enumerate(diversified):
        hits.append(Hit(
            chunk_id=c["chunk_id"],
            section_id=c["section_id"],
            citation_keys=c["citation_keys"],
            content=c["content"],
            page_number=c["page_number"],
            score=float(c["cosine_score"]),
            mmr_rank=rank,
        ))
    return hits, latency
```

- [ ] **Step 3: Smoke test**

Run: `pytest tests/integration/test_rag_retrieval.py -v`
Expected: existing test still passes (we changed the function signature but existing test only calls `_vector_search`).

- [ ] **Step 4: Commit**

```bash
git add app/modules/rag/retriever.py
git commit -m "feat(rag): retrieve() orchestrates embed -> vector_search -> MMR"
```

---

## Task C4: Grounder + prompt templates

**Files:**
- Modify: `app/modules/rag/grounder.py`
- Modify: `app/modules/rag/prompts.py`
- Create: `tests/unit/test_rag_grounder.py`

- [ ] **Step 1: Write failing tests**

```python
from dataclasses import dataclass

from app.modules.rag.grounder import decide


@dataclass
class FakeHit:
    score: float
    citation_keys: list[str]
    content: str = "x"
    chunk_id: str = "id"
    section_id: str = "sec"
    page_number: int | None = None
    mmr_rank: int = 0
    included: bool = False


CFG = {
    "include_threshold": 0.65,
    "soft_include_threshold": 0.60,
    "suggest_threshold": 0.50,
    "max_chunks": 5,
}


def test_strong_when_hits_above_high():
    hits = [FakeHit(0.9, ["a"]), FakeHit(0.8, ["b"]), FakeHit(0.4, ["c"])]
    out = decide(hits, CFG)
    assert out["grounded"] == "strong"
    assert sorted(out["citation_keys"]) == ["a", "b"]


def test_soft_when_top_in_rescue_band():
    hits = [FakeHit(0.62, ["a"]), FakeHit(0.55, ["b"]), FakeHit(0.40, ["c"])]
    out = decide(hits, CFG)
    assert out["grounded"] == "soft"
    assert out["citation_keys"] == ["a"]


def test_refused_when_no_hit_above_soft():
    hits = [FakeHit(0.55, ["a"]), FakeHit(0.52, ["b"]), FakeHit(0.40, ["c"])]
    out = decide(hits, CFG)
    assert out["grounded"] == "refused"
    assert out["citation_keys"] == []
    assert sorted([s["citation_key"] for s in out["suggestions"]]) == ["a", "b"]


def test_refused_with_no_suggestions_when_all_below_low():
    hits = [FakeHit(0.40, ["a"]), FakeHit(0.30, ["b"])]
    out = decide(hits, CFG)
    assert out["grounded"] == "refused"
    assert out["suggestions"] == []


def test_max_chunks_cap_in_strong():
    hits = [FakeHit(0.9, [f"k{i}"]) for i in range(10)]
    out = decide(hits, CFG)
    assert len(out["citation_keys"]) == 5
```

- [ ] **Step 2: Run — expect FAIL**

Run: `pytest tests/unit/test_rag_grounder.py -v`
Expected: NotImplementedError.

- [ ] **Step 3: Implement `decide` in `app/modules/rag/grounder.py`**

Replace file content:

```python
"""Grounding decision: strong | soft | refused. See spec §10."""


def decide(hits: list, cfg: dict) -> dict:
    """Return {"grounded": "strong"|"soft"|"refused",
                "citation_keys": [...],
                "included_hits": [Hit...],
                "suggestions": [{"citation_key", "score", "content", "page_number"}, ...]}.
    """
    high = cfg["include_threshold"]
    soft = cfg["soft_include_threshold"]
    low = cfg["suggest_threshold"]
    cap = cfg["max_chunks"]

    above_high = [h for h in hits if h.score >= high][:cap]
    above_soft = [h for h in hits if h.score >= soft]
    above_low = [h for h in hits if h.score >= low]

    if above_high:
        for h in above_high:
            h.included = True
        return {
            "grounded": "strong",
            "citation_keys": [k for h in above_high for k in h.citation_keys],
            "included_hits": above_high,
            "suggestions": [],
        }
    if above_soft:
        rescue = above_soft[0]
        rescue.included = True
        return {
            "grounded": "soft",
            "citation_keys": list(rescue.citation_keys),
            "included_hits": [rescue],
            "suggestions": [],
        }
    return {
        "grounded": "refused",
        "citation_keys": [],
        "included_hits": [],
        "suggestions": [
            {
                "citation_key": h.citation_keys[0] if h.citation_keys else "",
                "score": h.score,
                "content": h.content,
                "page_number": h.page_number,
            }
            for h in above_low[:3]
        ],
    }
```

- [ ] **Step 4: Run — expect PASS**

Run: `pytest tests/unit/test_rag_grounder.py -v`
Expected: 5 passed.

- [ ] **Step 5: Fill in prompt templates in `app/modules/rag/prompts.py`**

Replace file content with:

```python
"""System prompt + refusal templates. See spec §13."""

TRAINEE_SYSTEM_PROMPT = """You are an aerospace training assistant for the Indian Air Force.
Audience: trainee ({aircraft_context} program).

RULES:
1. Answer ONLY using the reference material provided in this conversation.
2. If the reference is insufficient, say so explicitly. Do NOT speculate.
3. Cite specific sections in your answer using the citation_key in [brackets].
4. Use **bold** for safety-critical values, limits, and warnings.
5. Be concise. Trainees are practicing, not reading textbooks.

Explain at training level. Avoid deep maintenance theory unless asked."""


INSTRUCTOR_SYSTEM_PROMPT = """You are an aerospace training assistant for the Indian Air Force.
Audience: instructor ({aircraft_context} program).

RULES:
1. Answer ONLY using the reference material provided in this conversation.
2. If the reference is insufficient, say so explicitly. Do NOT speculate.
3. Cite specific sections in your answer using the citation_key in [brackets].
4. Use **bold** for safety-critical values, limits, and warnings.
5. Be concise.

Provide deeper technical detail. Include cross-references to related procedures where relevant."""


SOFT_GROUNDED_PREFIX = """Note: The reference material below is the closest available match but may not be a perfect fit for the question. Caveat your answer accordingly."""


REFUSAL_TEMPLATE = """I don't have approved source material that answers this question directly.

{suggestion_block}

Please consult your instructor or check these sections manually."""


REWRITER_PROMPT = """You rewrite the user's latest message into a standalone search query for a document retrieval system over aerospace training manuals.

RULES:
- Resolve pronouns and references using the conversation history.
- DO NOT invent specifics not present in the conversation (no temperatures, altitudes, aircraft types, conditions unless the user mentioned them).
- Keep it concise (≤30 words).
- If the current message is already a standalone question, return it unchanged.
- Output ONLY the rewritten query. No preamble, no explanation.

Conversation history:
{history}

Current message:
{message}

Standalone retrieval query:"""


def render_refusal(suggestions: list[dict]) -> str:
    if not suggestions:
        suggestion_block = "No related references found."
    else:
        lines = [
            f"  • [{s['citation_key']}] (relevance: moderate)"
            for s in suggestions
        ]
        suggestion_block = "Closest related references:\n" + "\n".join(lines)
    return REFUSAL_TEMPLATE.format(suggestion_block=suggestion_block)
```

- [ ] **Step 6: Commit**

```bash
git add app/modules/rag/grounder.py app/modules/rag/prompts.py tests/unit/test_rag_grounder.py
git commit -m "feat(rag): grounding decision logic + prompt templates"
```

---

## Task C5: `POST /rag/query` debug endpoint

**Files:**
- Modify: `app/modules/rag/router.py`
- Modify: `app/main.py`

- [ ] **Step 1: Implement the router**

Replace `app/modules/rag/router.py`:

```python
from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.routing import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.auth.deps import get_current_user
from app.modules.auth.schemas import CurrentUser
from app.modules.rag.grounder import decide
from app.modules.rag.retriever import retrieve
from app.modules.rag.schemas import HitOut, RagQueryRequest, RagQueryResponse
from app.config import get_settings

router = APIRouter()
_settings = get_settings()


@router.post(
    "/query",
    response_model=dict,
    summary="Retrieve grounded citations for a query (debug)",
    description=(
        "Standalone retrieval endpoint — returns the citation_keys that "
        "would be sent to the AI gateway, plus grounding decision + suggestions. "
        "Used for tuning thresholds and debugging.\n\n"
        "**Required role:** instructor or admin."
    ),
    operation_id="rag_query",
)
async def rag_query(
    body: RagQueryRequest,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if current_user.role not in ("admin", "instructor"):
        raise HTTPException(status_code=403, detail="Admin or instructor required")
    cfg = {
        "top_k": body.top_k or _settings.RAG_TOP_K,
        "mmr_lambda": _settings.RAG_MMR_LAMBDA,
        "include_threshold": _settings.RAG_INCLUDE_THRESHOLD,
        "soft_include_threshold": _settings.RAG_SOFT_INCLUDE_THRESHOLD,
        "suggest_threshold": _settings.RAG_SUGGEST_THRESHOLD,
        "max_chunks": _settings.RAG_MAX_CHUNKS,
    }
    hits, _latency = await retrieve(db, body.query, body.aircraft_id, cfg)
    decision = decide(hits, cfg)

    hits_out = [
        HitOut(
            citation_key=h.citation_keys[0] if h.citation_keys else "",
            score=h.score,
            included=h.included,
            mmr_rank=h.mmr_rank,
        )
        for h in hits
    ]
    suggestions_out = [
        HitOut(
            citation_key=s["citation_key"],
            score=s["score"],
            included=False,
            mmr_rank=-1,
        )
        for s in decision["suggestions"]
    ]
    return {"data": RagQueryResponse(
        grounded=decision["grounded"],
        citation_keys=decision["citation_keys"],
        hits=hits_out,
        suggestions=suggestions_out,
    ).model_dump()}
```

- [ ] **Step 2: Wire router into `app/main.py`**

Edit `app/main.py` — add to imports (around line 32):

```python
from app.modules.rag.router import router as rag_router
```

Inside `create_app()`, add the include alongside other routers:

```python
    app.include_router(rag_router, prefix=f"{prefix}/rag", tags=["rag"])
```

- [ ] **Step 3: Smoke test**

Run: `uvicorn app.main:app --port 8001 &` then `sleep 2 && curl -s http://localhost:8001/api/v1/openapi.json | python -c "import json, sys; ops=[r['operationId'] for p in json.load(sys.stdin)['paths'].values() for r in p.values() if isinstance(r, dict)]; print('rag_query' in ops)"; kill %1`
Expected: `True`

- [ ] **Step 4: Commit**

```bash
git add app/modules/rag/router.py app/main.py
git commit -m "feat(rag): POST /rag/query debug endpoint"
```

---

# Phase D — Chat refactor

Goal: `/ai-assistant/message` becomes the real RAG-backed chat with persistence + query rewriting.

## Task D1: Query rewriter

**Files:**
- Modify: `app/modules/rag/rewriter.py`
- Create: `tests/unit/test_rag_rewriter.py`

- [ ] **Step 1: Write failing tests**

```python
import pytest
from unittest.mock import AsyncMock, patch

from app.modules.rag.rewriter import rewrite, _has_anaphora, _needs_rewrite


def test_needs_rewrite_skips_first_turn():
    assert _needs_rewrite("anything", turn=0) is False


def test_needs_rewrite_skips_long_no_anaphora():
    msg = "what is the standard procedure for engine start in cold weather operations"
    assert _needs_rewrite(msg, turn=2) is False


def test_needs_rewrite_proceeds_on_anaphora():
    assert _needs_rewrite("and what about it?", turn=2) is True


def test_has_anaphora_detects_pronouns():
    assert _has_anaphora("what about it?") is True
    assert _has_anaphora("describe the engine start procedure") is False


async def test_rewrite_returns_msg_on_first_turn():
    out = await rewrite("hello", history=[], turn=0)
    assert out == "hello"


async def test_rewrite_calls_llm_on_followup_with_anaphora():
    fake = {"response": "rewritten engine start procedure", "provider": "g", "model": "x", "cached": False, "usage": {}, "citations": [], "request_id": "r"}
    with patch("app.modules.rag.rewriter.AsyncSessionLocal"), \
         patch("app.modules.rag.rewriter.AIService") as MockAI:
        MockAI.return_value.complete = AsyncMock(return_value=fake)
        out = await rewrite("and what about it?", history=[{"role": "user", "content": "engine start"}], turn=2)
        assert out == "rewritten engine start procedure"


async def test_rewrite_falls_back_on_provider_error():
    with patch("app.modules.rag.rewriter.AsyncSessionLocal"), \
         patch("app.modules.rag.rewriter.AIService") as MockAI:
        MockAI.return_value.complete = AsyncMock(side_effect=RuntimeError("provider down"))
        history = [{"role": "user", "content": "engine start"}, {"role": "assistant", "content": "see FCOM 3.2.1"}]
        out = await rewrite("and what about it?", history=history, turn=2)
        # Fallback: concat last user msg + current
        assert "engine start" in out
        assert "and what about it?" in out
```

- [ ] **Step 2: Run — expect FAIL** (NotImplementedError + missing helpers)

Run: `pytest tests/unit/test_rag_rewriter.py -v`
Expected: failures across the board.

- [ ] **Step 3: Implement `app/modules/rag/rewriter.py`**

Replace file content:

```python
"""Conversational query rewriting. See spec §11."""

import asyncio

import structlog

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.modules.ai.providers.base import CompletionRequest as ProviderCompletionReq, Message
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
    if len(text.split()) >= 15 and not _has_anaphora(text):
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
```

- [ ] **Step 4: Run — expect PASS**

Run: `pytest tests/unit/test_rag_rewriter.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add app/modules/rag/rewriter.py tests/unit/test_rag_rewriter.py
git commit -m "feat(rag): conversational query rewriter with skip-on-heuristic + fallback"
```

---

## Task D2: `RAGService.answer()` orchestration

**Files:**
- Modify: `app/modules/rag/service.py`

- [ ] **Step 1: Implement the full orchestration**

Replace `app/modules/rag/service.py`:

```python
"""RAG orchestration: rewrite -> retrieve -> ground -> AIService.complete -> persist."""

import time
import uuid
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
        if not aircraft_id:
            return "general aviation"
        from app.modules.content.models import Aircraft
        result = await self.db.execute(select(Aircraft).where(Aircraft.id == aircraft_id))
        a = result.scalar_one_or_none()
        return a.display_name if a else "general aviation"

    async def _resolve_sources(self, citation_keys: list[str], scores_by_key: dict[str, float]) -> list[dict]:
        if not citation_keys:
            return []
        result = await self.db.execute(
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
        sys_prompt = _system_prompt(getattr(user, "role", "trainee"), aircraft_label, soft=(decision["grounded"] == "soft"))
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
```

- [ ] **Step 2: Smoke check — module imports cleanly**

Run: `python -c "from app.modules.rag.service import RAGService; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add app/modules/rag/service.py
git commit -m "feat(rag): RAGService.answer orchestration with telemetry"
```

---

## Task D3: Refactor `/ai-assistant/message` route

**Files:**
- Modify: `app/modules/ai_assistant/router.py`

- [ ] **Step 1: Replace `app/modules/ai_assistant/router.py` with the RAG-backed implementation**

```python
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Query
from fastapi.routing import APIRouter
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.ai_assistant.models import ChatMessage, ChatSession
from app.modules.auth.deps import get_current_user
from app.modules.auth.schemas import CurrentUser
from app.modules.rag.schemas import (
    AssistantMessage, ChatTurnResponse, CreateSessionRequest, SessionOut,
    SourceOut, UserMessage,
)
from app.modules.rag.service import RAGService

router = APIRouter()


class SendMessageRequest(BaseModel):
    content: str
    session_id: uuid.UUID | None = None


@router.post(
    "/sessions",
    response_model=dict,
    summary="Create a new chat session",
    description=(
        "Create a chat session with optional `aircraft_id` to scope retrieval. "
        "Without `aircraft_id`, only general aviation content is searched."
    ),
    operation_id="ai_assistant_create_session",
)
async def create_session(
    body: CreateSessionRequest,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    sess = ChatSession(
        user_id=uuid.UUID(str(current_user.id)),
        aircraft_id=body.aircraft_id,
        title=body.title,
    )
    db.add(sess)
    await db.commit()
    await db.refresh(sess)
    return {"data": SessionOut(
        id=sess.id, aircraft_id=sess.aircraft_id, title=sess.title, status=sess.status,
        created_at=sess.created_at, last_activity_at=sess.last_activity_at,
    ).model_dump(mode="json")}


@router.post(
    "/message",
    response_model=dict,
    summary="Send a message in a chat session (RAG-backed)",
    description=(
        "Sends a user message. The RAG layer retrieves citations from approved content "
        "and grounds the answer. Returns userMessage + assistantMessage with sources/suggestions.\n\n"
        "If `session_id` is omitted, a new session is created with no aircraft scope.\n\n"
        "Add `?debug=true` (instructor/admin only) for retrieval tracing."
    ),
    responses={
        401: {"description": "Not authenticated"},
        404: {"description": "Session not found"},
        429: {"description": "AI rate limit exceeded"},
        502: {"description": "All LLM providers unreachable"},
    },
    operation_id="ai_assistant_send_message",
)
async def send_message(
    body: SendMessageRequest,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    debug: bool = Query(False, description="Include retrieval debug info (instructor/admin only)"),
):
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="content is required")

    session_id = body.session_id
    if session_id is None:
        sess = ChatSession(user_id=uuid.UUID(str(current_user.id)))
        db.add(sess)
        await db.flush()
        session_id = sess.id

    svc = RAGService(db)
    result = await svc.answer(body.content.strip(), session_id, current_user)
    user_msg, asst_msg = result["user_message"], result["assistant_message"]
    sources = [SourceOut(**s) for s in result["sources"]]
    suggestions = [SourceOut(**s) for s in result["suggestions"]]

    response = {
        "data": ChatTurnResponse(
            userMessage=UserMessage(
                id=str(user_msg.id), role="user", content=user_msg.content,
                timestamp=user_msg.created_at,
            ),
            assistantMessage=AssistantMessage(
                id=str(asst_msg.id), role="assistant", content=asst_msg.content,
                timestamp=asst_msg.created_at,
                grounded=asst_msg.grounded,
                sources=sources, suggestions=suggestions,
            ),
        ).model_dump(mode="json")
    }

    if debug and current_user.role in ("admin", "instructor"):
        response["debug"] = {
            "original_query": body.content.strip(),
            "rewritten_query": result["rewritten_query"],
            "skipped_rewrite": result["skipped_rewrite"],
            "retrieval_hits": [
                {"citation_key": h.citation_keys[0] if h.citation_keys else "", "score": h.score, "included": h.included}
                for h in result["hits"]
            ],
        }
    return response


@router.get(
    "/history",
    response_model=dict,
    summary="Get chat history for a session",
    description="Returns ordered messages for a session_id (or empty if no session_id given).",
    operation_id="ai_assistant_history",
)
async def get_history(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    session_id: uuid.UUID | None = Query(None),
):
    if session_id is None:
        return {"data": []}
    result = await db.execute(
        select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at)
    )
    return {"data": [
        {
            "id": str(m.id),
            "role": m.role,
            "content": m.content,
            "citations": m.citations or [],
            "grounded": m.grounded,
            "timestamp": m.created_at.isoformat(),
        }
        for m in result.scalars().all()
    ]}


@router.delete(
    "/history",
    response_model=dict,
    summary="Close a chat session",
    description="Marks the session as closed. Messages remain for audit.",
    operation_id="ai_assistant_clear_history",
)
async def close_session(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    session_id: uuid.UUID = Query(...),
):
    result = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
    sess = result.scalar_one_or_none()
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")
    sess.status = "closed"
    sess.closed_at = datetime.now(UTC)
    await db.commit()
    return {"data": {"message": "Session closed", "session_id": str(session_id)}}
```

- [ ] **Step 2: Smoke check**

Run: `uvicorn app.main:app --port 8001 &` then `sleep 2 && curl -s http://localhost:8001/api/v1/openapi.json | python -c "import json, sys; ops={r['operationId'] for p in json.load(sys.stdin)['paths'].values() for r in p.values() if isinstance(r, dict)}; print(all(o in ops for o in ['ai_assistant_create_session','ai_assistant_send_message','ai_assistant_history','ai_assistant_clear_history']))"; kill %1`
Expected: `True`

- [ ] **Step 3: Commit**

```bash
git add app/modules/ai_assistant/router.py
git commit -m "feat(ai_assistant): RAG-backed /message + sessions endpoints + persistence"
```

---

## Task D4: End-to-end integration test for `/ai-assistant/message`

**Files:**
- Create: `tests/integration/test_ai_assistant_message.py`

- [ ] **Step 1: Write the test**

```python
import asyncio
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.modules.rag.tasks import _embed_source_async
from tests.fixtures.synthetic_fcom import seed_synthetic_fcom


async def _ingest(db_session):
    source = await seed_synthetic_fcom(db_session)
    await db_session.commit()
    fake = {"embeddings": [[0.1] * 1536] * 50, "model": "x", "usage": {"total_tokens": 1}}
    with patch("app.modules.rag.embedder.AIService") as MockAI:
        MockAI.return_value.embed = AsyncMock(return_value=fake)
        await _embed_source_async(str(source.id))


async def _auth_headers():
    # Stub: project test conftest would normally provide a JWT helper. We override the dep instead.
    return {}


async def test_send_message_returns_grounded_answer(client, db_session):
    await _ingest(db_session)

    fake_complete = {
        "response": "Per [SYN-FCOM-3.1], engine start procedure...",
        "provider": "gemini", "model": "gemini-1.5-pro",
        "cached": False, "usage": {"prompt_tokens": 10, "completion_tokens": 20, "cost_usd": 0.0001},
        "citations": ["SYN-FCOM-3.1"], "request_id": "req_x",
    }
    fake_embed = {"embeddings": [[0.1] * 1536], "model": "x", "usage": {"total_tokens": 1}}

    with patch("app.modules.rag.embedder.AIService") as MockEmb, \
         patch("app.modules.rag.service.AIService") as MockComplete, \
         patch("app.modules.auth.deps.get_current_user") as mock_user:
        MockEmb.return_value.embed = AsyncMock(return_value=fake_embed)
        MockComplete.return_value.complete = AsyncMock(return_value=fake_complete)
        from app.modules.auth.schemas import CurrentUser
        mock_user.return_value = CurrentUser(id=str(uuid.uuid4()), email="t@example.com", role="trainee")

        resp = await client.post("/api/v1/ai-assistant/message", json={"content": "engine start procedure?"})
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["userMessage"]["content"] == "engine start procedure?"
        assert body["assistantMessage"]["grounded"] in ("strong", "soft")
        assert body["assistantMessage"]["content"].startswith("Per [SYN-FCOM-3.1]")
        assert any(s["citation_key"] == "SYN-FCOM-3.1" for s in body["assistantMessage"]["sources"])
```

- [ ] **Step 2: Run — expect PASS** (assuming Postgres + pgvector test DB is set up per conftest)

Run: `pytest tests/integration/test_ai_assistant_message.py -v`
Expected: 1 passed.

If your test DB doesn't have pgvector enabled, run this first:
```bash
psql "postgresql://aegis:aegis@localhost:5432/aegis_test" -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_ai_assistant_message.py
git commit -m "test(ai_assistant): e2e RAG-backed message flow"
```

---

## Task D5: Auto-close idle sessions Celery beat schedule

**Files:**
- Modify: `app/modules/rag/tasks.py`
- Modify: `app/worker.py`

- [ ] **Step 1: Implement `auto_close_idle_sessions`**

In `app/modules/rag/tasks.py`, add helper + replace stub:

```python
async def _auto_close_idle_sessions_async() -> int:
    from datetime import UTC, datetime, timedelta
    cutoff = datetime.now(UTC) - timedelta(days=_settings.CHAT_SESSION_AUTO_CLOSE_DAYS)
    async with AsyncSessionLocal() as db:
        from app.modules.ai_assistant.models import ChatSession
        from sqlalchemy import update
        result = await db.execute(
            update(ChatSession)
            .where(ChatSession.status == "active", ChatSession.last_activity_at < cutoff)
            .values(status="closed", closed_at=datetime.now(UTC))
        )
        await db.commit()
        return result.rowcount or 0


@celery_app.task(name="rag.auto_close_idle_sessions")
def auto_close_idle_sessions() -> int:
    return asyncio.run(_auto_close_idle_sessions_async())
```

- [ ] **Step 2: Add beat schedule to `app/worker.py`**

After the existing `celery_app.conf.update(...)` block, add:

```python
celery_app.conf.beat_schedule = {
    "auto-close-idle-sessions-daily": {
        "task": "rag.auto_close_idle_sessions",
        "schedule": 24 * 60 * 60,  # every 24h
    },
}
```

- [ ] **Step 3: Manual smoke test**

Run: `python -c "from app.modules.rag.tasks import auto_close_idle_sessions; print(auto_close_idle_sessions.run())"`
Expected: prints integer (probably `0` on fresh DB).

- [ ] **Step 4: Commit**

```bash
git add app/modules/rag/tasks.py app/worker.py
git commit -m "feat(rag): auto-close idle chat sessions via Celery beat"
```

---

# Phase E — Polish

## Task E1: Fix N+1 in `_resolve_citations`

**Files:**
- Modify: `app/modules/ai/service.py`

- [ ] **Step 1: Replace `_resolve_citations` with a single-query version**

Edit `app/modules/ai/service.py` — replace the body of `_resolve_citations`:

```python
    async def _resolve_citations(self, citation_keys: list[str]) -> str:
        if not citation_keys:
            return ""
        from sqlalchemy import select
        from app.modules.content.models import ContentReference, ContentSection

        result = await self.db.execute(
            select(ContentReference, ContentSection)
            .join(ContentSection, ContentSection.id == ContentReference.section_id)
            .where(ContentReference.citation_key.in_(citation_keys))
        )
        # Preserve input order
        by_key = {ref.citation_key: sec for ref, sec in result}
        parts = []
        for key in citation_keys:
            sec = by_key.get(key)
            if sec is None:
                from app.core.exceptions import CitationNotFound
                raise CitationNotFound(key)
            if sec.content_markdown:
                parts.append(f"[{key}] {sec.content_markdown}")
        return "\n\n".join(parts)
```

- [ ] **Step 2: Run all tests to verify nothing broke**

Run: `pytest tests/ -v --timeout=30`
Expected: all green (existing AI gateway tests, new RAG tests).

- [ ] **Step 3: Commit**

```bash
git add app/modules/ai/service.py
git commit -m "perf(ai): replace N+1 in _resolve_citations with single IN query"
```

---

## Task E2: Module README

**Files:**
- Create: `app/modules/rag/README.md`

- [ ] **Step 1: Write the README**

```markdown
# RAG Module

Retrieval-Augmented Generation for the Trainee + Instructor AI Assistants.

## Contract

- **Input:** user query + optional aircraft_id (per chat session)
- **Output:** answer text + grounded citation_keys + score-ranked source provenance
- **Boundary:** RAG produces citation_keys; the AI gateway (`app/modules/ai`) resolves them and runs the LLM.

## Files

| File | Responsibility |
|---|---|
| `models.py` | `ContentChunk` (pgvector) + `RetrievalLog` |
| `schemas.py` | Pydantic request/response models |
| `chunker.py` | 3-rule hybrid (structural primary / recursive sub-split / sibling-merge) |
| `embedder.py` | `embed_and_validate()` — wraps `AIService.embed()` + dim check |
| `retriever.py` | pgvector cosine search + MMR diversification |
| `grounder.py` | `decide()` — strong / soft / refused thresholds |
| `rewriter.py` | Conversational query rewriting (skip-on-heuristic + LLM rewrite + fallback) |
| `service.py` | `RAGService.answer()` orchestration |
| `router.py` | `POST /rag/query` debug endpoint |
| `tasks.py` | Celery: embed_source, reembed_source, reembed_all_dim_mismatch, auto_close_idle_sessions |
| `prompts.py` | System prompt + refusal templates |

## Configuration

All knobs live in `app/config.Settings` under `RAG_*` and `EMBEDDING_*`. See spec §16 for defaults.

## Ingestion

Triggered automatically when `ContentService.approve_source()` is called. Embedding happens via Celery (`rag.embed_source`). Re-embed individual sources via `POST /content/sources/{id}/reembed` (admin). Bulk re-embed on dim mismatch via `rag.reembed_all_dim_mismatch`.

## Telemetry

Every retrieval writes to `retrieval_logs`, joined to `ai_requests` via `request_id`.

## Tests

- `tests/unit/test_rag_*.py` — chunker, grounder, rewriter, mmr, embedder
- `tests/integration/test_rag_ingestion.py` — Celery + supersedence
- `tests/integration/test_rag_retrieval.py` — pgvector search
- `tests/integration/test_ai_assistant_message.py` — e2e chat
- `tests/fixtures/synthetic_fcom.py` — synthetic FCOM fixture (real DB rows, no parsers needed)
```

- [ ] **Step 2: Commit**

```bash
git add app/modules/rag/README.md
git commit -m "docs(rag): module README explaining contract + file layout"
```

---

## Task E3: Coverage check + final smoke

**Files:** none

- [ ] **Step 1: Run full test suite with coverage**

Run: `pytest tests/ -v --timeout=60`
Expected: all green, coverage gate `--cov-fail-under=80` passes.

If coverage is below 80%, look at the term-missing report and add focused tests for uncovered branches in `service.py` (refusal path is the most likely gap).

- [ ] **Step 2: Manual end-to-end smoke against full stack**

```bash
# 1. Start the stack
docker-compose up -d postgres redis meilisearch

# 2. Ensure pgvector in the dev DB
psql "$DATABASE_URL" -c "CREATE EXTENSION IF NOT EXISTS vector;"

# 3. Run migrations
alembic upgrade head

# 4. Start API
uvicorn app.main:app --reload --port 8000 &

# 5. Start Celery worker (separate terminal)
celery -A app.worker.celery_app worker --loglevel=info &

# 6. Get an auth token (via existing /auth/login endpoint)

# 7. Upload a test source, approve it, send a message
TOKEN=...
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -F "file=@tests/fixtures/sample.pdf" -F "source_type=fcom" \
  -F "title=Test FCOM" -F "version=Rev 1" \
  http://localhost:8000/api/v1/content/sources

curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/content/sources/<id>/approve

# (wait ~10s for Celery to finish)

curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"content": "engine start procedure?"}' \
  http://localhost:8000/api/v1/ai-assistant/message
```

Expected: response JSON with `assistantMessage.grounded` set and `sources[]` populated.

- [ ] **Step 3: Push branch (optional)**

```bash
git push -u origin feat/rag-foundation
```

(Don't open the PR until you've coordinated with Sachin per the spec §19 dependencies.)

- [ ] **Step 4: Final commit (if README/coverage tweaks happened)**

```bash
git status
# if anything's untracked, commit it
git commit -am "chore(rag): final polish + coverage tweaks" || echo "nothing to commit"
```

---

# Self-review checklist (run after the plan executes)

- [ ] All 5 phases complete
- [ ] `alembic upgrade head` produces clean schema with pgvector
- [ ] `pytest --cov` ≥ 80%
- [ ] `POST /api/v1/ai-assistant/message` returns grounded + cited responses end-to-end
- [ ] `POST /api/v1/rag/query` debug endpoint works for instructors
- [ ] Refusal path returns top-3 suggestions
- [ ] Multi-turn follow-ups trigger query rewriting (visible in `?debug=true`)
- [ ] `retrieval_logs` rows accumulate per call
- [ ] `content_sources.embedding_status` flips to `succeeded` after approval
- [ ] N+1 fix in `_resolve_citations` lands

---

## Coordination after this branch lands

Per spec §19, before merging to `main`:

1. Sachin: walk through the 5 migrations + new `embedding_status` column
2. Sachin: confirm chat persistence in `ai_assistant/models.py` is OK with him
3. Sachin: real FCOM/QRH parsers — provide ETA so we can swap synthetic fixtures
4. Ira: PII filter audit before Phase 1 launch (current regex doesn't catch names/IAF service IDs)
5. Harish: walk through response shape for chat UI integration (spec §12 / Task D3 router)
