"""RAG orchestration: rewrite -> retrieve -> ground -> AIService.complete -> persist."""


class RAGService:
    def __init__(self, db):
        self.db = db

    async def answer(self, query: str, session_id, user) -> dict:
        raise NotImplementedError
