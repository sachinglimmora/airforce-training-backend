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


# Detector + orchestration functions defined in subsequent tasks
async def moderate(text: str, grounded_state: str, citations: list[str], db) -> ModerationResult:
    raise NotImplementedError  # implemented in Task B8
