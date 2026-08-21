"""Portfolio multi-symbol runtime / Hub / Upbit WS 동기화.

FULL_MARKET_PORTFOLIO: slot symbol set이 runtime SoT.
FULL_MARKET_SINGLE / FIXED: 변경하지 않음 (호출측에서 skip).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy.orm import Session

from stock_platform.operation.upbit_full_market.constants import (
    SLOT_RUNTIME_SYMBOL_STATUSES,
    is_full_market_portfolio,
)
from stock_platform.operation.upbit_full_market.entities import (
    UpbitPositionSlotEntity,
)
from stock_platform.strategy_deployment.runtime_models import (
    LoadedStrategyRuntime,
)
from stock_platform.strategy_deployment.symbol_payload import (
    apply_runtime_target_symbols,
    symbols_from_parameter_payload,
)

logger = structlog.get_logger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def desired_portfolio_symbols(session: Session, uba_id: int) -> list[str]:
    from sqlalchemy import select

    rows = list(
        session.scalars(
            select(UpbitPositionSlotEntity).where(
                UpbitPositionSlotEntity.user_broker_account_id == int(uba_id),
                UpbitPositionSlotEntity.status.in_(
                    list(SLOT_RUNTIME_SYMBOL_STATUSES)
                ),
            )
        )
    )
    out: list[str] = []
    for row in rows:
        sym = str(row.symbol or "").strip().upper()
        if sym and sym not in out:
            out.append(sym)
    return out


def sync_portfolio_runtime_symbols(
    session: Session,
    *,
    user_broker_account_id: int,
    ensure_quote_feed: bool = True,
) -> dict[str, Any]:
    """Slot symbol set → in-memory runtime payload + Hub consumer (+ optional WS).

    OPEN/EXIT_PENDING 심볼은 절대 제외하지 않는다 (desired set에 포함).
    """

    from stock_platform.operation.upbit_full_market.service import (
        UpbitFullMarketAssignmentService,
    )
    from stock_platform.realtime.runtime_bridge import (
        sync_realtime_consumer_for_entry,
    )
    from stock_platform.strategy_deployment.runtime_manager import (
        dynamic_strategy_runtime_manager,
    )

    uba_id = int(user_broker_account_id)
    assignment = UpbitFullMarketAssignmentService(session).get_or_create(uba_id)
    if not is_full_market_portfolio(assignment.mode):
        return {
            "ok": True,
            "skipped": True,
            "reason": "MODE_NOT_PORTFOLIO",
            "symbols": [],
        }

    desired = desired_portfolio_symbols(session, uba_id)
    result: dict[str, Any] = {
        "ok": True,
        "uba_id": uba_id,
        "desired_symbols": desired,
        "synced_scopes": [],
        "audit": "PORTFOLIO_RUNTIME_SYMBOLS_REALIGNED",
        "orders_created": 0,
    }
    if not desired:
        # 후보 없음 — consumer는 template/current 유지하지 않고 최소 no-op
        result["reason"] = "NO_SLOT_SYMBOLS"
        return result

    entries = dynamic_strategy_runtime_manager.list_entries(
        user_broker_account_id=uba_id,
    )
    entries = [
        e
        for e in entries
        if str(getattr(e.scope, "broker_code", "") or "").upper() == "UPBIT"
    ]
    if not entries:
        result["ok"] = False
        result["reason"] = "NO_RUNTIME_ENTRY"
        return result

    for entry in entries:
        prev = symbols_from_parameter_payload(
            getattr(entry.runtime, "parameter_payload", None)
        )
        new_payload = apply_runtime_target_symbols(
            getattr(entry.runtime, "parameter_payload", None),
            symbols=desired,
        )
        # frozen dataclass — 교체
        rt = entry.runtime
        entry.runtime = LoadedStrategyRuntime(
            deployment_id=rt.deployment_id,
            strategy_code=rt.strategy_code,
            market_code=rt.market_code,
            symbol=desired[0],
            parameter_payload=new_payload,
            loaded_at=rt.loaded_at,
            user_id=rt.user_id,
            account_id=rt.account_id,
            user_broker_account_id=rt.user_broker_account_id,
            strategy_id=rt.strategy_id,
            strategy_version=rt.strategy_version,
            market_type=rt.market_type,
            scope_key=rt.scope_key,
            broker_code=rt.broker_code,
            account_kind=rt.account_kind,
        )
        entry.updated_at = _now()
        hub = sync_realtime_consumer_for_entry(entry)
        result["synced_scopes"].append(
            {
                "scope_key": entry.scope.scope_key,
                "previous_symbols": prev,
                "symbols": desired,
                "hub": hub,
            }
        )

    feed: dict[str, Any] | None = None
    if ensure_quote_feed:
        feed = _ensure_upbit_quote_symbols(desired)
        result["quote_feed"] = feed
        if feed and feed.get("ok") is False:
            result["ok"] = False
            result["reason"] = str(feed.get("reason") or "QUOTE_FEED_SYNC_FAILED")

    # assignment.current_symbol은 summary/last-selected 용 (SoT 아님)
    if assignment.current_symbol not in desired:
        assignment.current_symbol = desired[0]
        session.flush()

    from stock_platform.operation.upbit_full_market.portfolio_entry_signal import (
        attach_portfolio_entry_context_to_hub,
    )

    try:
        result["entry_context"] = attach_portfolio_entry_context_to_hub(
            session, uba_id
        )
    except Exception as exc:  # noqa: BLE001
        result["entry_context"] = {
            "ok": False,
            "error": type(exc).__name__,
            "message": str(exc)[:200],
        }

    logger.info(
        "portfolio_runtime_symbols_realigned",
        uba_id=uba_id,
        symbols=desired,
        scopes=len(result["synced_scopes"]),
    )
    return result


def _ensure_upbit_quote_symbols(symbols: list[str]) -> dict[str, Any]:
    """Upbit public WS가 desired 심볼을 포함하도록 보장 (필요 시 restart)."""

    import asyncio

    try:
        from stock_platform.realtime.manager import realtime_manager
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": type(exc).__name__}

    desired = [str(s).upper() for s in symbols if s]
    if not desired:
        return {"ok": True, "reason": "NO_SYMBOLS"}

    clients = getattr(realtime_manager, "_clients", {}) or {}
    client = clients.get("UPBIT")
    current: list[str] = []
    if client is not None and hasattr(client, "status"):
        current = [
            str(x).upper()
            for x in (client.status().get("symbols") or [])
            if x
        ]
    missing = [s for s in desired if s not in current]
    if client is not None and not missing:
        return {
            "ok": True,
            "already_covering": True,
            "symbols": current,
        }

    union = list(dict.fromkeys([*current, *desired]))

    async def _restart() -> dict[str, Any]:
        # 기존 task 종료 후 union으로 재기동 (hot-expand API 없음)
        await realtime_manager.stop("UPBIT")
        return await realtime_manager.start_upbit(
            symbols=union,
            channels=["ticker", "trade"],
            connect_timeout_seconds=5.0,
        )

    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None and loop.is_running():
            # sync 경로에서 호출되면 백그라운드 태스크로 예약
            fut = asyncio.ensure_future(_restart())
            return {
                "ok": True,
                "scheduled": True,
                "symbols": union,
                "future": True,
                "task": str(fut),
            }
        status = asyncio.run(_restart())
        return {
            "ok": bool(status.get("connected") or status.get("task_running")),
            "restarted": True,
            "symbols": union,
            "status": {
                "connected": status.get("connected"),
                "symbols": status.get("symbols"),
            },
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": type(exc).__name__}
