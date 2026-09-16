"""STEP 12-2-1 — User Strategy Draft API.

Strategy Draft의 사용자(요청자) 측 API. 조회만 허용하며, 생성/수정/Archive는
관리자 전용이다(관리자 심사·작성 산출물이므로). AI 호출, Prompt 생성,
LLM Provider 호출, Backtest, Paper Trading, Runtime/Order/Broker/Scheduler
WRITE는 이 API의 범위가 아니다(STEP12-2-2 이후).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from stock_platform.ai.strategy_draft.service import (
    StrategyDraftError,
    StrategyDraftService,
)
from stock_platform.ai.strategy_draft_approval.service import (
    StrategyDraftApprovalService,
)
from stock_platform.auth.deps import AuthenticatedUser, require_permission
from stock_platform.database.session import get_db_session

router = APIRouter(
    prefix="/api/v1/user/strategy-drafts",
    tags=["User Strategy Drafts"],
)


def _raise(exc: StrategyDraftError) -> None:
    code = status.HTTP_400_BAD_REQUEST
    if exc.code in {"NOT_FOUND", "STRATEGY_REQUEST_NOT_FOUND"}:
        code = status.HTTP_404_NOT_FOUND
    elif exc.code == "OWNERSHIP_DENIED":
        code = status.HTTP_403_FORBIDDEN
    raise HTTPException(
        status_code=code, detail={"code": exc.code, "message": exc.message}
    )


@router.get("")
def list_strategy_drafts(
    strategy_request_id: int | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db_session),
    # STEP12-2-1A: 조회 전용 API이므로 trading:write(쓰기 권한)가 아니라
    # trading:read(읽기 권한)를 요구한다 — 이 프로젝트 전반의 확립된
    # 컨벤션(user_strategies.py/user_ai.py/user_candidates.py 등 모든
    # GET 엔드포인트가 trading:read 사용).
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
) -> dict[str, Any]:
    # IDOR 방지 — user_id를 요청자 본인으로 고정(쿼리 파라미터로 타인 지정 불가).
    # strategy_draft에는 별도 user_id 컬럼이 없어 strategy_request와 JOIN해
    # 소유권을 파생 조회한다.
    return StrategyDraftService(session).list(
        strategy_request_id=strategy_request_id,
        status=status_filter,
        user_id=user.user_id,
        limit=limit,
        offset=offset,
    )


@router.get("/{draft_id}")
def get_strategy_draft(
    draft_id: int,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
) -> dict[str, Any]:
    try:
        return StrategyDraftService(session).get_owned(draft_id, user_id=user.user_id)
    except StrategyDraftError as exc:
        _raise(exc)
    return {}


@router.get("/{draft_id}/approval")
def get_strategy_draft_approval(
    draft_id: int,
    session: Session = Depends(get_db_session),
    # STEP12-3 §13 — 본인 소유 승인 결과(및 생성된 Strategy Definition
    # 링크)를 읽기 전용으로 조회할 수 있게 한다. 새 쓰기 API는 추가하지
    # 않는다(승인/반려/취소는 관리자 전용).
    user: AuthenticatedUser = Depends(require_permission("trading:read")),
) -> dict[str, Any]:
    try:
        # 소유권 검증(IDOR 방지) — 본인 Strategy Request의 Draft가 아니면 차단.
        StrategyDraftService(session).get_owned(draft_id, user_id=user.user_id)
    except StrategyDraftError as exc:
        _raise(exc)
        return {}
    result = StrategyDraftApprovalService(session).get_for_draft(draft_id)
    return result or {}
