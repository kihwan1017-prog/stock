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
) -> dict[str, Any]:
    """Hub UPBIT subscription 기준으로 Quote WS 복구 (idempotent).

    - LIVE/ARM/Runtime RUN 하지 않음
    - duplicate task 생성 안 함 (start_upbit already_running)
    - subscription 없으면 no-op
    """

    symbols = collect_upbit_symbols_from_hub()
    result: dict[str, Any] = {
        "source": source,
        "symbols": symbols,
        "started": False,
    }
    if not symbols:
        result["reason"] = "NO_UPBIT_HUB_SUBSCRIPTIONS"
        return result

    try:
        from stock_platform.realtime.manager import realtime_manager

        status = await realtime_manager.start_upbit(
            symbols=symbols,
            channels=channels or ["ticker", "trade"],
            connect_timeout_seconds=connect_timeout_seconds,
        )
        result["started"] = not bool(status.get("already_running"))
        result["already_running"] = bool(status.get("already_running"))
        result["status"] = {
            "connected": status.get("connected"),
            "running": status.get("running"),
            "task_running": status.get("task_running"),
            "symbols": status.get("symbols"),
            "received_count": status.get("received_count"),
            "last_error": status.get("last_error"),
        }
        logger.info(
            "upbit_quote_feed_ensure",
            source=source,
            symbols=symbols,
            started=result["started"],
            already_running=result.get("already_running"),
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
        result["reason"] = type(exc).__name__
        result["error"] = type(exc).__name__
        return result
