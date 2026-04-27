import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.modules.rag.rewriter import rewrite, _has_anaphora, _needs_rewrite


def _make_session_factory_mock():
    db = MagicMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=db)
    ctx.__aexit__ = AsyncMock(return_value=False)
    factory = MagicMock(return_value=ctx)
    return factory


def test_needs_rewrite_skips_first_turn():
    assert _needs_rewrite("anything", turn=0) is False


def test_needs_rewrite_skips_long_no_anaphora():
    msg = "what is the standard procedure for engine start in cold weather operations"
    assert _needs_rewrite(msg, turn=2) is False


def test_needs_rewrite_proceeds_on_anaphora():
    assert _needs_rewrite("and what about it?", turn=2) is True


def test_has_anaphora_detects_pronouns():
    assert _has_anaphora("what about it?") is True
    assert _has_anaphora("describe the engine start procedure") is False


async def test_rewrite_returns_msg_on_first_turn():
    out = await rewrite("hello", history=[], turn=0)
    assert out == "hello"


async def test_rewrite_calls_llm_on_followup_with_anaphora():
    fake = {
        "response": "rewritten engine start procedure",
        "provider": "g", "model": "x",
        "cached": False, "usage": {}, "citations": [], "request_id": "r",
    }
    ai_instance = MagicMock()
    ai_instance.complete = AsyncMock(return_value=fake)
    with patch("app.modules.rag.rewriter.AsyncSessionLocal", _make_session_factory_mock()), \
         patch("app.modules.rag.rewriter.AIService", return_value=ai_instance):
        out = await rewrite(
            "and what about it?",
            history=[{"role": "user", "content": "engine start"}],
            turn=2,
        )
        assert out == "rewritten engine start procedure"


async def test_rewrite_falls_back_on_provider_error():
    ai_instance = MagicMock()
    ai_instance.complete = AsyncMock(side_effect=RuntimeError("provider down"))
    with patch("app.modules.rag.rewriter.AsyncSessionLocal", _make_session_factory_mock()), \
         patch("app.modules.rag.rewriter.AIService", return_value=ai_instance):
        history = [
            {"role": "user", "content": "engine start"},
            {"role": "assistant", "content": "see FCOM 3.2.1"},
        ]
        out = await rewrite("and what about it?", history=history, turn=2)
        # Fallback: concat last user msg + current
        assert "engine start" in out
        assert "and what about it?" in out
