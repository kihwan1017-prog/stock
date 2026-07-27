"""STEP 8-5-9 — Runtime Lifecycle ↔ Realtime Hub 브리지."""

from __future__ import annotations

from typing import Any

import structlog

from stock_platform.realtime.strategy_models import RealtimeStrategyConfig
from stock_platform.strategy_deployment.runtime_manager import (
    ScopedRuntimeEntry,
)
from stock_platform.strategy_deployment.runtime_scope import (
    RuntimeLifecycleStatus,
    StrategyRuntimeScope,
)


logger = structlog.get_logger(__name__)


def _symbols_for_entry(entry: ScopedRuntimeEntry) -> list[str]:
    symbol = (entry.runtime.symbol or "").strip().upper()
    if symbol:
        return [symbol]
    # 심볼 없으면 구독하지 않음 (허브 낭비 방지)
    return []


def _config_from_entry(entry: ScopedRuntimeEntry) -> RealtimeStrategyConfig:
    payload = entry.runtime.parameter_payload or {}
    try:
        short = int(payload.get("short_window", payload.get("short", 5)))
        long = int(payload.get("long_window", payload.get("long", 20)))
        cool = int(payload.get("cooldown_seconds", 30))
        return RealtimeStrategyConfig(
            short_window=max(1, short),
            long_window=max(short + 1, long),
            cooldown_seconds=max(0, cool),
        )
    except (TypeError, ValueError):
        return RealtimeStrategyConfig()


def sync_realtime_consumer_for_entry(entry: ScopedRuntimeEntry) -> dict[str, Any]:
    """Runtime Entry 상태에 맞춰 Hub Consumer 등록/갱신."""

    from stock_platform.common.settings import get_settings
    from stock_platform.realtime.market_data_hub import (
        get_realtime_market_data_hub,
    )

    if not bool(getattr(get_settings(), "realtime_hub_enabled", True)):
        return {"synced": False, "reason": "hub_disabled"}

    symbols = _symbols_for_entry(entry)
    if not symbols:
        return {
            "synced": False,
            "reason": "no_symbol",
            "scope_key": entry.scope.scope_key,
        }

    hub = get_realtime_market_data_hub()
    if entry.status == RuntimeLifecycleStatus.STOPPED:
        freed = hub.unregister_consumer(entry.scope)
        return {
            "synced": True,
            "action": "unregister",
            "freed_subscriptions": freed,
            "scope_key": entry.scope.scope_key,
        }

    try:
        hub.register_consumer(
            entry.scope,
            symbols,
            config=_config_from_entry(entry),
            runtime_status=entry.status,
        )
        hub.registry.set_runtime_status(
            entry.scope.scope_key,
            entry.status,
            pause_reason=entry.pause_reason,
        )
        return {
            "synced": True,
            "action": "register",
            "symbols": symbols,
            "scope_key": entry.scope.scope_key,
            "runtime_status": entry.status.value,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "realtime_consumer_sync_failed",
            scope_key=entry.scope.scope_key[:48],
            error_type=exc.__class__.__name__,
        )
        return {
            "synced": False,
            "reason": str(exc)[:200],
            "scope_key": entry.scope.scope_key,
        }


def unregister_realtime_consumer(scope: StrategyRuntimeScope | str) -> None:
    from stock_platform.realtime.market_data_hub import (
        get_realtime_market_data_hub,
    )

    get_realtime_market_data_hub().unregister_consumer(scope)
