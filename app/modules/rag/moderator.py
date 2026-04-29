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


# Detector + orchestration functions defined in subsequent tasks
async def moderate(text: str, grounded_state: str, citations: list[str], db) -> ModerationResult:
    raise NotImplementedError  # implemented in Task B8
