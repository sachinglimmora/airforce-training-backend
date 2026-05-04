import json
import uuid
from typing import Annotated

from fastapi import Depends
from fastapi.routing import APIRouter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.auth.deps import get_current_user
from app.modules.auth.schemas import CurrentUser
from app.modules.quiz.models import Quiz, QuizAttempt, QuizQuestion

router = APIRouter()

_401 = {401: {"description": "Not authenticated"}}


def _serialize_quiz(quiz: Quiz, attempts: list[QuizAttempt] | None = None) -> dict:
    trainee_attempts = attempts or []
    best = max((a.percentage for a in trainee_attempts), default=None)
    return {
        "id": str(quiz.id),
        "title": quiz.title,
        "description": quiz.description or "",
        "aircraft": quiz.aircraft,
        "system": quiz.system,
        "timeLimit": quiz.time_limit,
        "passingScore": quiz.passing_score,
        "questionCount": len(quiz.questions),
        "createdBy": str(quiz.created_by) if quiz.created_by else "system",
        "generatedBy": quiz.generated_by,
        "createdAt": quiz.created_at.isoformat(),
        "attempts": len(trainee_attempts),
        "bestScore": float(best) if best is not None else None,
    }


def _serialize_question(q: QuizQuestion) -> dict:
    return {
        "id": str(q.id),
        "type": q.question_type,
        "question": q.question,
        "options": q.options or [],
        "points": q.points,
        "difficulty": q.difficulty,
        "topic": q.topic,
    }


async def _generate_questions_with_ai(
    db: AsyncSession,
    user_id: str,
    topic: str,
    aircraft: str,
    system: str,
    count: int,
) -> list[dict]:
    """Call AI to generate quiz questions. Returns list of question dicts."""
    prompt = (
        f"Generate exactly {count} quiz questions for airforce trainees about: {topic}. "
        f"Aircraft: {aircraft}. System: {system}. "
        "Return a JSON array with this exact structure for each question:\n"
        '{"type":"multiple-choice","question":"...","options":["A","B","C","D"],'
        '"correct_answer":"A","explanation":"...","points":10,"difficulty":"medium","topic":"..."}\n'
        "Make questions technically accurate for Indian Air Force training. "
        "Use question types: multiple-choice (70%), true-false (20%), fill-blank (10%). "
        "For true-false, options are [\"True\",\"False\"]. "
        "For fill-blank, options is null. "
        "Respond with ONLY the JSON array, no other text."
    )
    from app.modules.ai.schemas import CompletionRequest, MessageIn
    from app.modules.ai.service import AIService

    svc = AIService(db)
    req = CompletionRequest(
        messages=[MessageIn(role="user", content=prompt)],
        temperature=0.6,
        max_tokens=2000,
    )
    result = await svc.complete(req, user_id)
    raw = result.get("response", "[]")

    # Extract JSON array from response
    start = raw.find("[")
    end = raw.rfind("]") + 1
    if start >= 0 and end > start:
        questions = json.loads(raw[start:end])
        return questions[:count]
    return []


