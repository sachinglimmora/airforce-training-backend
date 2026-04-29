# Module Awareness Backend — Design Spec

**Owner:** Shreyansh Mishra
**Status:** Approved (autonomous), pending implementation
**Module:** `app/modules/ai_assistant/` (extends ChatSession)
**Branch:** `feat/module-awareness-shreyansh` (off `feat/rag-foundation`)
**Excel ref:** R89, P0, "Context-aware module awareness (backend)"

---

## 1. Goal

Track which **training module + step** a trainee is currently working on, so AI calls (chat + explain-why + future quiz/help features) can inject that context into prompts and retrieval. The frontend reports module/step changes via a small endpoint; the backend stores per-session and surfaces it to AI consumers.

Concretely: when a trainee is in *"Module 7 — Engine Start, Step 3 (Cold Weather Procedure)"* and asks the AI assistant *"why?"* — the AI should know the question is about cold-weather engine start, not generic engine start.

This is the **plumbing** for F4 (Context-Sensitive Module Help) which will land next.

## 2. Non-goals

- Auto-detection of module/step from chat content (frontend reports explicitly)
- Module/step ontology / catalog — that's Sachin's `training_modules` (when he ships it)
- Validation that `module_id`/`step_id` exist in a real module — store them as opaque strings; let the frontend pass whatever IDs it knows about
- Historical context tracking (audit log of context changes) — single current-state per session

## 3. Architecture

Add 3 columns to `ChatSession` (extends F1's chat persistence schema):
- `current_module_id` (varchar nullable)
- `current_step_id` (varchar nullable)
- `module_context_data` (jsonb nullable) — free-form bag for things like step title, system state, aircraft mode, etc.

Plus 2 endpoints:
- `PUT /api/v1/ai-assistant/sessions/{session_id}/context` — frontend updates the trainee's current module/step
- `GET /api/v1/ai-assistant/sessions/{session_id}/context` — read current context (debug + frontend re-sync)

Plus update `RAGService.answer()` to inject the module context into the system prompt when present.

## 4. Data model — additive only

### `chat_sessions` columns added

| Column | Type | Notes |
|---|---|---|
| `current_module_id` | `VARCHAR(128) NULL` | opaque ID — frontend passes whatever it has |
| `current_step_id` | `VARCHAR(128) NULL` | opaque ID |
| `module_context_data` | `JSONB NULL` | small free-form context bag |
| `context_updated_at` | `TIMESTAMPTZ NULL` | when the context was last set (for staleness detection) |

No indexes — the lookup is always by `session_id` which is already PK.

## 5. Endpoints

### 5.1 `PUT /api/v1/ai-assistant/sessions/{session_id}/context`

Body:
```json
{
  "module_id": "MODULE-7",
  "step_id": "STEP-3",
  "context_data": {
    "step_title": "Engine Start - Cold Weather",
    "aircraft_mode": "ground",
    "system_state": {"oat": "-15C"}
  }
}
```

All fields optional. `null` for any field clears it.

Auth: the session's owner OR admin/instructor.

Behavior: upsert the 3 columns + `context_updated_at = now()`. Returns the updated context.

### 5.2 `GET /api/v1/ai-assistant/sessions/{session_id}/context`

Returns current context for the session.

Auth: session's owner OR admin/instructor.

Response:
```json
{
  "data": {
    "session_id": "...",
    "module_id": "MODULE-7",
    "step_id": "STEP-3",
    "context_data": {...},
    "context_updated_at": "2026-04-29T..."
  }
}
```

## 6. RAGService.answer() integration

When a session has `current_module_id` set, the system prompt gets a context block injected:

```python
if sess.current_module_id:
    context_block = f"""
The trainee is currently working in module {sess.current_module_id}, step {sess.current_step_id or '?'}.
Context: {json.dumps(sess.module_context_data or {}, separators=(',',':'))[:500]}

Tailor your answer to this specific module/step where relevant.
"""
    sys_prompt = sys_prompt + "\n\n" + context_block
```

Truncate context_data JSON to 500 chars to bound prompt size. Skipped entirely if `current_module_id` is null.

## 7. Schemas (in `app/modules/rag/schemas.py`)

```python
class ModuleContextUpdate(BaseModel):
    module_id: str | None = Field(default=None, max_length=128)
    step_id: str | None = Field(default=None, max_length=128)
    context_data: dict | None = None


class ModuleContextOut(BaseModel):
    session_id: UUID
    module_id: str | None
    step_id: str | None
    context_data: dict | None
    context_updated_at: datetime | None
```

## 8. Failure modes

| Failure | Behavior |
|---|---|
| `session_id` doesn't exist | 404 |
| Caller is not session owner AND not admin/instructor | 403 |
| `context_data` is huge (>10KB) | 413 (limit at the schema level via Pydantic max_length on serialized form) |
| RAGService called with non-existent context columns (e.g., before migration) | Migration is required; no fallback. Migration is additive so deploys cleanly. |

## 9. Tests

**Unit:**
- ChatSession model accepts the 3 new fields
- ModuleContextUpdate / ModuleContextOut schemas validate cleanly
- Schema rejects oversized context_data

**Integration:**
- PUT /context as session owner → 200, fields persisted
- PUT /context as instructor on someone else's session → 200
- PUT /context as different trainee → 403
- GET /context returns current state
- GET /context for nonexistent session → 404
- After PUT, RAGService.answer() injects the module context into the system prompt (smoke via spy on AIService.complete messages)

## 10. Configuration

No new settings.

## 11. Coordination

- Sachin: extends `chat_sessions` (which I added in PR #1) — additive 4-column migration. No conflict with his work.
- Harish: this is the API he'll call from the trainee module UI — `PUT /context` whenever the trainee navigates to a new step.
- Ira: no impact.

## 12. Out of scope

- Module/step catalog (Sachin's `training_modules`)
- Multi-cursor (trainee in two modules at once) — single context per session
- Historical timeline of context changes — single current state
- Auto-derived context from chat history (e.g., NLP detects "engine start" → infer module) — too brittle for Phase 1
