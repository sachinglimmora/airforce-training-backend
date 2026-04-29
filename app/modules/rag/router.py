import uuid
from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.routing import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.modules.auth.deps import get_current_user
from app.modules.auth.schemas import CurrentUser
from app.modules.rag.grounder import decide
from app.modules.rag.retriever import retrieve
from app.modules.rag.schemas import HitOut, RagQueryRequest, RagQueryResponse

router = APIRouter()
_settings = get_settings()


@router.post(
    "/query",
    response_model=dict,
    summary="Retrieve grounded citations for a query (debug)",
    description=(
        "Standalone retrieval endpoint — returns the citation_keys that "
        "would be sent to the AI gateway, plus grounding decision + suggestions. "
        "Used for tuning thresholds and debugging.\n\n"
        "**Required role:** instructor or admin."
    ),
    operation_id="rag_query",
)
async def rag_query(
    body: RagQueryRequest,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if not (set(current_user.roles) & {"admin", "instructor"}):
        raise HTTPException(status_code=403, detail="Admin or instructor required")
    cfg = {
        "top_k": body.top_k or _settings.RAG_TOP_K,
        "mmr_lambda": _settings.RAG_MMR_LAMBDA,
        "include_threshold": _settings.RAG_INCLUDE_THRESHOLD,
        "soft_include_threshold": _settings.RAG_SOFT_INCLUDE_THRESHOLD,
        "suggest_threshold": _settings.RAG_SUGGEST_THRESHOLD,
        "max_chunks": _settings.RAG_MAX_CHUNKS,
    }
    hits, _latency = await retrieve(db, body.query, body.aircraft_id, cfg)
    decision = decide(hits, cfg)

    hits_out = [
        HitOut(
            citation_key=h.citation_keys[0] if h.citation_keys else "",
            score=h.score,
            included=h.included,
            mmr_rank=h.mmr_rank,
        )
        for h in hits
    ]
    suggestions_out = [
        HitOut(
            citation_key=s["citation_key"],
            score=s["score"],
            included=False,
            mmr_rank=-1,
        )
        for s in decision["suggestions"]
    ]
    return {"data": RagQueryResponse(
        grounded=decision["grounded"],
        citation_keys=decision["citation_keys"],
        hits=hits_out,
        suggestions=suggestions_out,
    ).model_dump()}


# ─── Moderation admin endpoints ──────────────────────────────────────────────


def _require_admin_or_instructor(current_user: CurrentUser) -> None:
    if not (set(current_user.roles) & {"admin", "instructor"}):
        raise HTTPException(status_code=403, detail="Admin or instructor required")


def _require_admin(current_user: CurrentUser) -> None:
    if "admin" not in current_user.roles:
        raise HTTPException(status_code=403, detail="Admin required")


@router.get(
    "/moderation/rules",
    response_model=dict,
    summary="List moderation rules (admin/instructor)",
    operation_id="moderation_rules_list",
)
async def list_moderation_rules(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    category: str | None = None,
    active: bool | None = None,
    limit: int = 100,
    offset: int = 0,
):
    _require_admin_or_instructor(current_user)
    from sqlalchemy import select

    from app.modules.rag.models import ModerationRule
    from app.modules.rag.schemas import ModerationRuleOut
    q = select(ModerationRule)
    if category is not None:
        q = q.where(ModerationRule.category == category)
    if active is not None:
        q = q.where(ModerationRule.active == active)
    q = q.order_by(ModerationRule.created_at.desc()).limit(limit).offset(offset)
    rows = (await db.execute(q)).scalars().all()
    return {"data": [ModerationRuleOut.model_validate(r).model_dump(mode="json") for r in rows]}


@router.post(
    "/moderation/rules",
    response_model=dict,
    status_code=201,
    summary="Create a moderation rule (admin/instructor)",
    operation_id="moderation_rules_create",
)
async def create_moderation_rule(
    body: dict,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    _require_admin_or_instructor(current_user)
    import re as _re

    from app.modules.rag.models import ModerationRule
    from app.modules.rag.moderator import invalidate_cache
    from app.modules.rag.schemas import ModerationRuleIn, ModerationRuleOut

    payload = ModerationRuleIn.model_validate(body)
    # Validate the regex compiles before persisting (prevents bad patterns sneaking in)
    if payload.pattern_type == "regex":
        try:
            _re.compile(payload.pattern)
        except _re.error as exc:
            raise HTTPException(status_code=400, detail=f"Invalid regex: {exc}")

    rule = ModerationRule(
        category=payload.category,
        pattern=payload.pattern,
        pattern_type=payload.pattern_type,
        action=payload.action,
        severity=payload.severity,
        description=payload.description,
        active=payload.active,
        created_by=uuid.UUID(str(current_user.id)),
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    await invalidate_cache()
    return {"data": ModerationRuleOut.model_validate(rule).model_dump(mode="json")}


@router.get(
    "/moderation/rules/{rule_id}",
    response_model=dict,
    summary="Get a single moderation rule (admin/instructor)",
    operation_id="moderation_rules_get",
)
async def get_moderation_rule(
    rule_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    _require_admin_or_instructor(current_user)
    from sqlalchemy import select

    from app.modules.rag.models import ModerationRule
    from app.modules.rag.schemas import ModerationRuleOut
    rule = (await db.execute(select(ModerationRule).where(ModerationRule.id == rule_id))).scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"data": ModerationRuleOut.model_validate(rule).model_dump(mode="json")}


@router.patch(
    "/moderation/rules/{rule_id}",
    response_model=dict,
    summary="Update a moderation rule (admin/instructor)",
    operation_id="moderation_rules_update",
)
async def update_moderation_rule(
    rule_id: uuid.UUID,
    body: dict,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    _require_admin_or_instructor(current_user)
    import re as _re

    from sqlalchemy import select

    from app.modules.rag.models import ModerationRule
    from app.modules.rag.moderator import invalidate_cache
    from app.modules.rag.schemas import ModerationRuleOut, ModerationRuleUpdate

    payload = ModerationRuleUpdate.model_validate(body)
    rule = (await db.execute(select(ModerationRule).where(ModerationRule.id == rule_id))).scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    update_data = payload.model_dump(exclude_unset=True)
    # Validate new regex if pattern is being updated
    new_pattern = update_data.get("pattern", rule.pattern)
    new_pattern_type = update_data.get("pattern_type", rule.pattern_type)
    if "pattern" in update_data or "pattern_type" in update_data:
        if new_pattern_type == "regex":
            try:
                _re.compile(new_pattern)
            except _re.error as exc:
                raise HTTPException(status_code=400, detail=f"Invalid regex: {exc}")

    for k, v in update_data.items():
        setattr(rule, k, v)
    await db.commit()
    await db.refresh(rule)
    await invalidate_cache()
    return {"data": ModerationRuleOut.model_validate(rule).model_dump(mode="json")}


@router.delete(
    "/moderation/rules/{rule_id}",
    response_model=dict,
    summary="Delete a moderation rule (soft by default; ?hard=true requires admin)",
    operation_id="moderation_rules_delete",
)
async def delete_moderation_rule(
    rule_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    hard: bool = False,
):
    _require_admin_or_instructor(current_user)
    from sqlalchemy import select

    from app.modules.rag.models import ModerationRule
    from app.modules.rag.moderator import invalidate_cache
    rule = (await db.execute(select(ModerationRule).where(ModerationRule.id == rule_id))).scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    if hard:
        _require_admin(current_user)  # hard delete: admin only
        await db.delete(rule)
    else:
        rule.active = False
    await db.commit()
    await invalidate_cache()
    return {"data": {"id": str(rule_id), "deleted": "hard" if hard else "soft"}}


@router.get(
    "/moderation/logs",
    response_model=dict,
    summary="List moderation log entries (admin/instructor audit view)",
    operation_id="moderation_logs_list",
)
async def list_moderation_logs(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    category: str | None = None,
    severity: str | None = None,
    session_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    limit: int = 100,
    offset: int = 0,
):
    _require_admin_or_instructor(current_user)
    from sqlalchemy import select

    from app.modules.rag.models import ModerationLog
    from app.modules.rag.schemas import ModerationLogOut
    q = select(ModerationLog)
    if category is not None:
        q = q.where(ModerationLog.category == category)
    if severity is not None:
        q = q.where(ModerationLog.severity == severity)
    if session_id is not None:
        q = q.where(ModerationLog.session_id == session_id)
    if user_id is not None:
        q = q.where(ModerationLog.user_id == user_id)
    q = q.order_by(ModerationLog.created_at.desc()).limit(limit).offset(offset)
    rows = (await db.execute(q)).scalars().all()
    return {"data": [ModerationLogOut.model_validate(r).model_dump(mode="json") for r in rows]}
