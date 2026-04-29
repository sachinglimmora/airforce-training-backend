# RAG Foundation — Brief Plan

**Branch:** `feat/rag-foundation`
**Spec:** [`2026-04-27-rag-foundation-design.md`](./2026-04-27-rag-foundation-design.md)
**Approach:** Land in small, reviewable PRs against the branch. Squash-merge into `main` only after all phases land + integration test passes.

## Phase A — Plumbing (no behavior change)

**Goal:** Get the new module + DB layer in place. No user-visible changes yet.

1. Add deps to `pyproject.toml`: `pgvector`, `tiktoken`, `langchain-text-splitters` (optional)
2. Alembic migration: enable `pgvector` extension
3. Define `ChatSession` + `ChatMessage` models in `app/modules/ai_assistant/models.py` (queried in Phase D, defined now so migrations are auto-generated cleanly)
4. Alembic migration: `content_chunks` table + ivfflat index
5. Alembic migration: `chat_sessions` + `chat_messages` tables (auto-gen from #3)
6. Alembic migration: `retrieval_logs` table
7. Alembic migration: add `embedding_status` column to `content_sources`
8. Add RAG settings to `app/config.py` (full block from spec §16)
9. Scaffold `app/modules/rag/` with stub modules (`models.py`, `schemas.py`, `chunker.py`, `embedder.py`, `retriever.py`, `grounder.py`, `rewriter.py`, `service.py`, `router.py`, `tasks.py`, `prompts.py`) — public functions raise `NotImplementedError`
10. Wire embedding-dim startup health check into `app/main.py` `@app.on_event("startup")`

**Exit criteria:** `alembic upgrade head` clean. App starts. No new endpoints active yet.

## Phase B — Ingestion

**Goal:** Approving a content source produces embedded chunks in pgvector.

10. `chunker.py` — implement 3-rule hybrid (primary / sub-split / sibling-merge) + tiktoken counting
11. `embedder.py` — wrap `AIService.embed()` + dim validation + `EmbedDimensionMismatch` exception
12. `tasks.embed_source` — Celery task: load tree → chunk → embed → insert + supersedence sweep
13. Hook `embed_source.delay(...)` into `ContentService.approve_source()`
14. `tasks.reembed_source` + `POST /content/sources/{id}/reembed` admin endpoint
15. `tasks.reembed_all_dim_mismatch` — bulk recovery task
16. Unit tests: chunker (all 3 rules + edge cases), embedder (dim validation paths)
17. Integration test: synthetic FCOM fixture → approve → assert chunks land with correct citation_keys + embeddings

**Exit criteria:** Approving a source enqueues a Celery job; chunks land in `content_chunks` with embedding + provenance; failures surface via `embedding_status='failed'`.

## Phase C — Retrieval + grounding

**Goal:** Pure retrieval works standalone, no chat layer yet.

18. `retriever.py` — pgvector cosine search + aircraft scope filter + supersedence filter
19. `retriever.py` — MMR diversification (λ from config)
20. `grounder.py` — strong/soft/refused decision + suggestions
21. `prompts.py` — system prompt skeleton + soft-grounded prefix + refusal template
22. `router.py` — `POST /api/v1/rag/query` (debug endpoint, instructor/admin only)
23. Unit tests: MMR (regression cases), grounder (threshold paths)
24. Integration test: ingested fixtures + retrieval scenarios → expected citation_keys

**Exit criteria:** `POST /rag/query` returns ranked citation_keys with grounding decision. Refusal path produces top-3 suggestions.

## Phase D — Conversational layer

**Goal:** Refactor `/ai-assistant/message` to be the real RAG-backed chat.

25. (models already defined in Phase A item 3 — Phase D just consumes them)
26. `rewriter.py` — query rewriting + skip-on-heuristic + fallback chain + Redis cache
27. `service.RAGService.answer(query, session_id)` — full orchestration: rewrite → retrieve → ground → call `AIService.complete()` → persist
28. Refactor `app/modules/ai_assistant/router.py`:
    - `POST /message` calls `RAGService.answer(...)`
    - `GET /history` reads `chat_messages` for session
    - `DELETE /history` closes session
    - Add `POST /sessions` (create with optional `aircraft_id`)
29. Implement response-shape contract from spec §12 (incl. `?debug=true` for instructor/admin)
30. Background task: auto-close sessions inactive > `CHAT_SESSION_AUTO_CLOSE_DAYS` (Celery beat)
31. Telemetry: write `retrieval_logs` row per `/message` call, joined to `ai_requests` via `request_id`
32. End-to-end test: full chat session with multi-turn follow-ups → asserts rewriting kicks in, citations preserved, refusal works

**Exit criteria:** `/api/v1/ai-assistant/message` answers grounded questions with full citations and refuses ungrounded ones. History persists. Multi-turn follow-ups work via query rewriting.

## Phase E — Polish + drive-bys

**Goal:** Loose ends before merge.

33. Drive-by fix: N+1 in `app/modules/ai/service.py:_resolve_citations` (single `WHERE citation_key IN (...)` query)
34. Add OpenAPI examples to all new endpoints
35. README section in `app/modules/rag/` explaining the contract for future contributors
36. Coverage check (target ≥80% per `pyproject`)
37. Manual smoke test against running stack via `docker-compose up`

**Exit criteria:** All tests green, coverage gate passes, manual smoke clean.

## Out of branch scope

Defer to later branches/specs:

- Adaptive quizzes, lesson plan generation, debrief generation (separate Trainee/Instructor Assistant specs)
- Frontend chat UI changes (Harish)
- Real FCOM/QRH parsers (Sachin)
- PII filter hardening (Ira)
- Cohere/cross-encoder reranking, HyDE, multi-query expansion (Phase 2)
- Cockpit interactive logic, procedures engine, scenario config (Shreyansh's other Excel items — own specs each)

## Estimated PR breakdown

| PR | Phases | Reviewer focus |
|---|---|---|
| 1 | A | Sachin — schema + migrations + dep additions |
| 2 | B | Sachin — Celery integration, content service hook |
| 3 | C | Ira — retrieval logic + grounding policy |
| 4 | D | Sachin — `/ai-assistant/message` refactor + chat persistence |
| 5 | E | Ira — final review |

Each PR small enough for ≤30 min review. Squash-merge into `feat/rag-foundation`. Single squash from branch → `main` on completion.

## Coordination touchpoints

Before Phase A merges:
- Confirm with Sachin: `pgvector` extension migration ownership — default = me (in this branch); drop A item 4 if Sachin claims it
- Confirm with Sachin: chat persistence tables in `app/modules/ai_assistant/models.py` (he OK with me adding)
- Flag to Ira: PII filter scope check before Phase 1 launch

Before Phase D merges:
- Walk Harish through response contract (spec §12) so frontend builds against the right shape
