"""Quiz generation service — RAG-grounded multiple-choice question generation."""

from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai.schemas import CompletionRequest
from app.modules.ai.service import AIService
from app.modules.rag.prompts import QUIZ_GENERATION_SYSTEM_PROMPT
from app.modules.rag.service import (
    _aircraft_context_label,
    _build_cfg,
    _resolve_sources,
    decide,
    retrieve,
)


class QuizService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def generate_quiz(
        self,
        topic: str,
        aircraft_id: UUID | None,
        module_id: str | None,
        difficulty: str,
        num_questions: int,
        user: object,
    ) -> dict:
        # 1. Build retrieval query
        retrieval_query = topic
        if module_id:
            retrieval_query = f"{topic} (module: {module_id})"

        # 2. Retrieve relevant chunks
        cfg = _build_cfg()
        hits, _ = await retrieve(self.db, retrieval_query, aircraft_id, cfg)

        # 3. Decide grounding level
        decision = decide(hits, cfg)

        # 4. Refusal short-circuit
        if decision["grounded"] == "refused":
            return {
                "topic": topic,
                "difficulty": difficulty,
                "questions": [],
                "grounded": "refused",
                "sources": [],
                "generated_count": 0,
            }

        # 5. Build prompt context
        aircraft_label = await _aircraft_context_label(self.db, aircraft_id)
        user_roles = set(getattr(user, "roles", []))
        audience_label = "instructor" if user_roles & {"admin", "instructor"} else "trainee"

        sys_prompt = QUIZ_GENERATION_SYSTEM_PROMPT.format(
            topic=topic,
            difficulty=difficulty,
            num_questions=num_questions,
            aircraft_context=aircraft_label,
            audience_label=audience_label,
        )

        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": f"Generate {num_questions} quiz questions about: {topic}"},
        ]

        # 6. Call AI
        ai_svc = AIService(self.db)
        req = CompletionRequest(
            messages=messages,
            context_citations=decision["citation_keys"],
            temperature=0.4,
            max_tokens=1200,
            cache=True,
        )
        ai_result = await ai_svc.complete(req, user_id=str(getattr(user, "id", "anonymous")))

        # 7. Parse JSON response
        questions = self._parse_questions(ai_result.get("response", ""))

        # 8. Build score lookup for source resolution
        score_lookup: dict[str, float] = {}
        for hit in hits:
            if hit.included:
                for key in hit.citation_keys:
                    score_lookup[key] = hit.score

        # 9. Resolve sources
        sources = await _resolve_sources(self.db, decision["citation_keys"], score_lookup)

        return {
            "topic": topic,
            "difficulty": difficulty,
            "questions": questions,
            "grounded": decision["grounded"],
            "sources": sources,
            "generated_count": len(questions),
        }

    @staticmethod
    def _parse_questions(raw: str) -> list[dict]:
        """Parse JSON array of questions from LLM response.

        Handles:
        - Plain JSON array
        - JSON object with a "questions" key
        - Markdown code-fenced JSON

        Returns empty list on any parse failure.
        """
        try:
            text = raw.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                # Drop first line (``` or ```json) and last line (```)
                inner = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
                text = "\n".join(inner)
            data = json.loads(text)
            if isinstance(data, list):
                return data
            if isinstance(data, dict) and "questions" in data:
                return data["questions"]
        except (json.JSONDecodeError, KeyError, ValueError):
            pass
        return []
