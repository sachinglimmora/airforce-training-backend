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


@router.get("/competencies", summary="List competencies")
async def list_competencies(
    current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    result = await db.execute(select(Competency))
    comps = result.scalars().all()
    return {
        "data": [
            {"id": str(c.id), "code": c.code, "name": c.name, "category": c.category}
            for c in comps
        ]
    }


@router.get("/trainees/{trainee_id}/competencies", summary="Trainee competency evidence map")
async def trainee_competencies(
    trainee_id: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
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


@router.get("/rubrics", summary="List rubrics")
async def list_rubrics(
    current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    result = await db.execute(select(Rubric))
    rubrics = result.scalars().all()
    return {"data": [{"id": str(r.id), "name": r.name, "max_score": float(r.max_score)} for r in rubrics]}


@router.post("/rubrics", status_code=201, summary="Create rubric")
async def create_rubric(
    body: CreateRubricRequest,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
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


@router.get("/rubrics/{rubric_id}", summary="Get rubric")
async def get_rubric(
    rubric_id: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(Rubric).where(Rubric.id == rubric_id))
    r = result.scalar_one_or_none()
    if not r:
        from app.core.exceptions import NotFound
        raise NotFound("Rubric")
    return {"data": {"id": str(r.id), "name": r.name, "criteria": r.criteria, "max_score": float(r.max_score)}}


@router.post("/sessions/{session_id}/evaluations", status_code=201, summary="Submit evaluation")
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


@router.get("/evaluations/{evaluation_id}", summary="Get evaluation")
async def get_evaluation(
    evaluation_id: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
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


@router.patch("/evaluations/{evaluation_id}", summary="Update evaluation")
async def update_evaluation(
    evaluation_id: str,
    body: dict,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
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
