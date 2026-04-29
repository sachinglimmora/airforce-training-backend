from dataclasses import dataclass, field
from uuid import uuid4

from app.modules.rag.chunker import chunk_section_tree, count_tokens


def test_count_tokens_returns_zero_for_empty():
    assert count_tokens("") == 0


def test_count_tokens_returns_positive_for_text():
    assert count_tokens("hello world") > 0


def test_count_tokens_grows_with_length():
    assert count_tokens("a b c d e f g h") > count_tokens("a b")


@dataclass
class FakeRef:
    citation_key: str


@dataclass
class FakeSection:
    id: object
    section_number: str
    title: str
    content_markdown: str
    page_number: int | None = None
    children: list = field(default_factory=list)
    parent_section_id: object | None = None
    reference: FakeRef | None = None
    ordinal: int = 0


@dataclass
class FakeSource:
    id: object
    sections: list


def _section(num, title, body, key, page=1):
    sid = uuid4()
    return FakeSection(
        id=sid, section_number=num, title=title, content_markdown=body,
        page_number=page, reference=FakeRef(citation_key=key),
    )


def test_small_section_becomes_one_chunk():
    src = FakeSource(id=uuid4(), sections=[_section("3.2.1", "Engine Start", "Short body.", "K-3.2.1")])
    chunks = chunk_section_tree(src)
    assert len(chunks) == 1
    assert chunks[0]["citation_keys"] == ["K-3.2.1"]
    assert chunks[0]["section_id"] == src.sections[0].id
    assert chunks[0]["ordinal"] == 0
    assert "Engine Start" in chunks[0]["content"]


def test_large_section_is_sub_split():
    big_body = "lorem ipsum " * 800  # >> 800 tokens
    src = FakeSource(id=uuid4(), sections=[_section("3.2.1", "Big", big_body, "K-3.2.1")])
    chunks = chunk_section_tree(src)
    assert len(chunks) > 1
    assert all(c["citation_keys"] == ["K-3.2.1"] for c in chunks)
    assert [c["ordinal"] for c in chunks] == list(range(len(chunks)))


def test_walks_children():
    parent = _section("3", "Parent", "Parent body.", "K-3")
    child = _section("3.1", "Child", "Child body.", "K-3.1")
    parent.children = [child]
    src = FakeSource(id=uuid4(), sections=[parent])
    chunks = chunk_section_tree(src)
    keys = sorted({k for c in chunks for k in c["citation_keys"]})
    assert keys == ["K-3", "K-3.1"]


def test_tiny_adjacent_siblings_merge():
    parent = _section("3", "Parent", "", "K-3")
    a = _section("3.1", "A", "tiny.", "K-3.1")
    b = _section("3.2", "B", "also tiny.", "K-3.2")
    parent.children = [a, b]
    src = FakeSource(id=uuid4(), sections=[parent])
    chunks = chunk_section_tree(src)
    # parent has empty body -> 0 chunks; a and b should merge
    merged = [c for c in chunks if len(c["citation_keys"]) > 1]
    assert len(merged) == 1
    assert sorted(merged[0]["citation_keys"]) == ["K-3.1", "K-3.2"]
