"""Kiwoom fill → broker_position_snapshot WRITE 보장 (K_ONLY).

LiveFillLedgerService 시맨틱은 변경하지 않는다.
ExecutionSync 이후 silent ledger 실패를 Kiwoom 경로에서 idempotent 재적용한다.
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy.orm import Session

from stock_platform.broker.kiwoom.execution_models import KiwoomExecutionEvent
from stock_platform.broker.live_fill_ledger_service import LiveFillLedgerService

logger = structlog.get_logger(__name__)


def apply_kiwoom_fill_position_write(
    session: Session,
    *,
    order: Any,
    event: KiwoomExecutionEvent,
    actor: str = "KIWOOM_FILL_POSITION_WRITE",
    commit: bool = True,
) -> dict[str, Any]:
    """TradingOrder 체결 이벤트를 FILL_DRIVEN position snapshot에 반영.

    LiveFillLedger의 applied_execution_ids 로 duplicate 안전.
    """

    uba_id = getattr(order, "user_broker_account_id", None)
    if uba_id is None:
        return {"applied": False, "reason": "NO_UBA"}

    ledger = LiveFillLedgerService(session)
    result = ledger.apply_execution(order=order, event=event, actor=actor)
    binding_meta: dict[str, Any] = {}
    if result.get("applied"):
        try:
            strategy_id = getattr(order, "strategy_id", None)
            if strategy_id is not None:
                from decimal import Decimal

                from stock_platform.risk_engine.strategy_owned_risk_service import (
                    StrategyOwnedRiskService,
                )

                qty = Decimal(
                    str(
                        getattr(event, "filled_quantity", None)
                        or getattr(event, "quantity", None)
                        or 0
                    )
                )
                px = getattr(event, "fill_price", None) or getattr(
                    event, "price", None
                )
                side = str(
                    getattr(event, "side", None)
                    or getattr(order, "side_code", "")
                    or ""
                ).upper()
                # Upbit fill_sync와 동일: BUY=entry, SELL=exit (SELL을 entry로 쓰지 않음)
                is_buy = side in {"BUY", "BID"}
                is_sell = side in {"SELL", "ASK"}
                order_id = getattr(order, "order_id", None)
                StrategyOwnedRiskService(session).ensure_binding_from_fill(
                    user_broker_account_id=int(uba_id),
                    broker_code=str(
                        getattr(order, "broker_code", None) or "KIWOOM"
                    ),
                    strategy_id=int(strategy_id),
                    deployment_id=getattr(order, "strategy_deployment_id", None),
                    symbol=str(getattr(order, "symbol", "") or ""),
                    entry_order_id=(
                        int(order_id) if is_buy and order_id is not None else None
                    ),
                    broker_order_id=str(
                        getattr(event, "broker_order_id", None) or ""
                    )
                    or None,
                    quantity=qty,
                    entry_price=(
                        Decimal(str(px))
                        if is_buy and px is not None
                        else None
                    ),
                    side=side,
                    fill_price=(
                        Decimal(str(px))
                        if is_sell and px is not None
                        else None
                    ),
                    exit_order_id=(
                        int(order_id)
                        if is_sell and order_id is not None
                        else None
                    ),
                )
                StrategyOwnedRiskService(session).compute_and_persist(
                    user_broker_account_id=int(uba_id),
                    broker_code=str(
                        getattr(order, "broker_code", None) or "KIWOOM"
                    ),
                    strategy_id=int(strategy_id),
                    deployment_id=getattr(order, "strategy_deployment_id", None),
                )
                binding_meta = {"strategy_binding": True}
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "strategy_owned_binding_failed",
                error=type(exc).__name__,
                order_id=getattr(order, "order_id", None),
            )
            binding_meta = {
                "strategy_binding": False,
                "error": type(exc).__name__,
            }
    if commit and result.get("applied"):
        session.commit()
    elif commit and result.get("reason") == "DUPLICATE_EXECUTION":
        # 이미 반영됨 — 트랜잭션만 정리
        try:
            session.commit()
        except Exception:  # noqa: BLE001
            session.rollback()
    out = dict(result)
    out.update(binding_meta)
    return out


def ensure_kiwoom_position_after_sync(
    session: Session,
    *,
    order: Any | None,
    event: KiwoomExecutionEvent | None,
    actor: str,
) -> dict[str, Any]:
    """ExecutionSync 직후 호출 — ledger 누락 시 재적용."""

    if order is None or event is None:
        return {"applied": False, "reason": "NO_ORDER_OR_EVENT"}
    try:
        return apply_kiwoom_fill_position_write(
            session,
            order=order,
            event=event,
            actor=actor,
            commit=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "kiwoom_fill_position_write_failed",
            error=str(exc),
            broker_execution_id=getattr(event, "broker_execution_id", None),
            order_id=getattr(order, "order_id", None),
        )
        try:
            session.rollback()
        except Exception:  # noqa: BLE001
            pass
        return {"applied": False, "reason": "ERROR", "error": str(exc)}
