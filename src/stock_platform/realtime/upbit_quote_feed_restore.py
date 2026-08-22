"""Hub 구독 기준 Upbit 공개 시세 Feed 복구.

Backend restart/reload 시 in-memory Quote WS가 유실되어도,
Hub에 등록된 UPBIT market-data subscription이 있으면
실주문/LIVE/Runtime RUN 없이 시세만 idempotent 재연결한다.

모든 UBA를 무조건 start하지 않는다 — Hub subscription 심볼만 대상.
"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger(__name__)


def collect_upbit_symbols_from_hub() -> list[str]:
    """Hub registry의 UPBIT market-data subscription 심볼 목록."""

    try:
        from stock_platform.realtime.market_data_hub import (
            get_realtime_market_data_hub,
        )

        hub = get_realtime_market_data_hub()
        rows = hub.registry.list_subscriptions()
    except Exception:  # noqa: BLE001
        return []

    symbols: list[str] = []
    seen: set[str] = set()
    for row in rows or []:
        broker = str(row.get("broker_code") or "").strip().upper()
        symbol = str(row.get("symbol") or "").strip().upper()
        if broker != "UPBIT" or not symbol:
            continue
        if symbol in seen:
            continue
        seen.add(symbol)
        symbols.append(symbol)
    return symbols


def hub_has_upbit_subscriptions() -> bool:
    return bool(collect_upbit_symbols_from_hub())


async def ensure_upbit_quote_feed_from_hub(
    *,
    channels: list[str] | None = None,
    connect_timeout_seconds: float = 5.0,
    source: str = "HUB_SUBSCRIPTION_RESTORE",
    session: Any | None = None,
) -> dict[str, Any]:
    """Hub ∪ OPEN AUTO position 심볼 기준 Quote WS 복구 (idempotent).

    - LIVE/ARM/Runtime RUN 하지 않음
    - missing 심볼이면 expand restart
    - Hub·OPEN binding 모두 없으면 no-op
    """

    symbols = collect_upbit_symbols_from_hub()
    open_auto: list[str] = []
    if session is not None:
        try:
            from stock_platform.operation.upbit_full_market.portfolio_runtime_sync import (
                collect_upbit_open_auto_position_symbols,
            )

            open_auto = collect_upbit_open_auto_position_symbols(session)
        except Exception:  # noqa: BLE001
            open_auto = []
    else:
        # restart path — short-lived session
        try:
            from stock_platform.database.session import get_session_factory
            from stock_platform.operation.upbit_full_market.portfolio_runtime_sync import (
                collect_upbit_open_auto_position_symbols,
            )

            sf = get_session_factory()
            with sf() as db:
                open_auto = collect_upbit_open_auto_position_symbols(db)
        except Exception:  # noqa: BLE001
            open_auto = []

    for sym in open_auto:
        if sym not in symbols:
            symbols.append(sym)

    result: dict[str, Any] = {
        "source": source,
        "symbols": symbols,
        "hub_symbols": collect_upbit_symbols_from_hub(),
        "open_auto_symbols": open_auto,
        "started": False,
    }
    if not symbols:
        result["reason"] = "NO_UPBIT_HUB_OR_OPEN_AUTO_SYMBOLS"
        return result

    try:
        from stock_platform.realtime.manager import realtime_manager

        status = await realtime_manager.start_upbit(
            symbols=symbols,
            channels=channels or ["ticker", "trade"],
            connect_timeout_seconds=connect_timeout_seconds,
        )
        result["started"] = True
        result["status"] = status
        result["already_running"] = bool(status.get("already_running"))
        result["expanded"] = bool(status.get("expanded"))
        logger.info(
            "upbit_quote_feed_ensure",
            source=source,
            symbols=symbols,
            open_auto=open_auto,
            started=result["started"],
            already_running=result.get("already_running"),
            expanded=result.get("expanded"),
            connected=status.get("connected"),
        )
        return result
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "upbit_quote_feed_ensure_failed",
            source=source,
            error=type(exc).__name__,
            detail=str(exc)[:200],
        )
        result["ok"] = False
        result["reason"] = type(exc).__name__
        result["error"] = type(exc).__name__
        return result
