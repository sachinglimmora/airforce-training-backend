# RAG Foundation — Design Spec

**Owner:** Shreyansh Mishra
**Status:** Approved (brainstorm 2026-04-27), pending implementation
**Module path:** `app/modules/rag/`
**Branch:** `feat/rag-foundation`

---

## 1. Goal

Build the Retrieval-Augmented Generation foundation that turns approved aerospace training content (FCOM/QRH/AMM/SOP/syllabus) into a query-answerable, citation-enforced knowledge layer for the Trainee and Instructor AI Assistants.

This spec covers the **backend RAG pipeline only**. It does not redesign or replace anything Sachin has already built — it slots into the seam he already opened (`citation_key`-driven AI gateway).

## 2. Non-goals (explicit out of scope)

- Real FCOM/QRH/AMM/SOP parsers — Sachin (Excel R66-67). We build against `GenericParser` stub + synthetic fixtures.
- PII filter hardening (names, IAF service IDs, ranks) — Ira (R54). Current regex filter is consumed as-is.
- Frontend chat UI / source-citation display — Harish.
- Cross-encoder reranking, HyDE, multi-query expansion — Phase 2.
- Air-gapped / OwnLLM swap — Phase 2+.
- Trainee AI Assistant beyond the chat-with-RAG path (adaptive quizzes, lesson plans, etc. are separate specs).

## 3. Architectural insight

Sachin's `POST /api/v1/ai/complete` accepts `context_citations: list[str]` (citation_keys like `B737-FCOM-3.2.1`), resolves them internally to section markdown, runs PII filter, calls Gemini→OpenAI with cache + fallback, logs to `ai_requests`. **The gateway is citation-key driven, not vector-driven.**

Therefore RAG's job is:

```
query → (rewrite) → embed → vector_search → MMR → threshold → ranked citation_keys → AIService.complete(context_citations=[...])
```

We never call LLMs ourselves. We never store vectors elsewhere. We produce citation_keys.

## 4. Module layout

```
app/modules/rag/
├── __init__.py
├── models.py        # ContentChunk, ChatSession, ChatMessage, RetrievalLog
├── schemas.py       # Pydantic request/response models
├── router.py        # POST /rag/query (debug/standalone)
├── service.py       # RAGService.answer(query, session_id) — orchestration
├── chunker.py       # Section tree → ContentChunk records (3-rule hybrid)
├── embedder.py      # Wraps AIService.embed() + dim validation
├── retriever.py     # Vector search + MMR + threshold filter
├── grounder.py      # Decide: strong | soft | refused; build suggestions
├── rewriter.py      # Conversational query rewriting
├── tasks.py         # Celery: embed_source, reembed_source, reembed_all_dim_mismatch
└── prompts.py       # System prompt + refusal templates
```

`app/modules/ai_assistant/router.py` is refactored to call `RAGService.answer()` instead of `AIService.complete()` directly. Chat persistence tables live in `app/modules/ai_assistant/models.py` (we add them since Sachin's stub doesn't persist).

## 5. Data model

### 5.1 New tables

**`content_chunks`** — embedded chunk store

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID PK` | |
| `source_id` | `UUID FK content_sources.id` | indexed |
| `section_id` | `UUID FK content_sections.id` | indexed |
| `citation_keys` | `JSONB list[str]` | usually one; multiple when sibling-merged |
| `content` | `TEXT` | the chunk text passed to embedder |
| `token_count` | `INT` | tiktoken-counted |
| `ordinal` | `INT` | order within section (for sub-split chunks) |
| `embedding` | `vector(1536)` | pgvector |
| `embedding_model` | `VARCHAR(64)` | provenance |
| `embedding_dim` | `INT` | provenance, validated equals settings.EMBEDDING_DIM |
| `superseded_by_source_id` | `UUID FK content_sources.id NULL` | for version supersedence |
| `created_at` | `TIMESTAMPTZ` | |

**Indexes:**
- `ivfflat` on `embedding vector_cosine_ops` with `lists=100`
- B-tree on `superseded_by_source_id`
- B-tree on `(source_id, ordinal)`

**`chat_sessions`** — conversation containers

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID PK` | |
| `user_id` | `UUID FK users.id` | indexed |
| `aircraft_id` | `UUID FK aircraft.id NULL` | per-session aircraft scope |
| `title` | `VARCHAR(255) NULL` | first user message truncated |
| `status` | `ENUM('active','closed')` | |
| `created_at` | `TIMESTAMPTZ` | |
| `last_activity_at` | `TIMESTAMPTZ` | indexed for auto-close sweep |
| `closed_at` | `TIMESTAMPTZ NULL` | |

