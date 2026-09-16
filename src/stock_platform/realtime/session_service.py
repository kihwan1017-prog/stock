from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from stock_platform.operation.calendar_repository import (
    TradingCalendarRepository,
)
from stock_platform.operation.calendar_service import (
    TradingCalendarService,
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
            from stock_platform.realtime.integrated_runtime_lifecycle import (
                on_market_open,
            )

            opened = await on_market_open()
            execution_status = realtime_execution_runner.status()
            strategy_status = realtime_strategy_runner.status()
            return TradingSessionResult(
                phase=phase,
                executed=True,
                message=(
                    "Market open; "
                    f"lifecycle={opened.get('skipped_reason') or 'ok'}; "
                    f"auto={opened.get('auto_start', {}).get('skipped_reason')}; "
                    f"upbit={opened.get('upbit_quotes')}; "
                    f"execution_running={execution_status.get('running')}, "
                    f"strategy_running={strategy_status.get('running')}"
                ),
                executed_at=datetime.now(timezone.utc),
            )

        if phase == TradingSessionPhase.MARKET_CLOSE:
            from stock_platform.realtime.integrated_runtime_lifecycle import (
                on_market_close,
            )

            closed = await on_market_close()
            return TradingSessionResult(
                phase=phase,
                executed=True,
                message=(
                    "Market close; "
                    f"keep_upbit={closed.get('keep_upbit')}; "
                    f"runners={closed.get('runners')}; "
                    f"feeds={closed.get('feeds')}"
                ),
                executed_at=datetime.now(timezone.utc),
            )

        # POST_MARKET 등 — Upbit 유지 옵션 반영
        from stock_platform.realtime.live_runtime_control import (
            should_keep_upbit_on_krx_close,
            stop_live_market_feeds,
        )

        keep_upbit = should_keep_upbit_on_krx_close()
        await stop_live_market_feeds(keep_upbit=keep_upbit)

        return TradingSessionResult(
            phase=phase,
            executed=True,
            message=(
                "Realtime market data clients stopped"
                + (" (upbit kept)" if keep_upbit else "")
            ),
            executed_at=datetime.now(timezone.utc),
        )
