from typing import Annotated

from fastapi import Depends
from fastapi.routing import APIRouter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.auth.deps import get_current_user
from app.modules.auth.models import User
from app.modules.auth.schemas import CurrentUser
from app.modules.competency.models import Evaluation

router = APIRouter()

_401 = {401: {"description": "Not authenticated"}}

_GRADE_RATING = {
    "excellent": 5,
    "satisfactory": 4,
    "needs_improvement": 2,
    "unsatisfactory": 1,
}

_CATEGORY_MAP = {
    "procedural_compliance": "Technical",
    "crm": "CRM",
    "decision_making": "Practical",
    "emergency": "Emergency",
    "technical": "Technical",
    "practical": "Practical",
}


@router.get(
    "",
    response_model=dict,
    summary="Get trainee feedback / evaluations",
    description=(
        "Returns all instructor evaluations for the authenticated trainee, "
        "formatted as feedback entries with rating, category, and improvement notes."
    ),
    responses={**_401},
    operation_id="feedback_list",
)
async def list_feedback(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    # Find evaluations for sessions belonging to this trainee
    from app.modules.analytics.models import TrainingSession

    ts_result = await db.execute(
        select(TrainingSession).where(TrainingSession.trainee_id == current_user.id)
    )
    my_sessions = {str(s.id): s for s in ts_result.scalars().all()}

    if my_sessions:
        ev_result = await db.execute(
            select(Evaluation).where(
                Evaluation.session_id.in_(list(my_sessions.keys()))
            ).order_by(Evaluation.evaluated_at.desc())
        )
        evaluations = ev_result.scalars().all()
    else:
        evaluations = []

    entries = []
    for ev in evaluations:
        # Fetch evaluator name
        evaluator = (
            await db.execute(select(User).where(User.id == ev.evaluator_id))
        ).scalar_one_or_none()
        evaluator_name = evaluator.full_name if evaluator else "Instructor"

        # Derive category from rubric criteria keys
        category = "Technical"
        if ev.scores:
            for key in ev.scores.keys():
                mapped = _CATEGORY_MAP.get(key.lower().replace(" ", "_"))
                if mapped:
                    category = mapped
                    break

        rating = _GRADE_RATING.get(ev.grade or "satisfactory", 3)

        # Build improvements from score breakdown
        improvements = []
        if ev.scores:
            for criterion, score in ev.scores.items():
                if isinstance(score, (int, float)) and score < 7:
                    improvements.append(f"Improve {criterion.replace('_', ' ').title()}")

        entries.append(
            {
                "id": str(ev.id),
                "instructor": evaluator_name,
                "date": ev.evaluated_at.strftime("%Y-%m-%d"),
                "category": category,
                "rating": rating,
                "feedback": ev.comments or f"Session evaluation — grade: {ev.grade or 'N/A'}",
                "improvements": improvements,
            }
        )

    # Derive strengths and weaknesses from evaluation scores
    all_scores: dict[str, list[float]] = {}
    for ev in evaluations:
        if ev.scores:
            for criterion, score in ev.scores.items():
                if isinstance(score, (int, float)):
                    all_scores.setdefault(criterion, []).append(float(score))

    strengths = [
        k.replace("_", " ").title()
        for k, vals in all_scores.items()
        if (sum(vals) / len(vals)) >= 8.0
    ]
    weaknesses = [
        k.replace("_", " ").title()
        for k, vals in all_scores.items()
        if (sum(vals) / len(vals)) < 6.0
    ]

    return {
        "data": {
            "entries": entries,
            "strengths": strengths or [],
            "weaknesses": weaknesses or [],
        }
    }
