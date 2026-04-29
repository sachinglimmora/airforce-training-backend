# Explain-Why System Behavior Endpoint — Design Spec

**Owner:** Shreyansh Mishra
**Status:** Approved (autonomous), pending implementation
**Module:** `app/modules/rag/`
**Branch:** `feat/explain-why-shreyansh` (off `feat/rag-foundation`)
**Excel ref:** R40, P0, "Explain-why system behavior explanations"

---

## 1. Goal

Standalone endpoint that gives a trainee a **just-in-time, grounded, educational explanation** of an aircraft system, action, or observed state. Distinct from the chat endpoint: this is a one-shot Q&A specialized for "explain why" — no session, no history, no rewriter; just retrieve + ground + answer with an educational tone.

Use cases (frontend will call from cockpit overlays + module pages):
- Trainee clicks an instrument: *"Explain why the EGT spikes during start"*
- Trainee in a module: *"Explain why we close the bleed valve before takeoff"*
- Instructor reviewing: *"Explain the dependency between hydraulic system A and the flaps"*

## 2. Non-goals

- Multi-turn conversation (use `/ai-assistant/message` for that)
- Quiz/question generation (that's F2)
- Translation / multi-language (Phase 2)
- Streaming response (Phase 2)

## 3. Architecture

```
POST /api/v1/ai-assistant/explain
  → embed(topic + optional context)
  → vector search via pgvector (aircraft-scoped if aircraft_id provided)
  → MMR diversification
  → grounder.decide()
  → if refused: return refusal + suggestions
  → AIService.complete() with EXPLAIN_WHY_SYSTEM_PROMPT (educational tone)
  → moderator.moderate() (re-uses F1 layer)
  → return {explanation, sources, grounded}
```

Reuses RAG infra (retriever, grounder, moderator) but with:
- A different system prompt focused on educational depth + "why this matters"
- No chat history persistence (stateless)
- Optional `system_state` dict in the request to inject runtime context (e.g., `{"engine_n1": "23%", "oil_temp": "low"}`)

## 4. Module surface

### Endpoint

```
POST /api/v1/ai-assistant/explain
```

Request body:
```json
{
  "topic": "EGT spike during engine start",
  "context": "Su-30MKI, AL-31FP engine, cold weather start",
  "system_state": {"engine_n1": "23%", "oil_temp": "low"},
  "aircraft_id": "uuid-or-null"
}
```

Only `topic` is required.

Response (success / soft):
```json
{
  "data": {
    "explanation": "EGT spikes briefly during start because... [SU30-FCOM-3.2.1]",
    "grounded": "strong",
    "sources": [
      {
        "citation_key": "SU30-FCOM-3.2.1",
        "display_label": "FCOM Vol 2 §3.2.1 — Engine Start",
        "page_number": 127,
        "score": 0.87,
        "source_type": "fcom",
        "source_version": "Rev 42",
        "snippet": "..."
      }
    ],
    "suggestions": [],
    "moderation": null
  }
}
```

Response (refused):
```json
{
  "data": {
    "explanation": "I don't have approved source material that explains this directly. Closest related references: ...",
    "grounded": "refused",
    "sources": [],
    "suggestions": [/* top-3 below threshold */],
    "moderation": null
  }
}
```

Response (blocked by moderator):
```json
{
  "data": {
    "explanation": "This response was blocked by the content moderation layer.",
    "grounded": "blocked",
    "sources": [],
    "suggestions": [],
    "moderation": {"violation_type": "...", "severity": "..."}
  }
}
```

Auth: any authenticated user (trainee/instructor/admin). NOT role-gated — explain-why is a core trainee feature.

## 5. New files

```
Modify:
  app/modules/rag/prompts.py        (+ EXPLAIN_WHY_SYSTEM_PROMPT)
  app/modules/rag/service.py        (+ ExplainService.explain method)
  app/modules/rag/schemas.py        (+ ExplainRequest, ExplainResponse)
  app/modules/ai_assistant/router.py (+ POST /explain endpoint)

Create:
  tests/unit/test_explain_service.py
  tests/integration/test_explain_endpoint.py
```

No new tables. No new migrations. Pure compose-of-existing primitives.

## 6. System prompt (in `prompts.py`)

```python
EXPLAIN_WHY_SYSTEM_PROMPT = """You are an aerospace training assistant providing a focused 'why does this happen' explanation to an Indian Air Force trainee.

Audience: {audience_label}
Aircraft context: {aircraft_context}
Optional system state observed: {system_state_summary}

RULES:
1. Answer ONLY using the reference material in this conversation. Do NOT speculate.
2. If the reference is insufficient, say so — do NOT guess.
3. Cite specific sections in your explanation using the citation_key in [brackets].
4. Structure: brief one-line summary → mechanism (why this happens) → safety/operational implication → cross-reference to related procedures if relevant.
5. Use **bold** for safety-critical values, limits, and warnings.
6. Be concise: 4-8 sentences typical, 12 max for complex systems.
7. Educational, not conversational. No filler ("great question", etc.). No first-person opinions."""
```

## 7. ExplainService method (in `service.py`)

Reuses RAGService's primitives. Add a sibling class or top-level function:

```python
class ExplainService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def explain(
        self,
        topic: str,
        context: str | None,
        system_state: dict | None,
        aircraft_id: UUID | None,
        user,
    ) -> dict:
        """One-shot grounded explanation. No session, no history."""
        # 1. Build the retrieval query (topic + optional context)
        retrieval_query = topic if not context else f"{topic} ({context})"

        # 2. Retrieve
        cfg = _build_cfg()
        hits, latency = await retrieve(self.db, retrieval_query, aircraft_id, cfg)

        # 3. Ground
        decision = decide(hits, cfg)

        # 4. Refusal short-circuit
        if decision["grounded"] == "refused":
            suggestions = await self._resolve_sources(...)  # reuse RAGService helper
            return {
                "explanation": render_refusal(decision["suggestions"]),
                "grounded": "refused", "sources": [], "suggestions": suggestions,
                "moderation": None,
            }

        # 5. Build messages + call gateway
        aircraft_label = await self._aircraft_context_label(aircraft_id)
        audience_label = "instructor" if (set(getattr(user, "roles", [])) & {"admin", "instructor"}) else "trainee"
        sys_state_summary = json.dumps(system_state) if system_state else "(none)"
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
                temperature=0.2, max_tokens=600, cache=True,
            ),
            user_id=str(getattr(user, "id", "anonymous")),
        )

        # 6. Moderate (reuse F1)
        from app.modules.rag.moderator import moderate as _moderate
        mod_result = await _moderate(
            ai_result["response"], decision["grounded"], decision["citation_keys"], self.db,
        )

        # 7. Build response based on moderation result
        if mod_result.action == "block":
            return {
                "explanation": "This response was blocked by the content moderation layer.",
                "grounded": "blocked", "sources": [], "suggestions": [],
                "moderation": {"violation_type": mod_result.primary.category, "severity": mod_result.primary.severity},
            }
        text = mod_result.redacted_text if mod_result.action == "redact" else ai_result["response"]
        moderation_field = (
            {"redactions_applied": sum(1 for v in mod_result.all if v.action == "redact")}
            if mod_result.action == "redact" else None
        )

        sources = await self._resolve_sources(
            decision["citation_keys"],
            {k: h.score for h in hits for k in h.citation_keys if h.included},
        )
        return {
            "explanation": text,
            "grounded": decision["grounded"],
            "sources": sources,
            "suggestions": [],
            "moderation": moderation_field,
        }
```

(Implementation can extract `_build_cfg`, `_aircraft_context_label`, `_resolve_sources` from RAGService — refactor those to module-level helpers to share.)

## 8. Failure modes

| Failure | Behavior |
|---|---|
| `topic` empty / whitespace | 400 with "topic is required" |
| Retriever returns no hits | grounder → refused → return refusal + empty suggestions |
| AIService.complete returns 502 (all providers down) | Propagate 502 |
| Moderator BLOCK | Return blocked-shape response |
| Moderator REDACT | Return redacted text |
| Cache (Redis) unavailable | Fall back to direct DB (same as RAG path) |

## 9. Tests

**Unit:**
- ExplainService instantiates cleanly
- Retrieval query construction (with/without context)
- Refusal short-circuit when grounder returns refused
- System prompt formatting with various audience/aircraft/state combos

**Integration:**
- POST /explain returns grounded explanation with citations
- POST /explain with no aircraft → searches general
- POST /explain with empty topic → 400
- POST /explain with classification marker in mocked response → blocked
- POST /explain unauthenticated → 401

## 10. Configuration

No new settings. Reuses existing `RAG_*` and `MODERATION_*` config.

## 11. Coordination

- Sachin: no changes to his modules.
- Ira: no impact (same auth path).
- Harish: this is the API he'll call from cockpit overlays / module pages. The response shape mirrors the chat endpoint's `assistantMessage` so the frontend can reuse the citation rendering component.

## 12. Out of scope

- Streaming responses
- Multi-turn refinement
- Translation
- Image attachments (e.g., trainee shows EICAS screenshot)
