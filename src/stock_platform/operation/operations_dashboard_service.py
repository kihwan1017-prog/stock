from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.ai.analysis_models import (
    CandidateAnalysisResult,
    CandidateAnalysisRun,
)
from stock_platform.broker.live_transition_service import (
    LiveTradingTransitionService,
)
from stock_platform.common.settings import get_settings
from stock_platform.operation.health_service import (
    SystemHealthService,
)
from stock_platform.realtime.dashboard_service import (
    RealtimeDashboardService,
)
from stock_platform.risk_engine.kill_switch_service import (
    KillSwitchService,
)
from stock_platform.screener.persistence_models import (
    CandidateResult,
    CandidateRun,
)


class OperationsDashboardService:
    """운영센터용 통합 대시보드 스냅샷."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._realtime = RealtimeDashboardService(session)
        self._health = SystemHealthService()

    async def build(
        self,
        *,
        account_id: int = 1,
        exchange_code: str = "KRX",
        recent_limit: int = 20,
    ) -> dict[str, Any]:
        base = await self._realtime.build(
            account_id=account_id,
            recent_limit=recent_limit,
        )
        health = await self._health.build()
        settings = get_settings()
        exchange = exchange_code.upper()
        today = date.today()

        candidate_run = self._session.scalar(
            select(CandidateRun)
            .where(
                CandidateRun.exchange_code == exchange,
                CandidateRun.as_of_date == today,
            )
            .order_by(CandidateRun.run_id.desc())
            .limit(1)
        )
        candidates: list[dict[str, Any]] = []
        if candidate_run is not None:
            rows = list(
                self._session.scalars(
                    select(CandidateResult)
                    .where(
                        CandidateResult.run_id
                        == candidate_run.run_id
                    )
                    .order_by(CandidateResult.rank_no.asc())
                    .limit(10)
                )
            )
            candidates = [
                {
                    "rank": row.rank_no,
                    "symbol": row.symbol,
                    "total_score": row.total_score,
                }
                for row in rows
            ]

        analysis_run = self._session.scalar(
            select(CandidateAnalysisRun)
            .where(
                CandidateAnalysisRun.exchange_code == exchange
            )
            .order_by(
                CandidateAnalysisRun.analysis_run_id.desc()
            )
            .limit(1)
        )
        ai_selected: list[dict[str, Any]] = []
        if analysis_run is not None:
            ai_rows = list(
                self._session.scalars(
                    select(CandidateAnalysisResult)
                    .where(
                        CandidateAnalysisResult.analysis_run_id
                        == analysis_run.analysis_run_id
                    )
                    .order_by(
                        CandidateAnalysisResult.rank_no.asc()
                    )
                    .limit(5)
                )
            )
            ai_selected = [
                {
                    "rank": row.rank_no,
                    "symbol": row.symbol,
                    "ai_score": row.ai_score,
                    "action": row.action_code,
                    "confidence": row.confidence,
                }
                for row in ai_rows
            ]

        kill_switch = KillSwitchService(
            self._session
        ).get_state()
        live_transition = LiveTradingTransitionService(
            self._session
        ).get_active()

        return {
            "generated_at": datetime.now(timezone.utc),
            "health": health,
            "application": base.application,
            "infrastructure": base.infrastructure,
            "realtime": base.realtime,
            "account": base.account,
            "trading": base.trading,
            "ai": {
                **base.ai,
                "selected_candidates": ai_selected,
                "analysis_run_id": (
                    analysis_run.analysis_run_id
                    if analysis_run
                    else None
                ),
            },
            "candidates": {
                "as_of_date": today.isoformat(),
                "exchange_code": exchange,
                "run_id": (
                    candidate_run.run_id
                    if candidate_run
                    else None
                ),
                "top": candidates,
            },
            "risk": {
                "kill_switch": kill_switch,
                "live_order_enabled": (
                    settings.kiwoom_live_order_enabled
                ),
                "active_live_transition_id": (
                    live_transition.transition_id
                    if live_transition is not None
                    else None
                ),
            },
            "strategy_deployment": {
                "auto_deploy_enabled": (
                    settings.strategy_auto_deploy_enabled
                ),
                "paper_auto_stop_enabled": (
                    settings.paper_strategy_auto_stop_enabled
                ),
            },
            "recent_errors": base.recent_errors,
        }
