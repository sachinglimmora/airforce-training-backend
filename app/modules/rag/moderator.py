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


def _check_casual(text: str, rules: list[CompiledRule]) -> list[Violation]:
    """Casual register detector — same shape as pattern category but always action='log'."""
    return _check_pattern_category(text, rules)


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


async def moderate(text: str, grounded_state: str, citations: list[str], db) -> ModerationResult:
    raise NotImplementedError  # implemented in Task B8
