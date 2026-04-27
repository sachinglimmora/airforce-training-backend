"""Wraps AIService.embed() + dim validation. See spec §8."""


class EmbedDimensionMismatch(Exception):
    pass


async def embed_and_validate(texts: list[str]) -> list[list[float]]:
    raise NotImplementedError
