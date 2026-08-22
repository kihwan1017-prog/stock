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
    """Portfolio Hub/WS desired = slot runtime ∪ OPEN AUTO positions.

    Slot에서 빠져도 OPEN binding이면 feed/runtime에서 제거하지 않는다.
    """

    from sqlalchemy import select

    from stock_platform.operation.upbit_full_market.constants import (
        BINDING_STATUS_EXIT_PENDING,
        BINDING_STATUS_OPEN,
    )
    from stock_platform.operation.upbit_full_market.entities import (
        UpbitStrategyPositionBindingEntity,
    )
    from stock_platform.risk_engine.strategy_owned_entities import (
        StrategyPositionBindingEntity,
    )

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

    # OPEN / EXIT_PENDING AUTO bindings — slot 유무와 무관하게 feed 필수
    for entity, status_field in (
        (StrategyPositionBindingEntity, "status"),
        (UpbitStrategyPositionBindingEntity, "status"),
    ):
        bind_rows = list(
            session.scalars(
                select(entity).where(
                    entity.user_broker_account_id == int(uba_id),
                    getattr(entity, status_field).in_(
                        [BINDING_STATUS_OPEN, BINDING_STATUS_EXIT_PENDING]
                    ),
                )
            )
        )
        for row in bind_rows:
            if str(getattr(row, "broker_code", "UPBIT") or "UPBIT").upper() not in {
                "UPBIT",
                "",
            }:
                continue
            qty = getattr(row, "owned_quantity", None)
            if qty is not None:
                try:
                    from decimal import Decimal

                    if Decimal(str(qty)) <= 0:
                        continue
                except Exception:  # noqa: BLE001
                    pass
            sym = str(row.symbol or "").strip().upper()
            if sym and sym not in out:
                out.append(sym)
    return out


def collect_upbit_open_auto_position_symbols(
    session: Session,
    *,
    user_broker_account_id: int | None = None,
) -> list[str]:
    """UPBIT OPEN AUTO position symbols (UBA 필터 optional, global WS용)."""

    from sqlalchemy import select

    from stock_platform.operation.upbit_full_market.constants import (
        BINDING_STATUS_EXIT_PENDING,
        BINDING_STATUS_OPEN,
    )
    from stock_platform.operation.upbit_full_market.entities import (
        UpbitStrategyPositionBindingEntity,
    )
    from stock_platform.risk_engine.strategy_owned_entities import (
        StrategyPositionBindingEntity,
    )
    from stock_platform.trading.account_models import UserBrokerAccount

    out: list[str] = []
    statuses = [BINDING_STATUS_OPEN, BINDING_STATUS_EXIT_PENDING]

    def _append(sym: str) -> None:
        s = str(sym or "").strip().upper()
        if s and s not in out:
            out.append(s)

    q1 = select(StrategyPositionBindingEntity).where(
        StrategyPositionBindingEntity.status.in_(statuses),
        StrategyPositionBindingEntity.broker_code == "UPBIT",
    )
    if user_broker_account_id is not None:
        q1 = q1.where(
            StrategyPositionBindingEntity.user_broker_account_id
            == int(user_broker_account_id)
        )
    for row in session.scalars(q1):
        try:
            from decimal import Decimal

            if Decimal(str(row.owned_quantity or 0)) <= 0:
                continue
        except Exception:  # noqa: BLE001
            continue
        _append(row.symbol)

    q2 = select(UpbitStrategyPositionBindingEntity).where(
        UpbitStrategyPositionBindingEntity.status.in_(statuses),
    )
    if user_broker_account_id is not None:
        q2 = q2.where(
            UpbitStrategyPositionBindingEntity.user_broker_account_id
            == int(user_broker_account_id)
        )
    else:
        # UPBIT UBA만
        upbit_ubas = {
            int(x)
            for x in session.scalars(
                select(UserBrokerAccount.user_broker_account_id).where(
                    UserBrokerAccount.broker_code == "UPBIT",
                    UserBrokerAccount.is_active.is_(True),
                )
            )
        }
        if upbit_ubas:
            q2 = q2.where(
                UpbitStrategyPositionBindingEntity.user_broker_account_id.in_(
                    list(upbit_ubas)
                )
            )
    for row in session.scalars(q2):
        _append(row.symbol)
    return out


def ensure_protective_quote_feed(
    session: Session,
    *,
    user_broker_account_id: int | None = None,
) -> dict[str, Any]:
    """OPEN AUTO ∪ (portfolio면 slot) 심볼을 Upbit WS에 포함.

    포트폴리오 sync와 독립 — FIXED/SINGLE·슬롯 없는 controlled BUY 후 보호용.
    """

    symbols: list[str] = []
    if user_broker_account_id is not None:
        uba_id = int(user_broker_account_id)
        try:
            from stock_platform.operation.upbit_full_market.service import (
                UpbitFullMarketAssignmentService,
            )

            assignment = UpbitFullMarketAssignmentService(
                session
            ).get_or_create(uba_id)
            if is_full_market_portfolio(assignment.mode):
                symbols.extend(desired_portfolio_symbols(session, uba_id))
            else:
                symbols.extend(
                    collect_upbit_open_auto_position_symbols(
                        session, user_broker_account_id=uba_id
                    )
                )
                cur = str(assignment.current_symbol or "").strip().upper()
                if cur and cur not in symbols:
                    symbols.append(cur)
                tmpl = str(assignment.template_symbol or "").strip().upper()
                if tmpl and tmpl not in symbols:
                    symbols.append(tmpl)
        except Exception:  # noqa: BLE001
            symbols.extend(
                collect_upbit_open_auto_position_symbols(
                    session, user_broker_account_id=uba_id
                )
            )
    else:
        symbols.extend(collect_upbit_open_auto_position_symbols(session))
        # 모든 portfolio UBA slot도 포함
        try:
            from sqlalchemy import select

            from stock_platform.operation.upbit_full_market.entities import (
                UpbitFullMarketAssignmentEntity,
            )
            from stock_platform.operation.upbit_full_market.constants import (
                MODE_FULL_MARKET_PORTFOLIO,
            )

            uba_ids = list(
                session.scalars(
                    select(
                        UpbitFullMarketAssignmentEntity.user_broker_account_id
                    ).where(
                        UpbitFullMarketAssignmentEntity.mode
                        == MODE_FULL_MARKET_PORTFOLIO
                    )
                )
            )
            for uid in uba_ids:
                for sym in desired_portfolio_symbols(session, int(uid)):
                    if sym not in symbols:
                        symbols.append(sym)
        except Exception:  # noqa: BLE001
            pass

    feed = _ensure_upbit_quote_symbols(symbols)
    return {
        "ok": bool(feed.get("ok", True)),
        "symbols": symbols,
        "quote_feed": feed,
    }


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
