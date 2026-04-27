"""Wraps AIService.embed() + dim validation. See spec §8."""

from app.config import get_settings

_settings = get_settings()


class EmbedDimensionMismatch(Exception):
    pass


async def embed_and_validate(texts: list[str]) -> list[list[float]]:
    """Embed texts via the AI gateway. Raises EmbedDimensionMismatch on dim mismatch."""
    from app.database import AsyncSessionLocal
    from app.modules.ai.service import AIService

    async with AsyncSessionLocal() as db:
        svc = AIService(db)
        result = await svc.embed(texts, model=_settings.EMBEDDING_MODEL_HINT)

    embeddings = result["embeddings"]
    for i, vec in enumerate(embeddings):
        if len(vec) != _settings.EMBEDDING_DIM:
            raise EmbedDimensionMismatch(
                f"Expected dim={_settings.EMBEDDING_DIM}, got dim={len(vec)} "
                f"from model={result['model']}, text index {i}"
            )
    return embeddings