**`chat_messages`** — individual messages

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID PK` | |
| `session_id` | `UUID FK chat_sessions.id` | indexed |
| `role` | `ENUM('user','assistant')` | |
| `content` | `TEXT` | |
| `citations` | `JSONB list[str]` | citation_keys used for this message |
| `grounded` | `ENUM('strong','soft','refused')` | NULL for user messages |
| `created_at` | `TIMESTAMPTZ` | |

**`retrieval_logs`** — telemetry for quality measurement

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID PK` | |
| `request_id` | `VARCHAR(36)` | joins to `ai_requests.id` |
| `session_id` | `UUID FK chat_sessions.id NULL` | |
| `user_id` | `UUID NULL` | |
| `original_query` | `TEXT` | |
| `rewritten_query` | `TEXT NULL` | |
| `query_skipped_rewrite` | `BOOLEAN` | |
| `aircraft_scope_id` | `UUID NULL` | |
| `top_k` | `INT` | |
| `hits` | `JSONB` | `[{citation_key, score, included, mmr_rank}]` |
| `grounded` | `ENUM('strong','soft','refused')` | |
| `latency_ms` | `JSONB` | `{rewrite, embed, vector_search, mmr, llm}` |
| `created_at` | `TIMESTAMPTZ` | |

### 5.2 Column additions to existing tables

- `content_sources.embedding_status` — `ENUM('pending','succeeded','failed') DEFAULT 'pending'` — surfaces ingestion failures to admin without blocking approval.

### 5.3 Alembic migrations (in order)

1. `xxx_enable_pgvector_extension.py` — `CREATE EXTENSION IF NOT EXISTS vector`
2. `xxx_create_content_chunks.py` — table + ivfflat index
3. `xxx_create_chat_sessions_and_messages.py`
4. `xxx_create_retrieval_logs.py`
5. `xxx_add_embedding_status_to_content_sources.py`

## 6. Ingestion pipeline

**Trigger:** `ContentService.approve_source()` enqueues `tasks.embed_source.delay(source_id)`.

**Worker steps:**

1. Load source + section tree (eager-load `sections.children`).
2. For each leaf section, apply chunking (§7).
3. Apply sibling-merge pass on tiny adjacent siblings.
4. Batch chunk texts (50 per batch) → call `embedder.embed_and_validate(texts)`.
5. `INSERT INTO content_chunks` in a transaction. On failure: `embedding_status='failed'`, log, raise.
6. Find any prior `approved` source with same `(source_type, aircraft_id, title)`. If found:
   - Update old `content_sources.status='archived'`
   - Update old `content_chunks.superseded_by_source_id = new_source_id`
7. Set `content_sources.embedding_status='succeeded'`.

**Idempotency:**
- Re-running on a source with existing chunks → no-op + log warning.
- `POST /content/sources/{id}/reembed` (admin-only) — deletes existing chunks for that `source_id`, re-runs the worker. For chunker improvements or model swaps.

**Bulk re-embed:**
- `tasks.reembed_all_dim_mismatch` — finds chunks where `embedding_dim != settings.EMBEDDING_DIM`, re-embeds in batches. Triggered manually after model config change.

**Failure retry:** Celery `autoretry_for=(Exception,)`, `retry_backoff=True`, `max_retries=3`. Persistent failure → `embedding_status='failed'`.

## 7. Chunking strategy

Three rules, applied in order while walking the section tree:

