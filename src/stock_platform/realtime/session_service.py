from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from stock_platform.operation.calendar_repository import (
    TradingCalendarRepository,
)
from stock_platform.operation.calendar_service import (
    TradingCalendarService,
)
from stock_platform.realtime.manager import (
    realtime_manager,
)
from stock_platform.realtime.runtime import (
    realtime_execution_runner,
    realtime_safety_guard,
    realtime_strategy_runner,
)
from stock_platform.realtime.session_models import (
    TradingSessionPhase,
    TradingSessionResult,
)


class RealtimeTradingSessionService:
    """장전·장중·장마감·장후 자동매매 세션을 제어한다."""

    def __init__(self, session: Session) -> None:
        self._calendar = TradingCalendarService(
            TradingCalendarRepository(session)
        )

    async def execute(
        self,
        *,
        phase: TradingSessionPhase,
        exchange_code: str = "KRX",
        trade_date: date | None = None,
    ) -> TradingSessionResult:
        target_date = trade_date or date.today()
        exchange = exchange_code.upper()

        decision = self._calendar.evaluate(
            exchange_code=exchange,
            calendar_date=target_date,
        )

        if exchange == "KRX" and (
            not decision.is_trading_day or not decision.live_allowed
        ):
            from stock_platform.operation.calendar_constants import (
                CALENDAR_UNAVAILABLE_REASONS,
                PAUSE_REASON_CALENDAR_UNAVAILABLE,
                PAUSE_REASON_MARKET_CLOSED,
            )

            unavailable = (
                decision.reason_code in CALENDAR_UNAVAILABLE_REASONS
            )
            reason = (
                PAUSE_REASON_CALENDAR_UNAVAILABLE
                if unavailable
                else PAUSE_REASON_MARKET_CLOSED
            )
            return TradingSessionResult(
                phase=phase,
                executed=False,
                message=(
                    f"Skipped: {reason} ({decision.reason_code})"
                ),
                executed_at=datetime.now(timezone.utc),
            )

        if phase == TradingSessionPhase.PRE_MARKET:
            realtime_safety_guard.reset_daily_counters()
            return TradingSessionResult(
                phase=phase,
                executed=True,
                message="Daily safety counters reset",
                executed_at=datetime.now(timezone.utc),
            )

        if phase == TradingSessionPhase.MARKET_OPEN:
            # Feature Flag ON 일 때만 Runner 자동 기동 (기본 OFF)
            from stock_platform.realtime.execution_auto_start import (
                maybe_auto_start_runners,
            )
            from stock_platform.order.paper_unattended_runtime import (
                paper_fill_recovery_scheduler,
                paper_outbox_worker_runtime,
            )
            from stock_platform.realtime.paper_price_feed import (
                paper_price_feed,
            )

            # 세션 오픈 시 Paper 무인 보조 경로 재확인 (idempotent)
            worker_status = paper_outbox_worker_runtime.start()
            recovery_status = paper_fill_recovery_scheduler.start()
            feed_status = paper_price_feed.start()

            auto = await maybe_auto_start_runners(
                source="MARKET_OPEN",
                allow_live=False,  # 세션 스케줄러는 Paper만
            )
            execution_status = realtime_execution_runner.status()
            strategy_status = realtime_strategy_runner.status()
            return TradingSessionResult(
                phase=phase,
                executed=True,
                message=(
                    "Market open; auto_start="
                    f"{auto.get('started_execution')} "
                    f"reason={auto.get('skipped_reason')}; "
                    f"worker={worker_status.get('started')}; "
                    f"recovery={recovery_status.get('started')}; "
                    f"feed={feed_status.get('started')}; "
                    f"execution_running={execution_status.get('running')}, "
                    f"strategy_running={strategy_status.get('running')}"
                ),
                executed_at=datetime.now(timezone.utc),
            )

        if phase == TradingSessionPhase.MARKET_CLOSE:
            from stock_platform.realtime.paper_price_feed import (
                paper_price_feed,
            )

            await paper_price_feed.shutdown()
            await realtime_execution_runner.stop()
            await realtime_strategy_runner.stop()

            return TradingSessionResult(
                phase=phase,
                executed=True,
                message=(
                    "Realtime execution, strategy runners, "
                    "and paper price feed stopped"
                ),
                executed_at=datetime.now(timezone.utc),
            )

        await realtime_manager.stop_all()

        return TradingSessionResult(
            phase=phase,
            executed=True,
            message="Realtime market data clients stopped",
            executed_at=datetime.now(timezone.utc),
        )
