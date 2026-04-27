from dataclasses import dataclass

from app.modules.rag.grounder import decide


@dataclass
class FakeHit:
    score: float
    citation_keys: list[str]
    content: str = "x"
    chunk_id: str = "id"
    section_id: str = "sec"
    page_number: int | None = None
    mmr_rank: int = 0
    included: bool = False


CFG = {
    "include_threshold": 0.65,
    "soft_include_threshold": 0.60,
    "suggest_threshold": 0.50,
    "max_chunks": 5,
}


def test_strong_when_hits_above_high():
    hits = [FakeHit(0.9, ["a"]), FakeHit(0.8, ["b"]), FakeHit(0.4, ["c"])]
    out = decide(hits, CFG)
    assert out["grounded"] == "strong"
    assert sorted(out["citation_keys"]) == ["a", "b"]


def test_soft_when_top_in_rescue_band():
    hits = [FakeHit(0.62, ["a"]), FakeHit(0.55, ["b"]), FakeHit(0.40, ["c"])]
    out = decide(hits, CFG)
    assert out["grounded"] == "soft"
    assert out["citation_keys"] == ["a"]


def test_refused_when_no_hit_above_soft():
    hits = [FakeHit(0.55, ["a"]), FakeHit(0.52, ["b"]), FakeHit(0.40, ["c"])]
    out = decide(hits, CFG)
    assert out["grounded"] == "refused"
    assert out["citation_keys"] == []
    assert sorted([s["citation_key"] for s in out["suggestions"]]) == ["a", "b"]


def test_refused_with_no_suggestions_when_all_below_low():
    hits = [FakeHit(0.40, ["a"]), FakeHit(0.30, ["b"])]
    out = decide(hits, CFG)
    assert out["grounded"] == "refused"
    assert out["suggestions"] == []


def test_max_chunks_cap_in_strong():
    hits = [FakeHit(0.9, [f"k{i}"]) for i in range(10)]
    out = decide(hits, CFG)
    assert len(out["citation_keys"]) == 5
