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


from app.modules.rag.moderator import _check_ungrounded


def test_ungrounded_strong_with_brackets_returns_empty():
    out = _check_ungrounded("Per [FCOM-3.2.1], engine start...", "strong", ["FCOM-3.2.1"])
    assert out == []


def test_ungrounded_strong_without_brackets_returns_block_violation():
    out = _check_ungrounded("Engine starts when you press the button.", "strong", ["FCOM-3.2.1"])
    assert len(out) == 1
    v = out[0]
    assert v.category == "ungrounded"
    assert v.action == "block"
    assert v.severity == "high"
    assert v.rule_id is None


def test_ungrounded_soft_grounding_no_check():
    out = _check_ungrounded("Engine starts.", "soft", ["FCOM-3.2.1"])
    assert out == []


def test_ungrounded_no_citations_no_check():
    out = _check_ungrounded("anything", "strong", [])
    assert out == []


def test_ungrounded_refused_state_no_check():
    out = _check_ungrounded("anything", "refused", ["FCOM-3.2.1"])
    assert out == []


from app.modules.rag.moderator import _check_profanity


def test_profanity_no_match_returns_text_unchanged():
    rules = [_rule("profanity", "redact", "medium", r"\bdamn\b")]
    redacted, viols = _check_profanity("clean engine start", rules)
    assert redacted == "clean engine start"
    assert viols == []


def test_profanity_single_match_replaces_with_stars():
    rules = [_rule("profanity", "redact", "medium", r"\bdamn\b")]
    redacted, viols = _check_profanity("the damn engine", rules)
    assert redacted == "the **** engine"
    assert len(viols) == 1
    assert viols[0].matched_text == "damn"


def test_profanity_multiple_matches_all_redacted():
    rules = [_rule("profanity", "redact", "medium", r"\bdamn\b")]
    redacted, viols = _check_profanity("damn this damn engine", rules)
    assert redacted == "**** this **** engine"
    assert len(viols) == 2


def test_profanity_multiple_rules_chained():
    rules = [
        _rule("profanity", "redact", "medium", r"\bdamn\b"),
        _rule("profanity", "redact", "medium", r"\bhell\b"),
    ]
    redacted, viols = _check_profanity("damn hell yes", rules)
    assert "*" in redacted
    assert "damn" not in redacted
    assert "hell" not in redacted
    assert len(viols) == 2


from app.modules.rag.moderator import _check_casual


def test_casual_no_match_returns_empty():
    rules = [_rule("casual", "log", "low", r"\blol\b")]
    assert _check_casual("formal text", rules) == []


def test_casual_match_returns_log_violations():
    rules = [_rule("casual", "log", "low", r"\b(lol|haha)\b")]
    out = _check_casual("yeah lol haha that's funny", rules)
    assert len(out) == 2
    assert all(v.category == "casual" for v in out)
    assert all(v.action == "log" for v in out)
    assert all(v.severity == "low" for v in out)


from app.modules.rag.moderator import _resolve_action


def test_resolve_no_violations_returns_pass():
    out = _resolve_action([], "original text")
    assert out.action == "pass"
    assert out.primary is None
    assert out.all == []


def test_resolve_block_wins_over_redact_and_log():
    block = Violation("classification", uuid.uuid4(), "X", "block", "critical", 0, 1)
    redact = Violation("profanity", uuid.uuid4(), "Y", "redact", "medium", 1, 2)
    out = _resolve_action([redact, block], "original text")
    assert out.action == "block"
    assert out.primary is block


def test_resolve_most_severe_block_wins_when_multiple_blocks():
    high = Violation("banned_phrase", uuid.uuid4(), "A", "block", "high", 0, 1)
    critical = Violation("classification", uuid.uuid4(), "B", "block", "critical", 1, 2)
    out = _resolve_action([high, critical], "original text")
    assert out.action == "block"
    assert out.primary is critical


def test_resolve_redact_uses_redacted_text_when_provided():
    redact = Violation("profanity", uuid.uuid4(), "damn", "redact", "medium", 4, 8)
    out = _resolve_action([redact], "the **** word", redacted_text="the **** word")
    assert out.action == "redact"
    assert out.redacted_text == "the **** word"


def test_resolve_log_only_when_no_block_or_redact():
    log_v = Violation("casual", uuid.uuid4(), "lol", "log", "low", 0, 3)
    out = _resolve_action([log_v], "original text")
    assert out.action == "log"
    assert out.primary is None
    assert log_v in out.all


def test_resolve_all_violations_in_result_regardless_of_action():
    block = Violation("classification", uuid.uuid4(), "X", "block", "critical", 0, 1)
    redact = Violation("profanity", uuid.uuid4(), "Y", "redact", "medium", 1, 2)
    log_v = Violation("casual", uuid.uuid4(), "Z", "log", "low", 2, 3)
    out = _resolve_action([block, redact, log_v], "original text")
    assert out.action == "block"
    assert len(out.all) == 3


from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.rag.moderator import load_rules, invalidate_cache


def _row(category, pattern, action, severity, pattern_type="regex", active=True):
    r = MagicMock()
    r.id = uuid.uuid4()
    r.category = category
    r.pattern = pattern
    r.pattern_type = pattern_type
    r.action = action
    r.severity = severity
    r.active = active
    return r


async def test_load_rules_from_db_when_cache_miss():
    rows = [_row("classification", r"\bSECRET\b", "block", "critical")]
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(scalars=lambda: MagicMock(all=lambda: rows)))
    with patch("app.modules.rag.moderator._cache_get", new=AsyncMock(return_value=None)) as mock_get, \
         patch("app.modules.rag.moderator._cache_set", new=AsyncMock()) as mock_set:
        out = await load_rules(db)
        assert "classification" in out
        assert len(out["classification"]) == 1
        assert isinstance(out["classification"][0].compiled, re.Pattern)
        mock_get.assert_awaited_once()
        mock_set.assert_awaited_once()


async def test_load_rules_skips_invalid_regex():
    bad = _row("classification", r"[unclosed", "block", "critical")
    good = _row("classification", r"\bSECRET\b", "block", "critical")
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(scalars=lambda: MagicMock(all=lambda: [bad, good])))
    with patch("app.modules.rag.moderator._cache_get", new=AsyncMock(return_value=None)), \
         patch("app.modules.rag.moderator._cache_set", new=AsyncMock()):
        out = await load_rules(db)
        # bad rule skipped, good one kept
        assert len(out["classification"]) == 1


async def test_load_rules_handles_literal_pattern_type():
    row = _row("banned_phrase", "verbatim phrase", "block", "high", pattern_type="literal")
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(scalars=lambda: MagicMock(all=lambda: [row])))
    with patch("app.modules.rag.moderator._cache_get", new=AsyncMock(return_value=None)), \
         patch("app.modules.rag.moderator._cache_set", new=AsyncMock()):
        out = await load_rules(db)
        cr = out["banned_phrase"][0]
        assert cr.compiled.search("contains verbatim phrase here")


async def test_invalidate_cache_calls_redis_del():
    with patch("app.modules.rag.moderator._cache_del", new=AsyncMock()) as mock_del:
        await invalidate_cache()
        mock_del.assert_awaited_once_with(_cache_key())


def _cache_key():
    from app.modules.rag.moderator import _CACHE_KEY
    return _CACHE_KEY
