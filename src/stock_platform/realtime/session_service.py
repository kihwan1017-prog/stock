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

        if (
            exchange == "KRX"
            and not decision.is_trading_day
        ):
            return TradingSessionResult(
                phase=phase,
                executed=False,
                message=(
                    f"Skipped non-trading day: "
                    f"{decision.reason_code}"
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
            execution_status = (
                realtime_execution_runner.status()
            )
            strategy_status = (
                realtime_strategy_runner.status()
            )

            if not execution_status["running"]:
                await realtime_execution_runner.start()

            if not strategy_status["running"]:
                await realtime_strategy_runner.start()

            return TradingSessionResult(
                phase=phase,
                executed=True,
                message=(
                    "Realtime execution and strategy "
                    "runners started"
                ),
                executed_at=datetime.now(timezone.utc),
            )

        if phase == TradingSessionPhase.MARKET_CLOSE:
            await realtime_execution_runner.stop()
            await realtime_strategy_runner.stop()

            return TradingSessionResult(
                phase=phase,
                executed=True,
                message=(
                    "Realtime execution and strategy "
                    "runners stopped"
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
