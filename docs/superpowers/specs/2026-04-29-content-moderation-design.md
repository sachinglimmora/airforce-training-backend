# Content Moderation Layer — Design Spec

**Owner:** Shreyansh Mishra
**Status:** Approved (brainstorm 2026-04-29), pending implementation
**Module path:** `app/modules/rag/moderator.py` (+ models, schemas, router additions)
**Branch:** `feat/content-moderation-shreyansh` (off `feat/rag-foundation` — depends on RAG models)
**Excel ref:** R53, P1, "Content moderation layer on AI outputs"

---

## 1. Goal

Output-side content moderation for AI responses produced by `RAGService.answer()` (and any other consumer of `AIService.complete()` that opts in). Catches five violation classes — classification leaks, banned phrases, ungrounded outputs, profanity, casual tone — and applies tiered actions (BLOCK / REDACT / LOG) per violation type.

Production-grade from day one: **database-backed rule store + admin CRUD endpoints + Redis-cached lookups + per-rule audit log**. No hardcoded lists, no YAML-in-repo, no "we'll add CRUD later."

## 2. Non-goals

- **Input PII filtering** — Ira's lane (R54), already in `app/modules/ai/pii_filter.py`.
- **LLM-based semantic moderation** — deferred to Phase 2 with OwnLLM. Moderator interface stubs the integration point so it drops in cleanly.
- **Admin UI for rule management** — Harish's lane, eventually. The API surface is built and documented.
- **Real-time / streaming moderation** — Phase 1 responses are batch (one LLM call → one moderation pass). Streaming is Phase 2+.
- **Provider-side standard safety categories** (hate / sexual / violence) — Gemini and OpenAI handle these server-side. We don't duplicate them.

## 3. Architectural seam

Slots into the existing flow inside `RAGService.answer()`:

```
RAGService.answer(query, session_id, user)
  → rewrite (if turn ≥ 2)
  → retrieve (vector search + MMR)
  → ground (decide grounded state)
  → if grounded='refused': short-circuit (no moderation needed — refusal text is canned)
  → AIService.complete(messages, context_citations) → ai_result
  → moderator.moderate(ai_result.response, grounded, citations, db) → ModerationResult
  → branch on result.action:
      BLOCK   → replace assistant content with canned blocked-message; grounded='blocked'
      REDACT  → use result.redacted_text instead of original
      LOG     → use original; record violation
      PASS    → use original; no log
  → persist user + assistant ChatMessage
  → write moderation_logs row if any violation matched
  → return response
```

The moderator is **always called** (when `MODERATION_ENABLED=true`); the action it returns dictates branch.

## 4. Module layout

```
app/modules/rag/moderator.py          (NEW)
  - dataclasses: Violation, ModerationResult
  - public: async moderate(text, grounded_state, citations, db) -> ModerationResult
  - private detectors:
      _check_classification(text, rules) -> list[Violation]
      _check_banned(text, rules) -> list[Violation]
      _check_ungrounded(text, grounded_state, citations) -> list[Violation]   # heuristic, not rule-based
      _check_profanity(text, rules) -> tuple[str, list[Violation]]            # returns redacted_text + matches
      _check_casual(text, rules) -> list[Violation]
  - rule loading + cache:
      async load_rules(db) -> dict[Category, list[CompiledRule]]
      async invalidate_cache() -> None

app/modules/rag/models.py             (MODIFIED — add 2 tables)
  + ModerationRule
  + ModerationLog

app/modules/rag/schemas.py            (MODIFIED — add Pydantic schemas)
  + ModerationRuleIn, ModerationRuleOut
  + ModerationResultOut (for surface in /message debug)

app/modules/rag/router.py             (MODIFIED — add admin CRUD)
  + GET    /rag/moderation/rules
  + POST   /rag/moderation/rules
  + GET    /rag/moderation/rules/{id}
  + PATCH  /rag/moderation/rules/{id}
  + DELETE /rag/moderation/rules/{id}
  + GET    /rag/moderation/logs            (read-only audit view)

app/modules/rag/service.py            (MODIFIED — call moderator after gateway)
  ~ RAGService.answer() inserts moderation step

migrations/versions/<auto>_create_moderation_tables.py    (NEW)
  - moderation_rules
  - moderation_logs
  + seed default classification + profanity + casual rules

tests/unit/test_moderation.py         (NEW)
  - per-category detector tests
  - action precedence tests
  - rule cache + invalidation tests
  - regex compile-error handling

tests/integration/test_moderation_endpoints.py   (NEW)
  - admin CRUD round-trip
  - end-to-end: chat message → blocked response shape

app/config.py                         (MODIFIED — add 4 settings)
```

