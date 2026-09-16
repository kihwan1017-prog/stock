"""STEP 12-2-1 — Admin Strategy Draft API.

승인(APPROVED)된 Strategy Request 위에 Strategy Draft를 저장·버전관리하는
관리자 측 API. AI 호출, Prompt 생성, LLM Provider 호출, Strategy 자동 생성,
Backtest, Paper Trading, Runtime/Order/Broker/Scheduler WRITE는 이 API의
범위가 아니다(STEP12-2-2 이후).

엔드포인트는 지정된 고정 목록(POST/PATCH/GET/GET/GET history/POST archive)만
사용한다. "Revision 생성"과 "Version 조회"는 새 경로를 만들지 않고 기존
엔드포인트의 파라미터로 구분한다:
- POST /admin/strategy-drafts: body에 source_draft_id가 있으면 해당 Draft의
  새 Revision을 생성(create_revision)하고, 없으면 새 Draft/Version을
  생성(create)한다.
- GET /admin/strategy-drafts: strategy_request_id + version 쿼리파라미터를
  함께 주면 해당 Version의 전체 Revision 목록(Version 조회)을 반환한다.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.ai.providers.security import sanitize_for_log
from stock_platform.ai.strategy_draft.comparison import compare_drafts
from stock_platform.ai.strategy_draft.constants import (
    REASON_MAX_LENGTH,
    SUMMARY_MAX_LENGTH,
    TITLE_MAX_LENGTH,
)
from stock_platform.ai.strategy_draft.service import (
    StrategyDraftError,
    StrategyDraftService,
)
from stock_platform.ai.strategy_draft_generation.service import (
    StrategyDraftGenerationService,
)
from stock_platform.api.deps_admin import AuditLogService, require_admin
from stock_platform.auth.deps import AuthenticatedUser, admin_actor_label
from stock_platform.database.session import get_db_session

router = APIRouter(
    prefix="/api/v1/admin/strategy-drafts",
    tags=["Admin Strategy Drafts"],
    dependencies=[Depends(require_admin)],
)


class CreateStrategyDraftBody(BaseModel):
    strategy_request_id: int = Field(gt=0)
    # source_draft_id가 있으면 해당 Draft의 새 Revision을 생성한다(같은 Version).
    # 없으면 strategy_request_id 기준으로 새 Draft/Version을 생성한다.
    source_draft_id: int | None = Field(default=None, gt=0)

    title: str | None = Field(default=None, max_length=TITLE_MAX_LENGTH)
    summary: str | None = Field(default=None, max_length=SUMMARY_MAX_LENGTH)
    entry_rule: str | None = None
    exit_rule: str | None = None
    stop_loss_rule: str | None = None
    take_profit_rule: str | None = None
    position_sizing_rule: str | None = None
    timeframe: str | None = Field(default=None, max_length=20)
    market_type: str | None = Field(default=None, max_length=20)
    risk_parameters: dict[str, Any] | None = None
    indicator_configuration: dict[str, Any] | None = None
    llm_provider: str | None = Field(default=None, max_length=50)
    llm_model: str | None = Field(default=None, max_length=100)
    prompt_version: str | None = Field(default=None, max_length=40)

    reason: str | None = Field(default=None, max_length=REASON_MAX_LENGTH)
    correlation_id: str | None = None


class UpdateStrategyDraftBody(BaseModel):
    title: str | None = Field(default=None, max_length=TITLE_MAX_LENGTH)
    summary: str | None = Field(default=None, max_length=SUMMARY_MAX_LENGTH)
    entry_rule: str | None = None
    exit_rule: str | None = None
    stop_loss_rule: str | None = None
    take_profit_rule: str | None = None
    position_sizing_rule: str | None = None
    timeframe: str | None = Field(default=None, max_length=20)
    market_type: str | None = Field(default=None, max_length=20)
    risk_parameters: dict[str, Any] | None = None
    indicator_configuration: dict[str, Any] | None = None
    llm_provider: str | None = Field(default=None, max_length=50)
    llm_model: str | None = Field(default=None, max_length=100)
    prompt_version: str | None = Field(default=None, max_length=40)

    reason: str | None = Field(default=None, max_length=REASON_MAX_LENGTH)
    correlation_id: str | None = None


class ArchiveStrategyDraftBody(BaseModel):
    reason: str | None = Field(default=None, max_length=REASON_MAX_LENGTH)
    correlation_id: str | None = None


def _audit(
    session: Session, *, event_type: str, actor: str, detail: dict[str, Any]
) -> None:
    try:
        AuditLogService(session).record(
            event_type=event_type,
            actor=actor,
            detail=sanitize_for_log(detail),
        )
        session.commit()
    except Exception:  # noqa: BLE001
        session.rollback()


def _raise(exc: StrategyDraftError) -> None:
    code = status.HTTP_400_BAD_REQUEST
    if exc.code in {
        "NOT_FOUND",
        "STRATEGY_REQUEST_NOT_FOUND",
        "CANDIDATE_NOT_FOUND",
    }:
        code = status.HTTP_404_NOT_FOUND
    elif exc.code in {
        "INVALID_STATE_TRANSITION",
        "STRATEGY_REQUEST_NOT_APPROVED",
        "DUPLICATE_ACTIVE_DRAFT",
        "CANDIDATE_NOT_ACTIVE_AT_DRAFT",
        "CANDIDATE_FINGERPRINT_CHANGED",
        "AI_GENERATED_DRAFT_REQUIRES_REVISION",
        "CROSS_REQUEST_COMPARISON_BLOCKED",
    }:
        code = status.HTTP_409_CONFLICT
    raise HTTPException(
        status_code=code, detail={"code": exc.code, "message": exc.message}
    )


@router.post("", status_code=status.HTTP_201_CREATED)
def create_strategy_draft(
    body: CreateStrategyDraftBody,
    session: Session = Depends(get_db_session),
    admin: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(admin)
    is_revision = body.source_draft_id is not None
    event_ok = (
        "STRATEGY_DRAFT_REVISION_CREATED" if is_revision else "STRATEGY_DRAFT_CREATED"
    )
    event_fail = (
        "STRATEGY_DRAFT_REVISION_CREATE_FAILED"
        if is_revision
        else "STRATEGY_DRAFT_CREATE_FAILED"
    )
    try:
        if body.source_draft_id is not None:
            result = StrategyDraftService(session).create_revision(
                body.source_draft_id,
                actor=actor,
                reason=body.reason,
                correlation_id=body.correlation_id,
                title=body.title,
                summary=body.summary,
                entry_rule=body.entry_rule,
                exit_rule=body.exit_rule,
                stop_loss_rule=body.stop_loss_rule,
                take_profit_rule=body.take_profit_rule,
                position_sizing_rule=body.position_sizing_rule,
                timeframe=body.timeframe,
                market_type=body.market_type,
                risk_parameters=body.risk_parameters,
                indicator_configuration=body.indicator_configuration,
                llm_provider=body.llm_provider,
                llm_model=body.llm_model,
                prompt_version=body.prompt_version,
            )
        else:
            if not body.title or not body.timeframe or not body.market_type:
                raise StrategyDraftError(
                    "VALIDATION_ERROR",
                    "신규 Draft 생성 시 title/timeframe/market_type이 필요합니다.",
                )
            result = StrategyDraftService(session).create(
                strategy_request_id=body.strategy_request_id,
                actor=actor,
                title=body.title,
                timeframe=body.timeframe,
                market_type=body.market_type,
                summary=body.summary,
                entry_rule=body.entry_rule,
                exit_rule=body.exit_rule,
                stop_loss_rule=body.stop_loss_rule,
                take_profit_rule=body.take_profit_rule,
                position_sizing_rule=body.position_sizing_rule,
                risk_parameters=body.risk_parameters,
                indicator_configuration=body.indicator_configuration,
                llm_provider=body.llm_provider,
                llm_model=body.llm_model,
                prompt_version=body.prompt_version,
                correlation_id=body.correlation_id,
            )
    except StrategyDraftError as exc:
        _audit(
            session,
            event_type=event_fail,
            actor=actor,
            detail={
                "strategy_request_id": body.strategy_request_id,
                "source_draft_id": body.source_draft_id,
                "code": exc.code,
                "message": exc.message,
            },
        )
        _raise(exc)
        return {}
    _audit(
        session,
        event_type=event_ok,
        actor=actor,
        detail={
            "draft_id": result.get("draft_id"),
            "strategy_request_id": result.get("strategy_request_id"),
            "label": result.get("label"),
        },
    )
    return result


@router.patch("/{draft_id}")
def update_strategy_draft(
    draft_id: int,
    body: UpdateStrategyDraftBody,
    session: Session = Depends(get_db_session),
    admin: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(admin)
    overrides = body.model_dump(exclude={"reason", "correlation_id"})
    try:
        result = StrategyDraftService(session).update(
            draft_id,
            actor=actor,
            reason=body.reason,
            correlation_id=body.correlation_id,
            **overrides,
        )
    except StrategyDraftError as exc:
        _audit(
            session,
            event_type="STRATEGY_DRAFT_UPDATE_FAILED",
            actor=actor,
            detail={"draft_id": draft_id, "code": exc.code, "message": exc.message},
        )
        _raise(exc)
        return {}
    _audit(
        session,
        event_type="STRATEGY_DRAFT_UPDATED",
        actor=actor,
        detail={"draft_id": draft_id, "label": result.get("label")},
    )
    return result


@router.get("")
def list_strategy_drafts(
    strategy_request_id: int | None = Query(default=None),
    version: int | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    svc = StrategyDraftService(session)
    if strategy_request_id is not None and version is not None:
        try:
            return svc.get_version(strategy_request_id, version)
        except StrategyDraftError as exc:
            _raise(exc)
            return {}
    return svc.list(
        strategy_request_id=strategy_request_id,
        status=status_filter,
        limit=limit,
        offset=offset,
    )


@router.get("/{draft_id}")
def get_strategy_draft(
    draft_id: int,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        return StrategyDraftService(session).get(draft_id)
    except StrategyDraftError as exc:
        _raise(exc)
    return {}


@router.get("/{draft_id}/history")
def get_strategy_draft_history(
    draft_id: int,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db_session),
    admin: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(admin)
    try:
        result = StrategyDraftService(session).get_history(
            draft_id, limit=limit, offset=offset
        )
    except StrategyDraftError as exc:
        _audit(
            session,
            event_type="STRATEGY_DRAFT_HISTORY_VIEW_FAILED",
            actor=actor,
            detail={"draft_id": draft_id, "code": exc.code, "message": exc.message},
        )
        _raise(exc)
        return {}
    # History 내용 전체/Draft 본문은 기록하지 않고 draft_id/조회 건수만 남긴다.
    _audit(
        session,
        event_type="STRATEGY_DRAFT_HISTORY_VIEWED",
        actor=actor,
        detail={"draft_id": draft_id, "result_count": len(result.get("items", []))},
    )
    return result


@router.post("/{draft_id}/archive")
def archive_strategy_draft(
    draft_id: int,
    body: ArchiveStrategyDraftBody,
    session: Session = Depends(get_db_session),
    admin: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(admin)
    try:
        result = StrategyDraftService(session).archive(
            draft_id,
            actor=actor,
            reason=body.reason,
            correlation_id=body.correlation_id,
        )
    except StrategyDraftError as exc:
        _audit(
            session,
            event_type="STRATEGY_DRAFT_ARCHIVE_FAILED",
            actor=actor,
            detail={"draft_id": draft_id, "code": exc.code, "message": exc.message},
        )
        _raise(exc)
        return {}
    _audit(
        session,
        event_type="STRATEGY_DRAFT_ARCHIVED",
        actor=actor,
        detail={"draft_id": draft_id, "label": result.get("label")},
    )
    return result


@router.get("/{draft_id}/comparison")
def compare_strategy_draft(
    draft_id: int,
    compare_draft_id: int = Query(..., gt=0),
    session: Session = Depends(get_db_session),
    admin: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    """STEP12-2-3 — Version/Revision 비교(§7).

    IDOR 방지(§14) — 두 Draft가 동일 Strategy Request 소속일 때만 허용한다
    (다른 요청의 Draft를 임의로 비교하는 것은 기본적으로 차단).
    """
    actor = admin_actor_label(admin)
    draft_svc = StrategyDraftService(session)
    try:
        draft_a = draft_svc.get(draft_id)
        draft_b = draft_svc.get(compare_draft_id)
    except StrategyDraftError as exc:
        _audit(
            session,
            event_type="STRATEGY_DRAFT_COMPARISON_VIEWED",
            actor=actor,
            detail={
                "draft_id": draft_id,
                "compare_draft_id": compare_draft_id,
                "code": exc.code,
                "message": exc.message,
            },
        )
        _raise(exc)
        return {}

    if draft_a["strategy_request_id"] != draft_b["strategy_request_id"]:
        exc = StrategyDraftError(
            "CROSS_REQUEST_COMPARISON_BLOCKED",
            "다른 Strategy Request 소속 Draft는 비교할 수 없습니다.",
        )
        _audit(
            session,
            event_type="STRATEGY_DRAFT_COMPARISON_VIEWED",
            actor=actor,
            detail={
                "draft_id": draft_id,
                "compare_draft_id": compare_draft_id,
                "code": exc.code,
            },
        )
        _raise(exc)
        return {}

    gen_svc = StrategyDraftGenerationService(session)
    attempt_a = gen_svc.get_latest_attempt_for_draft(draft_id)
    attempt_b = gen_svc.get_latest_attempt_for_draft(compare_draft_id)
    result = compare_drafts(draft_a, draft_b, attempt_a=attempt_a, attempt_b=attempt_b)

    _audit(
        session,
        event_type="STRATEGY_DRAFT_COMPARISON_VIEWED",
        actor=actor,
        detail={
            "draft_id": draft_id,
            "compare_draft_id": compare_draft_id,
            "summary": result["summary"],
        },
    )
    return result