1. **PRIMARY** — If `len(tokens(section.content_markdown)) ≤ 800`, use the entire section as one chunk. `citation_keys = [section.reference.citation_key]`.
2. **SUB-SPLIT** — If a section's content_markdown > 800 tokens, recursive char splitter (separators: `\n\n`, `\n`, `. `, ` `) with 100-token overlap. Each sub-chunk inherits the parent section's `citation_key`. `ordinal` increments.
3. **MERGE-SMALL** — After primary/sub-split, if a leaf section produced a chunk < 100 tokens AND has an adjacent sibling chunk also < 100 tokens, merge into one chunk with `citation_keys = [a, b]`. Optional sweep, run last.

Tokenizer: `tiktoken` with `cl100k_base` encoding (matches OpenAI embedding tokenization).

Headings (`section.section_number` + `section.title`) prepended to each chunk's `content` for context: `## 3.2.1 Engine Start\n\n{content_markdown}`.

## 8. Embedding

- All embedding goes through `embedder.embed_and_validate(texts)` which wraps `AIService.embed()`.
- `AIService.embed()` already prefers Gemini if `GEMINI_API_KEY` set, else OpenAI.
- Validation: `len(vec) == settings.EMBEDDING_DIM` for every returned vector. Mismatch raises `EmbedDimensionMismatch`.
- Provenance written per chunk: `embedding_model`, `embedding_dim`.
- Startup health check (`@app.on_event("startup")`) embeds one test string and asserts dim — fails the deploy on misconfiguration.

**Config:**
```python
EMBEDDING_DIM: int = 1536
EMBEDDING_MODEL_HINT: str = "text-embedding-3-small"  # info only; gateway picks
```

## 9. Retrieval

```python
async def retrieve(query: str, aircraft_id: UUID | None, top_k: int = 10) -> list[Hit]:
    qvec = await embedder.embed_and_validate([query])
    candidates = await pgvector_search(qvec[0], top_k, aircraft_id)
    diversified = mmr(candidates, lambda_=0.5)
    return diversified  # raw — grounder applies thresholds
```

**Vector search SQL:**
```sql
SELECT c.*, s.aircraft_id,
       1 - (c.embedding <=> :qvec) AS cosine_score
FROM content_chunks c
JOIN content_sources s ON s.id = c.source_id
WHERE c.superseded_by_source_id IS NULL
  AND s.status = 'approved'
  AND (s.aircraft_id = :aircraft_id OR s.aircraft_id IS NULL)
ORDER BY c.embedding <=> :qvec
LIMIT :top_k;
```

**MMR (Maximum Marginal Relevance):** standard greedy implementation, λ=0.5. Re-orders the top_k candidates to favor diversity. ~30 LoC.

**Aircraft scoping:** `chat_sessions.aircraft_id` provides the scope. Always include `aircraft_id IS NULL` (general aviation content). If session has no aircraft set, search general only.

## 10. Grounding policy

```python
def decide(hits: list[Hit], cfg: RetrievalConfig) -> Decision:
    above_high = [h for h in hits if h.score >= cfg.include_threshold]      # 0.65
    above_soft = [h for h in hits if h.score >= cfg.soft_include_threshold] # 0.60
    above_low  = [h for h in hits if h.score >= cfg.suggest_threshold]      # 0.50

    if above_high:
        return Strong(cite=above_high[:cfg.max_chunks])
    if above_soft:
        return Soft(cite=[above_soft[0]])  # rescue top-1
    return Refused(suggestions=above_low[:3])
```

**Config:**
```python
RETRIEVAL_CONFIG = {
    "top_k": 10,
    "max_chunks": 5,
    "include_threshold": 0.65,
    "soft_include_threshold": 0.60,
    "suggest_threshold": 0.50,
    "mmr_lambda": 0.5,
    "use_reranker": False,
}
```

All values config-driven; tune from `retrieval_logs` after Phase 1 ships.

## 11. Query rewriting

Before retrieval, on follow-up turns:

