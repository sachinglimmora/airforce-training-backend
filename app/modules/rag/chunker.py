"""Section tree -> ContentChunk records (3-rule hybrid). See spec §7."""

from dataclasses import dataclass, field

import tiktoken
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import get_settings

_ENCODER = tiktoken.get_encoding("cl100k_base")
_settings = get_settings()


def count_tokens(text: str) -> int:
    if not text:
        return 0
    return len(_ENCODER.encode(text))


def _heading_prefix(section) -> str:
    return f"## {section.section_number} {section.title}\n\n"


def _format_chunk(text: str, section) -> str:
    return f"{_heading_prefix(section)}{text}".strip()


def _splitter():
    return RecursiveCharacterTextSplitter(
        separators=["\n\n", "\n", ". ", " "],
        chunk_size=_settings.RAG_CHUNK_TOKENS_MAX * 4,        # rough char budget for token target
        chunk_overlap=_settings.RAG_CHUNK_OVERLAP_TOKENS * 4,
        length_function=len,
    )


def _chunk_one_section(section, ordinal_start: int) -> list[dict]:
    body = section.content_markdown or ""
    if not body.strip():
        return []
    if section.reference is None:
        # No citation key -> can't be cited, skip
        return []

    if count_tokens(body) <= _settings.RAG_CHUNK_TOKENS_MAX:
        return [{
            "section_id": section.id,
            "citation_keys": [section.reference.citation_key],
            "content": _format_chunk(body, section),
            "token_count": count_tokens(_format_chunk(body, section)),
            "ordinal": ordinal_start,
            "page_number": section.page_number,
        }]

    splitter = _splitter()
    pieces = splitter.split_text(body)
    chunks = []
    for i, piece in enumerate(pieces):
        formatted = _format_chunk(piece, section)
        chunks.append({
            "section_id": section.id,
            "citation_keys": [section.reference.citation_key],
            "content": formatted,
            "token_count": count_tokens(formatted),
            "ordinal": ordinal_start + i,
            "page_number": section.page_number,
        })
    return chunks


def _merge_small_siblings(chunks: list[dict]) -> list[dict]:
    threshold = _settings.RAG_CHUNK_TOKENS_MIN_MERGE
    merged: list[dict] = []
    i = 0
    while i < len(chunks):
        current = chunks[i]
        # only merge consecutive single-citation chunks both under threshold
        if (
            i + 1 < len(chunks)
            and current["token_count"] < threshold
            and chunks[i + 1]["token_count"] < threshold
            and len(current["citation_keys"]) == 1
            and len(chunks[i + 1]["citation_keys"]) == 1
        ):
            nxt = chunks[i + 1]
            merged.append({
                "section_id": current["section_id"],  # arbitrary; first wins
                "citation_keys": current["citation_keys"] + nxt["citation_keys"],
                "content": current["content"] + "\n\n" + nxt["content"],
                "token_count": current["token_count"] + nxt["token_count"],
                "ordinal": current["ordinal"],
                "page_number": current["page_number"],
            })
            i += 2
        else:
            merged.append(current)
            i += 1
    # Re-sequence ordinals
    for idx, c in enumerate(merged):
        c["ordinal"] = idx
    return merged


def chunk_section_tree(source) -> list[dict]:
    """Walk the section tree and produce a flat list of chunk dicts.

    Each dict has: section_id, citation_keys (list[str]), content, token_count,
    ordinal, page_number.
    """
    chunks: list[dict] = []

    def walk(sections):
        for sec in sections:
            new = _chunk_one_section(sec, ordinal_start=len(chunks))
            chunks.extend(new)
            if getattr(sec, "children", None):
                walk(sec.children)

    walk(source.sections)
    return _merge_small_siblings(chunks)
