from app.modules.rag.chunker import count_tokens


def test_count_tokens_returns_zero_for_empty():
    assert count_tokens("") == 0


def test_count_tokens_returns_positive_for_text():
    assert count_tokens("hello world") > 0


def test_count_tokens_grows_with_length():
    assert count_tokens("a b c d e f g h") > count_tokens("a b")