## 5. Data model

### 5.1 `moderation_rules`

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID PK` | |
| `category` | `ENUM('classification','banned_phrase','profanity','casual')` | not null |
| `pattern` | `TEXT` | regex or literal string per `pattern_type` |
| `pattern_type` | `ENUM('regex','literal')` | default `'regex'` |
| `action` | `ENUM('block','redact','log')` | what happens on match |
| `severity` | `ENUM('critical','high','medium','low')` | for audit triage |
| `description` | `TEXT NULL` | human-readable description |
| `active` | `BOOLEAN` | not null, default `true` (soft-disable instead of delete) |
| `created_by` | `UUID FK users.id NULL` | who added the rule |
| `created_at` | `TIMESTAMPTZ` | not null, default `now()` |
| `updated_at` | `TIMESTAMPTZ` | not null, auto-updated |

Indexes:
- B-tree on `category, active` (the primary lookup pattern)
- B-tree on `created_at` (for audit list views)

### 5.2 `moderation_logs`

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID PK` | |
| `request_id` | `VARCHAR(36) NULL` | joins to `ai_requests.id` for E2E trace |
| `session_id` | `UUID FK chat_sessions.id NULL` | |
| `user_id` | `UUID NULL` | |
| `rule_id` | `UUID FK moderation_rules.id NULL` | NULL when violation is heuristic (e.g. ungrounded) |
| `category` | `ENUM('classification','banned_phrase','ungrounded','profanity','casual')` | includes 'ungrounded' which has no rule_id |
| `matched_text` | `TEXT` | the actual matched substring (truncated to 500 chars) |
| `original_response` | `TEXT` | full pre-moderation response (truncated to 4000 chars) |
| `action_taken` | `ENUM('block','redact','log')` | |
| `severity` | `ENUM('critical','high','medium','low')` | |
| `created_at` | `TIMESTAMPTZ` | not null, default `now()`, indexed |

Indexes:
- B-tree on `created_at` (recent-violations dashboards)
- B-tree on `session_id` (per-session audit)
- B-tree on `severity, created_at` (alerting on critical violations)

### 5.3 Migration includes seed data (reversible in `downgrade()`)

Default rules inserted by the migration:

**Classification (BLOCK, critical):**
- `\bSECRET//\w+` (regex)
- `\bTOP\s+SECRET\b` (regex)
- `\bTS//SCI\b` (regex)
- `\bNOFORN\b` (regex)
- `\bREL\s+TO\s+\w+` (regex)
- `\bCONFIDENTIAL//\w+` (regex)

**Profanity (REDACT, medium):** standard 7-word list. Short, English-only for Phase 1; Hindi/regional terms can be added per-deployment via the admin API.

**Casual register (LOG, low):**
- `\b(lol|lmao|haha|hehe|dude|gonna|wanna|kinda|gotta)\b` (regex, case-insensitive)

**Banned phrases:** none seeded — admin populates per organization.

## 6. Rule loading + caching

Rules are queried from Postgres but cached in Redis with a short TTL so the moderator doesn't query the DB on every call.