def _fallback_questions(topic: str, aircraft: str, system: str, count: int) -> list[dict]:
    """Template questions used when AI is unavailable."""
    templates = [
        {
            "type": "multiple-choice",
            "question": f"What is the primary function of the {system} system on the {aircraft}?",
            "options": [
                f"To manage {system} operations",
                "To provide pilot entertainment",
                "To control external lighting",
                "To manage fuel flow only",
            ],
            "correct_answer": f"To manage {system} operations",
            "explanation": f"The {system} system is responsible for managing its respective aircraft subsystem functions.",
            "points": 10,
            "difficulty": "easy",
            "topic": topic,
        },
        {
            "type": "true-false",
            "question": f"A pre-flight inspection of the {system} system must be completed before every sortie.",
            "options": ["True", "False"],
            "correct_answer": "True",
            "explanation": "Pre-flight checks are mandatory before every flight to ensure airworthiness.",
            "points": 5,
            "difficulty": "easy",
            "topic": topic,
        },
        {
            "type": "multiple-choice",
            "question": f"Which action should a pilot take FIRST when a {system} malfunction is indicated?",
            "options": [
                "Refer to the QRH and follow abnormal procedures",
                "Ignore the warning and continue mission",
                "Immediately eject from the aircraft",
                "Land at the nearest airfield without checks",
            ],
            "correct_answer": "Refer to the QRH and follow abnormal procedures",
            "explanation": "The QRH (Quick Reference Handbook) contains prescribed procedures for all abnormal conditions.",
            "points": 10,
            "difficulty": "medium",
            "topic": topic,
        },
        {
            "type": "multiple-choice",
            "question": f"During emergency procedures related to {topic}, the pilot should prioritise:",
            "options": [
                "Aviate, Navigate, Communicate",
                "Communicate, Navigate, Aviate",
                "Navigate, Aviate, Communicate",
                "Communicate, Aviate, Navigate",
            ],
            "correct_answer": "Aviate, Navigate, Communicate",
            "explanation": "The standard priority hierarchy in emergencies is Aviate (fly the aircraft first), Navigate, then Communicate.",
            "points": 10,
            "difficulty": "medium",
            "topic": topic,
        },
        {
            "type": "true-false",
            "question": f"All {system} system parameters must be within normal limits before departure.",
            "options": ["True", "False"],
            "correct_answer": "True",
            "explanation": "All systems must be confirmed serviceable and within limits before flight.",
            "points": 5,
            "difficulty": "easy",
            "topic": topic,
        },
    ]
    return (templates * ((count // len(templates)) + 1))[:count]


@router.get(
    "",
    response_model=dict,
    summary="List available quizzes",
    responses={**_401},
    operation_id="quizzes_list",
)
async def list_quizzes(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
):
    result = await db.execute(select(Quiz))
    quizzes = result.scalars().all()

    # Get trainee's attempts for each quiz
    attempts_result = await db.execute(
        select(QuizAttempt).where(QuizAttempt.trainee_id == current_user.id)
    )
    all_attempts = attempts_result.scalars().all()
    attempts_by_quiz: dict[str, list] = {}
    for a in all_attempts:
        attempts_by_quiz.setdefault(str(a.quiz_id), []).append(a)

    return {
        "data": {
            "quizzes": [
                _serialize_quiz(q, attempts_by_quiz.get(str(q.id), []))
                for q in quizzes
            ]
        }
    }


@router.get(
    "/attempts/history",
    response_model=dict,
    summary="Get trainee's quiz attempt history",
    responses={**_401},
    operation_id="quizzes_attempts_history",
)
async def get_attempt_history(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
):
    result = await db.execute(
        select(QuizAttempt, Quiz)
        .join(Quiz, QuizAttempt.quiz_id == Quiz.id)
        .where(QuizAttempt.trainee_id == current_user.id)
        .order_by(QuizAttempt.completed_at.desc())
    )
    rows = result.all()
    attempts = [
        {
            "id": str(attempt.id),
            "quizId": str(attempt.quiz_id),
            "quizTitle": quiz.title,
            "score": attempt.score,
            "percentage": float(attempt.percentage),
            "passed": attempt.passed,
            "timeTaken": attempt.time_taken,
            "completedAt": attempt.completed_at.isoformat(),
        }
        for attempt, quiz in rows
    ]
    return {"data": {"attempts": attempts}}


@router.get(
    "/{quiz_id}",
    response_model=dict,
    summary="Get quiz with questions",
    responses={**_401},
    operation_id="quizzes_get",
)
async def get_quiz(
    quiz_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
):
    result = await db.execute(select(Quiz).where(Quiz.id == quiz_id))
    quiz = result.scalar_one_or_none()
    if not quiz:
        from app.core.exceptions import NotFound
        raise NotFound("Quiz")

    data = _serialize_quiz(quiz)
    data["questions"] = [_serialize_question(q) for q in quiz.questions]
    return {"data": data}


@router.post(
    "/{quiz_id}/submit",
    response_model=dict,
    summary="Submit quiz answers",
    responses={**_401},
    operation_id="quizzes_submit",
)
async def submit_quiz(
    quiz_id: uuid.UUID,
    body: dict,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
):
    result = await db.execute(select(Quiz).where(Quiz.id == quiz_id))
    quiz = result.scalar_one_or_none()
    if not quiz:
        from app.core.exceptions import NotFound
        raise NotFound("Quiz")

    answers: dict = body.get("answers", {})
    time_taken: int = body.get("timeTaken", 0)

    # Grade answers
    total_points = 0
    earned_points = 0
    question_results = []
    for q in quiz.questions:
        qid = str(q.id)
        user_answer = answers.get(qid, "")
        is_correct = user_answer.strip().lower() == q.correct_answer.strip().lower()
        total_points += q.points
        if is_correct:
            earned_points += q.points
        question_results.append(
            {
                "questionId": qid,
                "userAnswer": user_answer,
                "isCorrect": is_correct,
                "correctAnswer": q.correct_answer,
                "explanation": q.explanation or "",
            }
        )

    percentage = round((earned_points / total_points * 100), 1) if total_points > 0 else 0.0
    passed = percentage >= quiz.passing_score

    attempt = QuizAttempt(
        quiz_id=quiz.id,
        trainee_id=current_user.id,
        answers=answers,
        score=earned_points,
        percentage=percentage,
        passed=passed,
        time_taken=time_taken,
    )
    db.add(attempt)
    await db.commit()
    await db.refresh(attempt)

    return {
        "data": {
            "attemptId": str(attempt.id),
            "score": earned_points,
            "percentage": percentage,
            "passed": passed,
            "passingScore": quiz.passing_score,
            "results": question_results,
            "timeTaken": time_taken,
        }
    }


@router.post(
    "/generate",
    response_model=dict,
    summary="AI-generate a quiz",
    responses={**_401},
    operation_id="quizzes_generate",
)
async def generate_quiz(
    body: dict,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
):
    topic = body.get("topic", "General Aviation Knowledge")
    aircraft = body.get("aircraft", "general")
    system = body.get("system", "general")
    count = min(int(body.get("questionCount", 5)), 10)

    # Try AI generation, fall back to templates
    try:
        raw_questions = await _generate_questions_with_ai(
            db, str(current_user.id), topic, aircraft, system, count
        )
    except Exception:
        raw_questions = []

    if not raw_questions:
        raw_questions = _fallback_questions(topic, aircraft, system, count)

    # Persist the generated quiz
    quiz = Quiz(
        title=f"{topic} — {aircraft.upper()}",
        description=f"AI-generated assessment on {topic} for {aircraft} {system} system.",
        aircraft=aircraft,
        system=system,
        time_limit=15,
        passing_score=70,
        created_by=current_user.id,
        generated_by="ai",
    )
    db.add(quiz)
    await db.flush()

    questions = []
    for idx, q in enumerate(raw_questions):
        question = QuizQuestion(
            quiz_id=quiz.id,
            ordinal=idx,
            question_type=q.get("type", "multiple-choice"),
            question=q.get("question", ""),
            options=q.get("options"),
            correct_answer=q.get("correct_answer", ""),
            explanation=q.get("explanation"),
            points=int(q.get("points", 10)),
            difficulty=q.get("difficulty", "medium"),
            topic=q.get("topic", topic),
        )
        db.add(question)
        questions.append(question)

    await db.commit()
    await db.refresh(quiz)

    data = _serialize_quiz(quiz)
    data["questions"] = [_serialize_question(q) for q in questions]
    return {"data": data}
