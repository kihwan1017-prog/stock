"""STEP 8-5-9 — 레거시 RealtimeStrategyRunner 호환 래퍼.

전역 MA State는 제거되었다.
start/stop/status는 Shared Hub + Scope Consumer Registry만 사용한다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import structlog

from stock_platform.realtime.bus import RealtimeQuoteBus
from stock_platform.realtime.signal_bus import RealtimeSignalBus
from stock_platform.realtime.strategy_models import (
    RealtimePositionState,
    RealtimeStrategyConfig,
)


logger = structlog.get_logger(__name__)
ZERO = Decimal("0")


class RealtimeStrategyRunner:
    """
    Deprecated 전역 Runner 파사드.

    실제 전략 평가는 Scope별 MovingAverageStrategyEvaluator가 수행한다.
    Scope 없는 단독 MA 루프는 더 이상 기동하지 않는다.
    """

    def __init__(
        self,
        *,
        quote_bus: RealtimeQuoteBus,
        signal_bus: RealtimeSignalBus,
        config: RealtimeStrategyConfig | None = None,
    ) -> None:
        self._quote_bus = quote_bus
        self._signal_bus = signal_bus
        self._config = config or RealtimeStrategyConfig()
        # 레거시 포지션 API 호환용 (Scope별이 아님 — 조회만)
        self._positions: dict[str, RealtimePositionState] = {}
        self._deprecated = True

    async def start(self) -> dict:
        """Hub dispatch 루프 시작 — 전역 MA 루프는 기동하지 않음."""

        from stock_platform.realtime.market_data_hub import (
            get_realtime_market_data_hub,
        )

        hub = get_realtime_market_data_hub()
        hub.set_quote_bus(self._quote_bus)
        result = await hub.start_dispatch()
        logger.warning(
            "realtime_strategy_runner_start_deprecated",
            message=(
                "Global MA runner removed (STEP 8-5-9). "
                "Using RealtimeMarketDataHub + Scope Registry."
            ),
        )
        return {
            "deprecated": True,
            "mode": "SCOPE_REGISTRY_HUB",
            "message": (
                "Global realtime_strategy_runner MA loop removed. "
                "Register scoped consumers via Runtime Registry."
            ),
            **result,
            **self.status(),
        }

    async def run_forever(self) -> None:
        # 레거시 호출 호환 — Hub dispatch에 위임
        await self.start()
        from stock_platform.realtime.market_data_hub import (
            get_realtime_market_data_hub,
        )

        hub = get_realtime_market_data_hub()
        task = hub._task
        if task is not None:
            await task

    async def stop(self) -> None:
        from stock_platform.realtime.market_data_hub import (
            get_realtime_market_data_hub,
        )

        await get_realtime_market_data_hub().stop_dispatch()

    def set_position(
        self,
        *,
        exchange_code: str,
        symbol: str,
        quantity: Decimal,
        average_entry_price: Decimal | None,
    ) -> RealtimePositionState:
        if quantity < ZERO:
            raise ValueError("quantity must be >= 0")
        if quantity > ZERO and average_entry_price is None:
            raise ValueError("average_entry_price required when quantity > 0")
        key = self._key(exchange_code, symbol)
        state = RealtimePositionState(
            quantity=quantity,
            average_entry_price=average_entry_price,
        )
        self._positions[key] = state
        return state

    def get_position(
        self, *, exchange_code: str, symbol: str
    ) -> RealtimePositionState:
        return self._positions.get(
            self._key(exchange_code, symbol),
            RealtimePositionState(quantity=ZERO, average_entry_price=None),
        )

    def status(self) -> dict:
        from stock_platform.realtime.market_data_hub import (
            get_realtime_market_data_hub,
        )

        hub = get_realtime_market_data_hub()
        hub_status = hub.status()
        return {
            "deprecated": True,
            "mode": "SCOPE_REGISTRY_HUB",
            "running": hub_status.get("dispatch_running", False),
            "processed_count": hub_status.get("event_count", 0),
            "published_count": hub_status.get("signal_published", 0),
            "last_error": hub_status.get("last_error"),
            "position_count": len(self._positions),
            "active_scopes": hub_status.get("active_scopes", 0),
            "hub": hub_status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def _key(exchange_code: str, symbol: str) -> str:
        return f"{exchange_code.upper()}:{symbol.upper()}"
