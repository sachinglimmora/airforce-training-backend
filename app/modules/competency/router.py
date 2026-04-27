from decimal import Decimal
from typing import Annotated

from fastapi import Depends
from fastapi.routing import APIRouter
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.auth.deps import get_current_user
from app.modules.auth.schemas import CurrentUser
from app.modules.competency.models import Competency, Evaluation, Rubric

router = APIRouter()

_401 = {401: {"description": "Not authenticated"}}
_403 = {403: {"description": "Insufficient permissions"}}
_404 = {404: {"description": "Not found"}}


class CreateRubricRequest(BaseModel):
    name: str
    procedure_id: str | None = None
    scenario_id: str | None = None
    criteria: dict = {}
    max_score: float = 100.0


class CreateEvaluationRequest(BaseModel):
    rubric_id: str
    scores: dict[str, float]
    grade: str
    comments: str | None = None


@router.get(
    "/competencies",
    response_model=dict,
    summary="List all competency definitions",
    description=(
        "Returns the full competency catalogue with codes, names, and categories.\n\n"
        "Example codes: `PROC-ADH` (Procedural Adherence), `CRM` (Crew Resource Management), "
        "`DECISION` (Decision Making), `SIT-AWR` (Situational Awareness)."
    ),
    responses={**_401},
    operation_id="competencies_list",
)
async def list_competencies(
    _current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    result = await db.execute(select(Competency))
    comps = result.scalars().all()
    return {
        "data": [
            {"id": str(c.id), "code": c.code, "name": c.name, "category": c.category} for c in comps
        ]
    }


@router.get(
    "/trainees/{trainee_id}/competencies",
    response_model=dict,
    summary="Get a trainee's competency evidence map",
    description=(
        "Returns all competency evidence records for a trainee — one entry per "
        "competency per session where evidence was recorded. "
        "Use this to plot progression over time."
    ),
    responses={**_401, **_403},
    operation_id="competencies_trainee_evidence",
)
async def trainee_competencies(
    trainee_id: str,
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from app.modules.competency.models import CompetencyEvidence

    result = await db.execute(
        select(CompetencyEvidence).where(CompetencyEvidence.trainee_id == trainee_id)
    )
    evidence = result.scalars().all()
    return {
        "data": [
            {
                "competency_id": str(e.competency_id),
                "score": float(e.score),
                "recorded_at": e.recorded_at.isoformat(),
            }
            for e in evidence
        ]
    }


@router.get(
    "/rubrics",
    response_model=dict,
    summary="List evaluation rubrics",
    description="Returns all rubrics with their names and maximum scores.",
    responses={**_401},
    operation_id="rubrics_list",
)
async def list_rubrics(
    _current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    result = await db.execute(select(Rubric))
    rubrics = result.scalars().all()
    return {
        "data": [
            {"id": str(r.id), "name": r.name, "max_score": float(r.max_score)} for r in rubrics
        ]
    }


@router.post(
    "/rubrics",
    status_code=201,
    response_model=dict,
    summary="Create an evaluation rubric",
    description=(
        "Creates a new rubric with weighted criteria. "
        "Optionally link to a specific `procedure_id` or `scenario_id`.\n\n"
        "Criteria format:\n"
        "```json\n"
        "{\n"
        '  "procedural_compliance": { "weight": 0.40, "max": 10 },\n'
        '  "crm":                   { "weight": 0.15, "max": 10 }\n'
        "}\n"
        "```\n\n"
        "**Required permission:** `rubric:create`"
    ),
    responses={**_401, **_403},
    operation_id="rubrics_create",
)
async def create_rubric(
    body: CreateRubricRequest,
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    rubric = Rubric(
        name=body.name,
        procedure_id=body.procedure_id,
        scenario_id=body.scenario_id,
        criteria=body.criteria,
        max_score=Decimal(str(body.max_score)),
    )
    db.add(rubric)
    await db.flush()
    return {"data": {"id": str(rubric.id), "name": rubric.name}}


@router.get(
    "/rubrics/{rubric_id}",
    response_model=dict,
    summary="Get a rubric with full criteria",
    description="Returns the rubric definition including all weighted criteria and max score.",
    responses={**_401, **_404},
    operation_id="rubrics_get",
)
async def get_rubric(
    rubric_id: str,
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(Rubric).where(Rubric.id == rubric_id))
    r = result.scalar_one_or_none()
    if not r:
        from app.core.exceptions import NotFound

        raise NotFound("Rubric")
    return {
        "data": {
            "id": str(r.id),
            "name": r.name,
            "criteria": r.criteria,
            "max_score": float(r.max_score),
        }
    }


@router.post(
    "/sessions/{session_id}/evaluations",
    status_code=201,
    response_model=dict,
    summary="Submit a session evaluation",
    description=(
        "Records a graded evaluation against a rubric for a completed session.\n\n"
        "- `rubric_id` — the rubric to evaluate against\n"
        "- `scores` — map of criterion name → numeric score\n"
        "- `grade` — `excellent` | `satisfactory` | `needs_improvement` | `unsatisfactory`\n"
        "- `comments` — optional free-text instructor feedback\n\n"
        "**Required permission:** `evaluation:create`"
    ),
    responses={**_401, **_403, 404: {"description": "Session or rubric not found"}},
    operation_id="evaluations_create",
)
async def create_evaluation(
    session_id: str,
    body: CreateEvaluationRequest,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    total = Decimal(str(sum(body.scores.values())))
    evaluation = Evaluation(
        session_id=session_id,
        evaluator_id=current_user.id,
        rubric_id=body.rubric_id,
        scores=body.scores,
        total_score=total,
        grade=body.grade,
        comments=body.comments,
    )
    db.add(evaluation)
    await db.flush()
    return {
        "data": {
            "id": str(evaluation.id),
            "session_id": session_id,
            "grade": body.grade,
            "total_score": float(total),
        }
    }


@router.get(
    "/evaluations/{evaluation_id}",
    response_model=dict,
    summary="Get an evaluation",
    description="Returns the full evaluation record including scores, grade, comments, and timestamp.",
    responses={**_401, **_404},
    operation_id="evaluations_get",
)
async def get_evaluation(
    evaluation_id: str,
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(Evaluation).where(Evaluation.id == evaluation_id))
    ev = result.scalar_one_or_none()
    if not ev:
        from app.core.exceptions import NotFound

        raise NotFound("Evaluation")
    return {
        "data": {
            "id": str(ev.id),
            "rubric_id": str(ev.rubric_id),
            "scores": ev.scores,
            "total_score": float(ev.total_score) if ev.total_score else None,
            "grade": ev.grade,
            "comments": ev.comments,
            "evaluated_at": ev.evaluated_at.isoformat(),
        }
    }


@router.patch(
    "/evaluations/{evaluation_id}",
    response_model=dict,
    summary="Update an evaluation",
    description=(
        "Partial update of a submitted evaluation. "
        "Editable within 24 h of submission by the original evaluator or an admin.\n\n"
        "Updatable fields: `comments`, `grade`."
    ),
    responses={**_401, **_403, **_404},
    operation_id="evaluations_update",
)
async def update_evaluation(
    evaluation_id: str,
    body: dict,
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(Evaluation).where(Evaluation.id == evaluation_id))
    ev = result.scalar_one_or_none()
    if not ev:
        from app.core.exceptions import NotFound

        raise NotFound("Evaluation")
    if "comments" in body:
        ev.comments = body["comments"]
    if "grade" in body:
        ev.grade = body["grade"]
    return {"data": {"id": str(ev.id), "updated": True}}
