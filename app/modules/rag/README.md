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