```python
async def load_rules(db) -> dict[Category, list[CompiledRule]]:
    """Loads active rules by category, compiles regex patterns once, caches in Redis."""
    cached = await redis.get("moderation_rules:v1")
    if cached:
        return _decode(cached)  # also rebuilds CompiledRule (re.compile happens here, not stored)

    rows = await db.execute(
        select(ModerationRule).where(ModerationRule.active == True)
    ).scalars().all()

    by_category: dict[Category, list[CompiledRule]] = defaultdict(list)
    for r in rows:
        try:
            compiled = (re.compile(r.pattern, re.IGNORECASE) if r.pattern_type == "regex"
                        else re.compile(re.escape(r.pattern), re.IGNORECASE))
            by_category[r.category].append(CompiledRule(rule=r, compiled=compiled))
        except re.error as exc:
            log.error("moderation_rule_compile_failed", rule_id=str(r.id), pattern=r.pattern, error=str(exc))
            # SKIP this rule, continue loading others. Alert flagged for admin attention.

    # Cache the SERIALIZABLE rule data (not CompiledRule which has re.Pattern objects)
    await redis.setex("moderation_rules:v1", 60, _encode_serializable(by_category))
    return by_category
```

**Cache invalidation:** every CRUD endpoint (`POST`/`PATCH`/`DELETE` on `moderation_rules`) calls `await invalidate_cache()` before returning. Cache key pattern `moderation_rules:v*` allows version bumps if schema changes.

**Cache TTL:** 60 seconds. Even without explicit invalidation, rule changes propagate within a minute. Configurable via `MODERATION_CACHE_TTL_S`.

**Cache miss / Redis down:** falls back to direct DB query (slower path but works).

## 7. Detectors

Each is a pure function on the response text plus the rule list (or grounding state for the heuristic).

### 7.1 Classification + banned phrase

```python
def _check_pattern_category(text, rules) -> list[Violation]:
    violations = []
    for cr in rules:
        for match in cr.compiled.finditer(text):
            violations.append(Violation(
                category=cr.rule.category,
                rule_id=cr.rule.id,
                matched_text=match.group(0),
                action=cr.rule.action,
                severity=cr.rule.severity,
                start=match.start(),
                end=match.end(),
            ))
    return violations
```

Used for both `classification` and `banned_phrase` categories — same logic, different rule set.

### 7.2 Ungrounded heuristic (no rule, hard-coded logic)

```python
_CITATION_RE = re.compile(r"\[([\w\-\.]+)\]")

def _check_ungrounded(text, grounded_state, citations) -> list[Violation]:
    if grounded_state != "strong" or not citations:
        return []  # only enforce for strong grounding
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

Always on for `grounded='strong'`. Skipped for `'soft'` (already caveated) and `'refused'` (no LLM response to check).

### 7.3 Profanity (REDACT)

Returns the redacted text alongside the violation list:

```python
def _check_profanity(text, rules) -> tuple[str, list[Violation]]:
    violations = []
    redacted = text
    for cr in rules:
        def _replace(m):
            violations.append(Violation(
                category="profanity", rule_id=cr.rule.id,
                matched_text=m.group(0), action="redact",
                severity=cr.rule.severity, start=m.start(), end=m.end(),
            ))
            return "*" * len(m.group(0))
        redacted = cr.compiled.sub(_replace, redacted)
    return redacted, violations
```

### 7.4 Casual register (LOG only)

Pattern detection without text modification — just for audit/dashboard.

## 8. Action precedence (when multiple violations match)

```python
def _resolve_action(violations) -> ModerationResult:
    if any(v.action == "block" for v in violations):
        # Most severe BLOCK wins; ignore others
        block = max((v for v in violations if v.action == "block"),
                    key=lambda v: _severity_rank[v.severity])
        return ModerationResult(action="block", primary=block, all=violations)
    elif any(v.action == "redact" for v in violations):
        # redacted_text comes from _check_profanity (the only detector that produces a modified string)
        return ModerationResult(action="redact", redacted_text=profanity_redacted, all=violations)
    elif any(v.action == "log" for v in violations):
        return ModerationResult(action="log", all=violations)
    else:
        return ModerationResult(action="pass")
