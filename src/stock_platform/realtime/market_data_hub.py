"""STEP 8-5-9 — Shared Realtime Market Data Hub."""

from __future__ import annotations

import asyncio
import threading
from datetime import datetime, timezone
from typing import Any, Callable

import structlog

from stock_platform.realtime.bus import RealtimeQuoteBus
from stock_platform.realtime.consumer_registry import (
    ScopeConsumerRegistry,
    ScopeRequiredError,
)
from stock_platform.realtime.hub_constants import HubConnectionStatus
from stock_platform.realtime.market_event import RealtimeMarketEvent
from stock_platform.realtime.models import MarketEventType, RealtimeQuote
from stock_platform.realtime.strategy_models import RealtimeStrategyConfig
from stock_platform.realtime.strategy_signal import StrategySignal
from stock_platform.strategy_deployment.runtime_scope import (
    RuntimeLifecycleStatus,
    StrategyRuntimeScope,
)


logger = structlog.get_logger(__name__)


class RealtimeMarketDataHub:
    """
    공유 시세 연결·구독 집계·Event 라우팅.
    주문 생성·Credential 장기 보관 금지.
    """

    def __init__(
        self,
        *,
        quote_bus: RealtimeQuoteBus | None = None,
        registry: ScopeConsumerRegistry | None = None,
        signal_handler: Callable[[StrategySignal], Any] | None = None,
    ) -> None:
        self._quote_bus = quote_bus
        self._registry = registry or ScopeConsumerRegistry()
        self._signal_handler = signal_handler
        self._status = HubConnectionStatus.DISCONNECTED
        self._task: asyncio.Task | None = None
        self._lock = threading.Lock()
        self._reconnect_count = 0
        self._last_event_at: datetime | None = None
        self._last_error: str | None = None
        self._event_count = 0
        self._signal_published = 0
        self._enabled = True

    @property
    def registry(self) -> ScopeConsumerRegistry:
        return self._registry

    def set_quote_bus(self, bus: RealtimeQuoteBus) -> None:
        self._quote_bus = bus

    def set_signal_handler(
        self, handler: Callable[[StrategySignal], Any] | None
    ) -> None:
        self._signal_handler = handler

    def register_consumer(
        self,
        scope: StrategyRuntimeScope | None,
        symbols: list[str],
        *,
        config: RealtimeStrategyConfig | None = None,
        runtime_status: RuntimeLifecycleStatus = RuntimeLifecycleStatus.RUNNING,
    ):
        if not self._enabled:
            raise RuntimeError("Realtime hub disabled")
        return self._registry.register_consumer(
            scope,
            symbols,
            config=config,
            runtime_status=runtime_status,
        )

    def unregister_consumer(
        self, scope: StrategyRuntimeScope | str
    ) -> list[str]:
        return self._registry.unregister_consumer(scope)

    async def start_dispatch(self) -> dict[str, Any]:
        if self._task is not None and not self._task.done():
            return {"already_running": True, **self.status()}
        if self._quote_bus is None:
            raise RuntimeError("quote_bus not bound")
        self._status = HubConnectionStatus.CONNECTING
        self._task = asyncio.create_task(
            self._run_dispatch(),
            name="realtime-market-data-hub",
        )
        return self.status()

    async def stop_dispatch(self) -> None:
        if self._task is None:
            self._status = HubConnectionStatus.STOPPED
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        self._status = HubConnectionStatus.STOPPED

    async def shutdown(self) -> dict[str, Any]:
        await self.stop_dispatch()
        self._registry.clear()
        return self.status()

    async def _run_dispatch(self) -> None:
        assert self._quote_bus is not None
        self._status = HubConnectionStatus.CONNECTED
        try:
            async for quote in self._quote_bus.subscribe():
                try:
                    event = self._quote_to_event(quote)
                    self._event_count += 1
                    self._last_event_at = datetime.now(timezone.utc)
                    signals = self._registry.dispatch(event)
                    for signal in signals:
                        self._signal_published += 1
                        if self._signal_handler is not None:
                            result = self._signal_handler(signal)
                            if asyncio.iscoroutine(result):
                                await result
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    self._last_error = str(exc)[:200]
                    self._status = HubConnectionStatus.DEGRADED
                    logger.warning(
                        "realtime_hub_dispatch_error",
                        error_type=exc.__class__.__name__,
                    )
        finally:
            if self._status != HubConnectionStatus.STOPPED:
                self._status = HubConnectionStatus.DISCONNECTED

    def ingest_quote_sync(self, quote: RealtimeQuote) -> list[StrategySignal]:
        """테스트·동기 주입용."""

        event = self._quote_to_event(quote)
        self._event_count += 1
        self._last_event_at = datetime.now(timezone.utc)
        return self._registry.dispatch(event)

    @staticmethod
    def _quote_to_event(quote: RealtimeQuote) -> RealtimeMarketEvent:
        exchange = quote.exchange_code.upper()
        market_type = (
            "CRYPTO"
            if exchange in {"UPBIT"}
            else "STOCK"
        )
        from stock_platform.realtime.consumer_registry import (
            ScopeConsumerRegistry,
        )

        data_broker = ScopeConsumerRegistry.market_data_broker(
            broker_code=exchange,
            market_type=market_type,
        )
        event_type = quote.event_type.value
        if quote.event_type == MarketEventType.TICKER:
            event_type = "TICKER"
        elif quote.event_type == MarketEventType.TRADE:
            event_type = "TRADE"
        return RealtimeMarketEvent(
            broker_code=data_broker,
            market_type=market_type,
            symbol=quote.symbol.upper(),
            event_type=event_type,
            event_time=quote.event_time,
            received_at=quote.received_at,
            exchange_code=exchange,
            price=quote.trade_price,
            volume=quote.trade_volume,
            bid=quote.bid,
            ask=quote.ask,
            change_rate=quote.change_rate,
            raw_sequence=None,
            source_code=quote.source_code,
        )

    def status(self) -> dict[str, Any]:
        return {
            "hub_status": self._status.value,
            "enabled": self._enabled,
            "dispatch_running": (
                self._task is not None and not self._task.done()
            ),
            "reconnect_count": self._reconnect_count,
            "event_count": self._event_count,
            "signal_published": self._signal_published,
            "last_event_at": (
                self._last_event_at.isoformat()
                if self._last_event_at
                else None
            ),
            "last_error": self._last_error,
            "active_scopes": self._registry.active_scope_count(),
            "running_scopes": self._registry.running_scope_count(),
            "warming_up_scopes": self._registry.warming_up_count(),
            "subscriptions": len(self._registry.list_subscriptions()),
            "deprecated_global_runner": False,
        }

    def health_summary(self) -> dict[str, Any]:
        return {
            "hub_status": self._status.value,
            "reconnect_count": self._reconnect_count,
            "active_subscriptions": len(
                self._registry.list_subscriptions()
            ),
            "active_scopes": self._registry.active_scope_count(),
            "running_scopes": self._registry.running_scope_count(),
            "warming_up_scopes": self._registry.warming_up_count(),
            "last_event_at": (
                self._last_event_at.isoformat()
                if self._last_event_at
                else None
            ),
            "last_error": self._last_error,
        }


_HUB: RealtimeMarketDataHub | None = None
_HUB_LOCK = threading.Lock()


def get_realtime_market_data_hub() -> RealtimeMarketDataHub:
    global _HUB
    with _HUB_LOCK:
        if _HUB is None:
            from stock_platform.common.settings import get_settings
            from stock_platform.realtime.manager import realtime_manager
            from stock_platform.realtime.scoped_signal_pipeline import (
                publish_scoped_signal,
            )

            s = get_settings()
            hub = RealtimeMarketDataHub(
                quote_bus=realtime_manager.bus,
                signal_handler=publish_scoped_signal,
            )
            hub._enabled = bool(
                getattr(s, "realtime_hub_enabled", True)
            )
            _HUB = hub
        return _HUB


def reset_realtime_market_data_hub_for_tests() -> None:
    global _HUB
    with _HUB_LOCK:
        if _HUB is not None:
            _HUB.registry.clear()
        _HUB = None


__all__ = [
    "RealtimeMarketDataHub",
    "ScopeRequiredError",
    "get_realtime_market_data_hub",
    "reset_realtime_market_data_hub_for_tests",
]
