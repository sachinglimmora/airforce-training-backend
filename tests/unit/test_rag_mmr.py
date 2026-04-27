import math

from app.modules.rag.retriever import _mmr_rerank


def _vec(*xs):
    return list(xs)


def test_mmr_returns_all_when_few_candidates():
    cands = [
        {"id": "a", "embedding": _vec(1, 0, 0), "score": 0.9},
        {"id": "b", "embedding": _vec(0, 1, 0), "score": 0.8},
    ]
    out = _mmr_rerank(cands, lambda_=0.5, qvec=_vec(1, 0, 0))
    assert {c["id"] for c in out} == {"a", "b"}


def test_mmr_prefers_diversity_when_lambda_low():
    cands = [
        {"id": "a", "embedding": _vec(1, 0, 0), "score": 0.99},
        {"id": "a2", "embedding": _vec(0.99, 0.01, 0), "score": 0.98},  # near-duplicate of a
        {"id": "b", "embedding": _vec(0, 1, 0), "score": 0.50},          # very different
    ]
    out = _mmr_rerank(cands, lambda_=0.0, qvec=_vec(1, 0, 0))
    # With lambda=0 (pure diversity) the second pick should be "b" not "a2"
    assert out[0]["id"] == "a"
    assert out[1]["id"] == "b"


def test_mmr_pure_relevance_when_lambda_one():
    cands = [
        {"id": "a", "embedding": _vec(1, 0, 0), "score": 0.99},
        {"id": "b", "embedding": _vec(0, 1, 0), "score": 0.80},
        {"id": "c", "embedding": _vec(0, 0, 1), "score": 0.70},
    ]
    out = _mmr_rerank(cands, lambda_=1.0, qvec=_vec(1, 0, 0))
    # lambda=1 -> pure score order
    assert [c["id"] for c in out] == ["a", "b", "c"]