```

Severity rank: `critical(4) > high(3) > medium(2) > low(1)`.

All violations get logged regardless of which action wins (so we know the full picture per response).

## 9. Response shape

### 9.1 BLOCK case

`grounded` enum gains a fourth state: `"blocked"`. The `assistantMessage` content is a canned message, with a new `moderation` field surfacing why:

```json
{
  "data": {
    "userMessage": {...},
    "assistantMessage": {
      "id": "msg_xxx",
      "role": "assistant",
      "content": "This response was blocked by the content moderation layer. Please rephrase or contact your instructor.",
      "timestamp": "2026-04-29T12:00:00Z",
      "grounded": "blocked",
      "moderation": {
        "violation_type": "classification_marker",
        "severity": "critical",
        "rule_id": "..."
      },
      "sources": [],
      "suggestions": []
    }
  }
}
```

### 9.2 REDACT case

Response goes through with `****` substitutions. Optional `moderation` field surfaces redaction count:

```json
"assistantMessage": {
  ...
  "content": "Per FCOM §3.2.1, the **** engine requires...",
  "grounded": "strong",
  "moderation": {
    "redactions_applied": 1,
    "categories": ["profanity"]
  },
  "sources": [...],
  ...
}
```

### 9.3 LOG case

Response unchanged. NO `moderation` field surfaced to client. Server-side `moderation_logs` row is written.

### 9.4 PASS case (no violations)

Identical to today's response shape — no moderation field at all.

## 10. Admin endpoints

All require `set(current_user.roles) & {"admin", "instructor"}` per the existing pattern.

### 10.1 `GET /api/v1/rag/moderation/rules`

Query params: `category`, `active`, `limit`, `offset`. Returns paginated rule list.

### 10.2 `POST /api/v1/rag/moderation/rules`

Body: `ModerationRuleIn` (category, pattern, pattern_type, action, severity, description, active). Returns created rule. **Side effect: invalidates Redis cache.**

### 10.3 `GET /api/v1/rag/moderation/rules/{id}`

Single rule fetch.

### 10.4 `PATCH /api/v1/rag/moderation/rules/{id}`

Partial update — most common is toggling `active` or changing `action`/`severity`. **Side effect: invalidates cache.**

### 10.5 `DELETE /api/v1/rag/moderation/rules/{id}`

Soft delete by default (sets `active=false`) — works for any role with `admin|instructor`. Hard delete requires `?hard=true` query param **and** the `admin` role specifically (instructor cannot hard-delete). **Side effect: invalidates cache.**

### 10.6 `GET /api/v1/rag/moderation/logs`

Audit view. Query params: `category`, `severity`, `session_id`, `user_id`, `since`, `until`, `limit`, `offset`. Returns paginated log entries with rule + matched_text + original_response.

## 11. Failure modes

| Failure | Behavior |
|---|---|
| `MODERATION_ENABLED=false` (kill switch) | Skip moderator entirely; pass response through unchanged |
| Rules table empty / all rules inactive | Pass through + log warning. Admin should be aware. |
| Redis cache unavailable | Fall back to direct DB query. Slower (~10ms/call) but works. |
| Rules DB unavailable | If `MODERATION_FAIL_OPEN=true` (default): pass through + log error + alert admin (don't break the chat over moderation infra failure). If `false`: return 503. |
| Regex compile error on a rule | Skip that rule, log error, continue with others. Surface in admin logs view. |
| `moderation_logs` insert fails | Log to structlog, return the moderated response anyway — don't block delivery on audit infra. |
| Multiple BLOCK violations | Most severe wins; all logged. |
| Heuristic ungrounded check on a `soft` response | No-op (only enforced for `strong`). |

## 12. Telemetry / audit

Every match writes a `moderation_logs` row:
- `request_id` joins to `ai_requests` (Sachin's table) for full E2E trace
- `session_id` joins to `chat_sessions`
- `original_response` truncated to 4000 chars (preserve evidence without bloating storage)
- `matched_text` truncated to 500 chars

Future quality dashboard can join `moderation_logs` ⨝ `retrieval_logs` ⨝ `ai_requests` ⨝ `chat_messages` for per-session forensic view.

## 13. Configuration (in `app/config.py`)

```python
MODERATION_ENABLED: bool = True            # kill switch — set False to disable entirely
MODERATION_CACHE_TTL_S: int = 60           # how long Redis caches the rule set
MODERATION_FAIL_OPEN: bool = True          # if True, pass response through when moderator infra fails
MODERATION_LOG_TRUNCATE_RESPONSE: int = 4000  # max chars stored in moderation_logs.original_response
```

## 14. Tests

Coverage target: chunker-level (98–100%) for `moderator.py` since it's pure logic + DB I/O.

**Unit (`tests/unit/test_moderation.py`):**
- Each detector: positive cases (rule fires) + negative cases (no false positives)
- Action precedence: BLOCK > REDACT > LOG > PASS
- Multiple BLOCK violations → most severe wins
- Profanity REDACT: matched chars replaced with `*`s of equal length
- Ungrounded heuristic: `strong + no [citation]` → block; `soft + no citation` → no-op
- Regex compile error handling: bad rule skipped, others still load
- Cache: load → cached → invalidate → reload from DB
- `MODERATION_ENABLED=false` → moderator returns PASS without any work
- `MODERATION_FAIL_OPEN=true` → DB error → PASS + log; `false` → raises

**Integration (`tests/integration/test_moderation_endpoints.py`):**
- Admin CRUD round-trip (POST → GET → PATCH → DELETE) with role-gate (trainee gets 403)
- End-to-end: chat message → moderator catches classification marker → blocked response shape
- Cache invalidation: POST a new rule → moderator picks it up on next call (no 60s wait needed)
- Audit log row written per violation

## 15. Coordination + dependencies

| Item | Who | Status |
|---|---|---|
| RAG foundation (PR #1 — `feat/rag-foundation`) | Shreyansh | Already shipped, this branch is stacked on it |
| Sachin's `ai_requests` table | Sachin | Exists; we just FK to `request_id` |
| Sachin's `users` table | Sachin | Exists; we FK for `created_by` |
| Sachin's `chat_sessions` table | Shreyansh (in PR #1) | Exists |
| Admin UI for moderation rules | Harish | Not blocking — API is consumable as soon as this lands |
| PII filter (input) | Ira (R54) | Independent — different filter, different direction |

## 16. Risks

- **False-positive blocks erode trust.** Mitigation: ship with conservative seed rules, enable LOG-only severity for ambiguous patterns initially, audit `moderation_logs` weekly during pilot.
- **Latency creep.** Moderator should add ≤10ms per response. Mitigation: Redis cache hit path is sub-ms; cold-cache load is one DB query (~5ms); detector loops are pure regex (~1-2ms). Targets verified in tests.
- **Storage growth on `moderation_logs`.** Truncated columns + indexed `created_at` enable a future TTL-based purge job (Celery beat — out of scope this PR).
- **Admin endpoint abuse.** Role-gated to admin/instructor; CRUD writes also write to Sachin's `audit_log` (drive-by — symmetric with how `approve_source` is audited).

## 17. Out of scope for this PR

- LLM-based semantic judge (Phase 2 with OwnLLM)
- Admin UI (Harish, eventually)
- Streaming moderation (mid-response cancellation)
- Multi-tenant rule scoping (per-aircraft / per-program rule overrides)
- Auto-detection of new banned-phrase candidates from violation logs
- Periodic `moderation_logs` retention purge (Celery beat task — separate ticket)
