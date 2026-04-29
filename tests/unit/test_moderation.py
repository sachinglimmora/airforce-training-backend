import re
import uuid

import pytest

from app.modules.rag.moderator import CompiledRule, Violation, _check_pattern_category


def _rule(category, action, severity, pattern_str):
    return CompiledRule(
        rule_id=uuid.uuid4(),
        category=category,
        action=action,
        severity=severity,
        compiled=re.compile(pattern_str, re.IGNORECASE),
    )


def test_pattern_no_match_returns_empty():
    rules = [_rule("classification", "block", "critical", r"\bSECRET//\w+")]
    assert _check_pattern_category("clean text here", rules) == []


def test_pattern_single_match_returns_one_violation():
    rules = [_rule("classification", "block", "critical", r"\bSECRET//\w+")]
    out = _check_pattern_category("contents marked SECRET//NOFORN here", rules)
    assert len(out) == 1
    v = out[0]
    assert v.category == "classification"
    assert v.action == "block"
    assert v.severity == "critical"
    assert v.matched_text == "SECRET//NOFORN"
    assert v.start == 16


def test_pattern_multiple_matches_in_one_text():
    rules = [_rule("classification", "block", "critical", r"\bSECRET//\w+")]
    out = _check_pattern_category("SECRET//A and SECRET//B both", rules)
    assert len(out) == 2


def test_pattern_multiple_rules_same_text():
    rules = [
        _rule("classification", "block", "critical", r"\bNOFORN\b"),
        _rule("classification", "block", "critical", r"\bREL\s+TO\s+\w+"),
    ]
    out = _check_pattern_category("NOFORN and REL TO USA both fire", rules)
    assert len(out) == 2
    cats = {v.matched_text for v in out}
    assert cats == {"NOFORN", "REL TO USA"}


def test_pattern_empty_rules_list():
    assert _check_pattern_category("anything", []) == []