```python
async def rewrite(msg: str, history: list[Message], turn: int) -> str:
    if turn == 0:
        return msg
    if len(msg.split()) >= 15 and not _has_anaphora(msg):
        return msg  # heuristic skip
    try:
        return await _llm_rewrite(msg, history[-6:], cache=True)
    except (TimeoutError, ProviderError):
        return _fallback_concat(msg, history)
```

- Model: `gemini-1.5-flash` (cheap, fast)
- Temperature: 0.0 (deterministic → caches well)
- Max tokens: 100
- Timeout: 5s
- Cache: same `ai_cache:` Redis prefix Sachin uses
- **Original query** sent to LLM for the answer; **rewritten query** used only for retrieval embedding
- Anaphora set: `{it, that, this, they, those, same, again, also, too, either}`
- Fallback chain: rewriter fails → `concat(last_user_msg, current_msg)` → `current_msg` alone

**Conservative prompt** (do-not-invent rule baked in) — see `app/modules/rag/prompts.py:REWRITER_PROMPT`.

## 12. Response shape — `/api/v1/ai-assistant/message`

Refactored route, full contract for Harish:

```json
{
  "data": {
    "userMessage": {
      "id": "msg_<uuid>",
      "role": "user",
      "content": "engine start in cold weather?",
      "timestamp": "2026-04-27T10:30:00Z"
    },
    "assistantMessage": {
      "id": "msg_<uuid>",
      "role": "assistant",
      "content": "Per FCOM §3.2.1, ...",
      "timestamp": "2026-04-27T10:30:02Z",
      "grounded": "strong",          // strong | soft | refused
      "sources": [
        {
          "citation_key": "SU30-FCOM-3.2.1",
          "display_label": "FCOM Vol 2, Ch 3, §3.2.1 — Engine Start",
          "page_number": 127,
          "score": 0.87,
          "source_type": "fcom",
          "source_version": "Rev 42",
          "snippet": "...the AL-31FP requires engine warm-up..."
        }
      ],
      "suggestions": []              // populated only when grounded=refused
    }
  },
  "debug": {                         // only when ?debug=true AND role in (instructor,admin)
    "original_query": "...",
    "rewritten_query": "...",
    "skipped_rewrite": false,
    "retrieval_hits": [{"key": "...", "score": 0.87, "included": true}]
  }
}
```

Refusal example:
```json
"assistantMessage": {
  "content": "I don't have approved source material that answers this directly. Closest related references are listed below.",
  "grounded": "refused",
  "sources": [],
  "suggestions": [/* same shape as sources, top-3 below threshold */]
}
```

## 13. System prompt + refusal template

**Trainee assistant system prompt skeleton** (`prompts.py`):
```
You are an aerospace training assistant for the Indian Air Force.
Audience: {role} ({aircraft_context} program).

RULES:
1. Answer ONLY using the reference material provided in this conversation.
2. If the reference is insufficient, say so explicitly. Do NOT speculate.
3. Cite specific sections in your answer using the citation_key in [brackets].
4. Use **bold** for safety-critical values, limits, and warnings.
5. Be concise. Trainees are practicing, not reading textbooks.
{role_addendum}
```

**Role addendums** (stub for Ira to refine per R50):
- Trainee: *"Explain at training level. Avoid deep maintenance theory unless asked."*
- Instructor: *"Provide deeper technical detail. Include cross-references to related procedures."*

**Soft-grounded prompt prefix** (when `grounded='soft'`):
```
Note: The reference material below is the closest available match but may not 
be a perfect fit for the question. Caveat your answer accordingly.
```

**Refusal user-facing template:**
```
I don't have approved source material that answers this question directly.

Closest related references:
  • [SU30-FCOM-3.2.1] FCOM Vol 2, Ch 3 — Engine Start (relevance: moderate)
  • [SU30-QRH-EMG-04] QRH Emergency 04 — Engine Failure (relevance: moderate)

Please consult your instructor or check these sections manually.
```

Treat all prompt text as v1 — iterate after Phase 1 SME review.

## 14. Failure modes & degradation

