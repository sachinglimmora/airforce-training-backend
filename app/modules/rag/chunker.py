"""Section tree -> ContentChunk records (3-rule hybrid). See spec §7."""

import tiktoken

_ENCODER = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    if not text:
        return 0
    return len(_ENCODER.encode(text))


def chunk_section_tree(source) -> list:
    raise NotImplementedError
