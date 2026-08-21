"""STEP 8-5-9 — Runtime Lifecycle ↔ Realtime Hub 브리지."""

from __future__ import annotations

from decimal import Decimal
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
    from stock_platform.strategy_deployment.symbol_payload import (
        symbols_from_parameter_payload,
    )

    payload_symbols = symbols_from_parameter_payload(
        getattr(entry.runtime, "parameter_payload", None)
    )
    if payload_symbols:
        return payload_symbols
    symbol = (entry.runtime.symbol or "").strip().upper()
    if symbol:
        return [symbol]
    return []


def _payload_timeframe(payload: dict[str, Any]) -> str:
    return str(payload.get("timeframe") or "").strip()


def _payload_cooldown_bars(payload: dict[str, Any]) -> int | None:
    """Paper cooldown_bars. LIVE seconds cooldown과 별개 — 값을 바꾸지 않고 전달만 한다."""

    raw_cfg = payload.get("indicator_configuration")
    if not isinstance(raw_cfg, dict):
        return None
    value = raw_cfg.get("cooldown_bars")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _config_from_entry(entry: ScopedRuntimeEntry) -> RealtimeStrategyConfig:
    payload = entry.runtime.parameter_payload or {}
    timeframe = _payload_timeframe(payload)
    cooldown_bars = _payload_cooldown_bars(payload)
    try:
        short = int(payload.get("short_window", payload.get("short", 5)))
        long = int(payload.get("long_window", payload.get("long", 20)))
        cool = int(payload.get("cooldown_seconds", 30))
        # SL/TP — payload 없으면 RealtimeStrategyConfig 기본값
        stop = Decimal(
            str(
                payload.get(
                    "stop_loss_ratio",
                    payload.get("stop_loss", "0.03"),
                )
            )
        )
        take = Decimal(
            str(
                payload.get(
                    "take_profit_ratio",
                    payload.get("take_profit", "0.06"),
                )
            )
        )
        return RealtimeStrategyConfig(
            short_window=max(1, short),
            long_window=max(short + 1, long),
            cooldown_seconds=max(0, cool),
            stop_loss_ratio=max(Decimal("0"), stop),
            take_profit_ratio=max(Decimal("0"), take),
            timeframe=timeframe,
            cooldown_bars=cooldown_bars,
        )
    except (TypeError, ValueError):
        return RealtimeStrategyConfig(
            timeframe=timeframe,
            cooldown_bars=cooldown_bars,
        )


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
        config = _config_from_entry(entry)
        consumer = hub.register_consumer(
            entry.scope,
            symbols,
            config=config,
            runtime_status=entry.status,
        )
        hub.registry.set_runtime_status(
            entry.scope.scope_key,
            entry.status,
            pause_reason=entry.pause_reason,
        )
        daily_seed: dict[str, Any] | None = None
        if config.uses_daily_bars():
            from stock_platform.realtime.daily_bar_seed import (
                seed_registered_consumer,
            )

            try:
                daily_seed = seed_registered_consumer(consumer)
            except Exception as seed_exc:  # noqa: BLE001
                logger.warning(
                    "realtime_daily_bar_seed_failed",
                    scope_key=entry.scope.scope_key[:48],
                    error_type=seed_exc.__class__.__name__,
                )
                daily_seed = {
                    "seeded": False,
                    "reason": seed_exc.__class__.__name__,
                }

        # Portfolio UBA: restart/resume 후에도 BULLISH ctx를 항상 재부착
        entry_ctx: dict[str, Any] | None = None
        try:
            from stock_platform.strategy_deployment.runtime_scope import (
                AccountKind,
            )

            if (
                str(getattr(entry.scope, "broker_code", "") or "").upper()
                == "UPBIT"
                and getattr(entry.scope, "account_kind", None)
                == AccountKind.USER_BROKER
            ):
                from stock_platform.operation.upbit_full_market.portfolio_entry_signal import (
                    ensure_portfolio_entry_evaluator_for_uba,
                )

                entry_ctx = ensure_portfolio_entry_evaluator_for_uba(
                    int(entry.scope.account_id)
                )
        except Exception as ctx_exc:  # noqa: BLE001
            entry_ctx = {
                "ok": False,
                "error": type(ctx_exc).__name__,
                "message": str(ctx_exc)[:200],
            }

        return {
            "synced": True,
            "action": "register",
            "symbols": symbols,
            "scope_key": entry.scope.scope_key,
            "runtime_status": entry.status.value,
            "timeframe": config.timeframe or "",
            "ma_input_unit": "DAY" if config.uses_daily_bars() else "TICK",
            "daily_seed": daily_seed,
            "portfolio_entry_context": entry_ctx,
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