| Failure | Behavior |
|---|---|
| pgvector / Postgres down | `/ai-assistant/message` returns 503 "retrieval temporarily unavailable". Never call LLM ungrounded. |
| AI gateway 502 (`ALL_PROVIDERS_DOWN`) | Propagate 502, log to `retrieval_logs` with `latency_ms.llm = -1`. |
| Embed call fails during ingestion | Celery retries 3× with exponential backoff. Persistent failure → `content_sources.embedding_status='failed'`. Source still `approved` for content browsing; admin sees failed flag and can trigger re-embed. |
| Query rewriter times out / errors | Fall back to concat, then current alone. Do not block answer. |
| Embedding dim mismatch at insert | `EmbedDimensionMismatch` raised, transaction rolled back, ingestion fails loudly. |
| No approved content yet | Refuse with explanatory message: *"No approved training content has been ingested yet. Contact your administrator."* |
| User has no current aircraft set on session | Search `aircraft_id IS NULL` only. Include metadata flag in response so frontend can prompt user to set aircraft. |
| Citation key from old chat history points to superseded chunk | `_resolve_citations` still resolves it (we keep references for archived sources). Audit trail preserved. |

## 15. Telemetry

Every retrieval writes a `retrieval_logs` row. Joined to `ai_requests` via `request_id` for full E2E trace. Powers a future RAG quality dashboard without instrumentation rework.

Latency breakdown captured per stage: `rewrite`, `embed`, `vector_search`, `mmr`, `llm`.

## 16. Configuration summary

All knobs in `app/config.py` `Settings`:

```python
# RAG
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

## 17. Test strategy

Minimum coverage `--cov-fail-under=80` (existing pyproject rule).

- **Unit tests:** `chunker`, `mmr`, `grounder`, `rewriter` (mocking AIService) — 100% target
- **Integration tests:** ingestion worker + retriever against synthetic FCOM fixtures (`tests/fixtures/synthetic_fcom.json` produces a real ContentSource tree via `GenericParser`-like seed)
- **End-to-end:** `POST /ai-assistant/message` with mocked `AIService.complete()` — asserts citation_keys flow, refusal logic, response shape
- Real FCOM PDF tests come later when Sachin ships parsers

## 18. New dependencies

To add to `pyproject.toml`:

```toml
"pgvector>=0.3.0",          # SQLAlchemy bindings + Vector type
"tiktoken>=0.7.0",          # token counting for chunk size enforcement
"langchain-text-splitters>=0.2.0",  # OPTIONAL recursive splitter (alternative: ~50 LoC custom)
```

## 19. Dependencies on others

| Item | Who | Blocks | Workaround until ready |
|---|---|---|---|
| Real FCOM/QRH parsers | Sachin (R66-67) | E2E with real docs | Synthetic fixtures + `GenericParser` |
| PII filter hardening | Ira (R54) | Phase 1 launch readiness | Document gap; raise pre-launch |
| `_resolve_citations` N+1 fix | Sachin (or me — trivial) | Performance, not correctness | Fix as drive-by in this branch |
| `pgvector` Alembic migration approval | Sachin (DBA-ish) | Migration order | Include in this branch's PR; coordinate before merge |
| Role-based AI depth policy v1 | Ira (R50) | Prompt finalization | Stub addendums; iterate post-Ira |

## 20. Risks

- **Embedding cost runaway during bulk re-embed.** Mitigation: batch size cap, rate limiter on AI gateway already in place (2k/min global), Celery rate-limited task `rate_limit='10/s'`.
- **MMR correctness.** Standard algorithm but easy to get the second-pass wrong. Mitigation: dedicated unit tests with known-good cases.
- **Soft-include rescue producing low-quality answers.** Mitigation: `grounded='soft'` flag in response + system-prompt prefix instructs LLM to caveat.
- **Query rewriter inventing specifics.** Mitigation: explicit do-not-invent rule in prompt + length cap + temp=0 + integration tests that assert no fabricated entities.
- **Aircraft scope misconfiguration leaking content across programs.** Mitigation: enforced at SQL level (`WHERE` clause, not application filter); test with multi-aircraft fixtures.
