"""Admin LLM Learning Center — READ ONLY research hub.

Prefix: /api/v1/admin/llm-learning
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import require_admin
from stock_platform.auth.deps import AuthenticatedUser, get_current_user
from stock_platform.database.session import get_db_session
from stock_platform.operation.dual_llm.markets import MARKET_UPBIT, normalize_market
from stock_platform.operation.llm_learning_center.assistant import ask_assistant, redact_secrets
from stock_platform.operation.llm_learning_center.entities import (
    LlmLearningAssistantMessageEntity,
    LlmLearningUserCommentEntity,
    REVIEW_STATUS_USER_REVIEWED,
    VALID_FEEDBACK_LABELS,
)
from stock_platform.operation.llm_learning_center.service import (
    MARKET_ALL,
    build_forward_shadow_panel,
    build_learning_stages,
    build_lora_readiness,
    build_market_samples,
    build_quality_panel,
    build_summary,
    build_teacher_findings,
)

router = APIRouter(
    prefix="/api/v1/admin/llm-learning",
    tags=["Admin LLM Learning Center"],
    dependencies=[Depends(require_admin)],
)


def _parse_market(market: str | None) -> str:
    if not market or market.upper() == MARKET_ALL:
        return MARKET_ALL
    m = normalize_market(market)
    if m is None:
        raise HTTPException(status_code=400, detail="INVALID_MARKET")
    return m


class AskBody(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    market: str | None = None
    session_id: str | None = None
    use_llm: bool = True


class CommentBody(BaseModel):
    market: str
    symbol: str | None = None
    related_analysis_id: int | None = None
    related_prediction_id: int | None = None
    related_shadow_id: int | None = None
    comment: str = Field(min_length=1, max_length=4000)
    label: str


@router.get("/summary")
def get_llm_learning_summary(
    market: str | None = Query(default=MARKET_ALL),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    m = _parse_market(market)
    payload = build_summary(session, market=m)
    payload["REAL_ORDER_MUTATION"] = 0
    payload["LLM_REAL_GATE_MUTATION"] = 0
    return payload


@router.get("/samples")
def get_llm_learning_samples(
    market: str = Query(default=MARKET_UPBIT),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    m = normalize_market(market)
    if m is None:
        raise HTTPException(status_code=400, detail="INVALID_MARKET")
    return build_market_samples(session, market=m)


@router.get("/learning-stages")
def get_llm_learning_stages(
    market: str | None = Query(default=MARKET_ALL),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    return build_learning_stages(session, market=_parse_market(market))


@router.get("/quality")
def get_llm_learning_quality(
    market: str | None = Query(default=MARKET_ALL),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    return build_quality_panel(session, market=_parse_market(market))


@router.get("/teacher-reviews")
def get_llm_learning_teacher_reviews(
    market: str | None = Query(default=MARKET_ALL),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    return build_teacher_findings(
        session, market=_parse_market(market), limit=limit, offset=offset
    )


@router.get("/forward-shadow")
def get_llm_learning_forward_shadow(
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    return build_forward_shadow_panel(session)


@router.get("/lora-readiness")
def get_llm_learning_lora_readiness(
    market: str | None = Query(default=MARKET_ALL),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    return build_lora_readiness(session, market=_parse_market(market))


@router.post("/ask")
def post_llm_learning_ask(
    body: AskBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Read-only assistant — no trading mutation."""

    m = _parse_market(body.market)
    result = ask_assistant(
        session,
        question=body.question,
        market=m,
        use_llm=body.use_llm,
    )
    ent = LlmLearningAssistantMessageEntity(
        session_id=body.session_id,
        market_scope=m,
        intent=str(result.get("intent") or "overview"),
        question=redact_secrets(body.question),
        answer_json=result.get("answer") if isinstance(result.get("answer"), dict) else {},
        context_refs_json=result.get("context_refs")
        if isinstance(result.get("context_refs"), dict)
        else {},
        model=result.get("model"),
        created_by=f"admin:{user.username}",
    )
    session.add(ent)
    session.commit()
    session.refresh(ent)
    result["message_id"] = int(ent.message_id)
    result["conversation_saved"] = True
    return result


@router.get("/conversations")
def list_llm_learning_conversations(
    limit: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    rows = list(
        session.scalars(
            select(LlmLearningAssistantMessageEntity)
            .where(LlmLearningAssistantMessageEntity.deleted_at.is_(None))
            .order_by(desc(LlmLearningAssistantMessageEntity.created_at))
            .limit(limit)
        )
    )
    return {
        "schema": "llm_learning_conversations_v1",
        "items": [
            {
                "message_id": int(r.message_id),
                "intent": r.intent,
                "question": r.question,
                "answer": r.answer_json,
                "context_refs": r.context_refs_json,
                "model": r.model,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
        "total": len(rows),
    }


@router.delete("/conversations/{message_id}")
def delete_llm_learning_conversation(
    message_id: int,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    ent = session.get(LlmLearningAssistantMessageEntity, message_id)
    if ent is None or ent.deleted_at is not None:
        return {"ok": False, "error": "NOT_FOUND"}
    ent.deleted_at = datetime.now(timezone.utc)
    session.commit()
    return {"ok": True, "message_id": message_id}


@router.post("/comments")
def post_llm_learning_comment(
    body: CommentBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """User research comment — USER_REVIEWED, not auto GOLD."""

    m = normalize_market(body.market)
    if m is None:
        raise HTTPException(status_code=400, detail="INVALID_MARKET")
    label = body.label.upper().strip()
    if label not in VALID_FEEDBACK_LABELS:
        raise HTTPException(status_code=400, detail="INVALID_LABEL")

    ent = LlmLearningUserCommentEntity(
        market=m,
        symbol=body.symbol,
        related_analysis_id=body.related_analysis_id,
        related_prediction_id=body.related_prediction_id,
        related_shadow_id=body.related_shadow_id,
        comment=redact_secrets(body.comment.strip()),
        label=label,
        review_status=REVIEW_STATUS_USER_REVIEWED,
        created_by=f"admin:{user.username}",
    )
    session.add(ent)
    session.commit()
    session.refresh(ent)
    return {
        "schema": "llm_learning_comment_v1",
        "ok": True,
        "comment_id": int(ent.comment_id),
        "review_status": REVIEW_STATUS_USER_REVIEWED,
        "pipeline_note": "USER COMMENT → Feedback → Teacher → CLEAN → Gold/Silver → LoRA export",
        "auto_gold_forbidden": True,
        "REAL_ORDER_MUTATION": 0,
    }


@router.get("/comments")
def list_llm_learning_comments(
    market: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    q = (
        select(LlmLearningUserCommentEntity)
        .where(LlmLearningUserCommentEntity.deleted_at.is_(None))
        .order_by(desc(LlmLearningUserCommentEntity.created_at))
        .limit(limit)
    )
    if market:
        m = normalize_market(market)
        if m:
            q = q.where(LlmLearningUserCommentEntity.market == m)
    rows = list(session.scalars(q))
    return {
        "schema": "llm_learning_comments_v1",
        "items": [
            {
                "comment_id": int(r.comment_id),
                "market": r.market,
                "symbol": r.symbol,
                "related_analysis_id": r.related_analysis_id,
                "related_prediction_id": r.related_prediction_id,
                "related_shadow_id": r.related_shadow_id,
                "comment": r.comment,
                "label": r.label,
                "review_status": r.review_status,
                "created_by": r.created_by,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
        "total": len(rows),
    }
