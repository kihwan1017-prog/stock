"""회원용 전략 조회 API — 읽기 전용.

전략 배포·런타임 제어(POST 계열)는 여전히 admin 전용이다
(strategy_deployment.py, strategy_runtime.py, realtime_strategy.py,
strategy_selector.py, strategy_leaderboard.py, strategy_performance.py).
이 파일은 그 화면들이 노출하던 조회(GET)만 회원 권한(trading:read)으로
재노출하는 얇은 wrapper이며, 서비스/리포지토리 로직은 전혀 중복하지
않는다 — 실제 다계정 전략 실행 엔진 자체는 이번 범위에 포함하지 않는다.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from stock_platform.auth.deps import (
    AuthenticatedUser,
    require_permission,
)
from stock_platform.database.session import get_db_session
from stock_platform.performance.leaderboard_repository import (
    StrategyLeaderboardRepository,
)
from stock_platform.performance.leaderboard_trend_service import (
    StrategyLeaderboardTrendService,
)
from stock_platform.performance.ranking_service import (
    StrategyPerformanceRankingService,
)
from stock_platform.performance.repository import (
    StrategyPerformanceRepository,
)
from stock_platform.performance.selector_repository import (
    StrategySelectionRepository,
)
from stock_platform.performance.summary_service import (
    StrategyPerformanceSummaryService,
)
from stock_platform.realtime.runtime import realtime_strategy_runner
from stock_platform.strategy_deployment.dashboard_service import (
    StrategyOperationsDashboardService,
)
from stock_platform.strategy_deployment.runtime_manager import (
    dynamic_strategy_runtime_manager,
)


router = APIRouter(
    prefix="/api/v1/user/strategies",
    tags=["User Strategies"],
)


@router.get("/operations-dashboard")
def get_strategy_operations_dashboard(
    market_code: str = Query(default="KRX", min_length=1),
    symbol: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200),
    _: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    try:
        return StrategyOperationsDashboardService(session).build(
            market_code=market_code,
            symbol=symbol,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get("/ranking")
def get_strategy_ranking(
    run_type: str | None = Query(default=None),
    market_code: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
    minimum_trade_count: int = Query(default=1, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    _: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    return StrategyPerformanceRankingService(session).rank(
        run_type=run_type,
        market_code=market_code,
        symbol=symbol,
        minimum_trade_count=minimum_trade_count,
        limit=limit,
    )


@router.get("/ranking/summary")
def get_strategy_ranking_summary(
    strategy_code: str | None = Query(default=None),
    run_type: str | None = Query(default=None),
    market_code: str | None = Query(default=None),
    _: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    return StrategyPerformanceSummaryService(session).summarize(
        strategy_code=strategy_code,
        run_type=run_type,
        market_code=market_code,
    )


@router.get("/selection/latest")
def get_latest_strategy_selection(
    market_code: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
    _: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    return StrategySelectionRepository(session).latest(
        market_code=market_code,
        symbol=symbol,
    )


@router.get("/runtime/status")
def get_strategy_runtime_status(
    _: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
):
    return dynamic_strategy_runtime_manager.status()


@router.get("/realtime/status")
def get_realtime_strategy_status(
    _: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
):
    return realtime_strategy_runner.status()


@router.get("/leaderboard/history")
def list_leaderboard_history(
    run_type: str | None = Query(default=None),
    market_code: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    _: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    return StrategyLeaderboardRepository(session).list_history(
        run_type=run_type,
        market_code=market_code,
        symbol=symbol,
        limit=limit,
    )


@router.get("/leaderboard/snapshots/{snapshot_id}")
def get_leaderboard_snapshot(
    snapshot_id: int,
    _: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    snapshot, entries = StrategyLeaderboardRepository(
        session
    ).get_snapshot(snapshot_id=snapshot_id)
    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Leaderboard snapshot not found",
        )
    return {"snapshot": snapshot, "entries": entries}


@router.get("/leaderboard/strategies/{strategy_code}/history")
def get_strategy_rank_history(
    strategy_code: str,
    limit: int = Query(default=100, ge=1, le=500),
    _: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    return StrategyLeaderboardTrendService(session).strategy_history(
        strategy_code=strategy_code,
        limit=limit,
    )


@router.get("/performance/runs/{run_id}")
def get_performance_run(
    run_id: int,
    user: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    run, metric = StrategyPerformanceRepository(session).get_detail(
        run_id=run_id
    )
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Strategy performance run not found",
        )
    # STEP 8-3: 타인 개인 백테스트 결과 차단
    if not user.is_admin:
        requested_by = getattr(run, "requested_by_user_id", None)
        strategy_id = getattr(run, "strategy_id", None)
        if requested_by is not None and int(requested_by) != int(
            user.user_id
        ):
            # 공개 전략 결과는 조회 허용, 그 외 차단
            if strategy_id is not None:
                from stock_platform.strategy_deployment.ownership import (
                    StrategyDefinitionService,
                    assert_strategy_readable,
                )

                try:
                    strategy = StrategyDefinitionService(
                        session
                    ).require(int(strategy_id))
                    assert_strategy_readable(user, strategy)
                except HTTPException:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="다른 사용자의 백테스트 결과입니다.",
                    ) from None
            else:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="다른 사용자의 백테스트 결과입니다.",
                )
    return {"run": run, "metric": metric}
