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
        # Alert V2 — fill 성공 후 알림만 (fail-open, trading 미영향)
        try:
            _emit_kiwoom_fill_alert_v2(order=order, event=event)
            binding_meta["alert_v2_emit"] = True
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "kiwoom_alert_v2_emit_failed",
                error=type(exc).__name__,
                order_id=getattr(order, "order_id", None),
            )
            binding_meta["alert_v2_emit"] = False
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


def _emit_kiwoom_fill_alert_v2(*, order: Any, event: KiwoomExecutionEvent) -> None:
    """Kiwoom AUTO fill → Alert V2 Telegram. 실패해도 체결 경로 유지."""

    try:
        from decimal import Decimal

        from stock_platform.order.live_safety_audit import emit_live_order_telegram

        status = str(getattr(order, "status_code", "") or "").upper()
        # 부분체결 spam 방지: FILLED 중심 (부분은 PARTIAL 이벤트만)
        side = str(
            getattr(event, "side", None) or getattr(order, "side_code", "") or ""
        ).upper()
        if side in {"BID"}:
            side = "BUY"
        if side in {"ASK"}:
            side = "SELL"
        oid = getattr(order, "order_id", None)
        if oid is None:
            return
        meta = dict(getattr(order, "metadata_payload", None) or {})
        if meta.get("fill_lifecycle_notified"):
            return
        qty = getattr(event, "filled_quantity", None) or getattr(
            event, "quantity", None
        ) or getattr(order, "filled_quantity", None)
        px = getattr(event, "fill_price", None) or getattr(
            event, "price", None
        ) or getattr(order, "average_fill_price", None)
        fee = getattr(event, "fee", None) or meta.get("fee") or meta.get("paid_fee")
        symbol = str(getattr(order, "symbol", "") or "")
        strategy_id = getattr(order, "strategy_id", None)
        deployment_id = getattr(order, "strategy_deployment_id", None)
        order_source = str(
            getattr(order, "order_source", None) or meta.get("order_source") or ""
        ).upper()
        detail: dict[str, Any] = {
            "order_id": int(oid),
            "symbol": symbol,
            "symbol_name": meta.get("symbol_name") or meta.get("korean_name"),
            "side": side,
            "filled_qty": str(qty) if qty is not None else None,
            "filled_quantity": str(qty) if qty is not None else None,
            "avg_fill_price": str(px) if px is not None else None,
            "average_fill_price": str(px) if px is not None else None,
            "fee": str(fee) if fee is not None else None,
            "broker_code": "KIWOOM",
            "market": "KIWOOM",
            "broker_order_id": getattr(event, "broker_order_id", None)
            or getattr(order, "broker_order_id", None),
            "order_source": order_source or None,
            "strategy_id": strategy_id,
            "strategy_deployment_id": deployment_id,
            "entry_reason": meta.get("entry_reason") or meta.get("signal_reason"),
            "exit_reason": meta.get("exit_reason") or meta.get("signal_reason"),
            "ai_recommendation": meta.get("ai_recommendation"),
            "ai_confidence": meta.get("ai_confidence") or meta.get("confidence"),
            "entry_price": meta.get("entry_price"),
            "realized_pnl": meta.get("realized_pnl"),
            "realized_pnl_pct": meta.get("realized_pnl_pct"),
            "total_fee": meta.get("total_fee") or meta.get("fees") or fee,
            "holding_seconds": meta.get("holding_seconds"),
            "opened_at": meta.get("opened_at"),
            "closed_at": meta.get("closed_at"),
        }
        try:
            if px is not None and qty is not None:
                detail["gross_amount"] = str(Decimal(str(px)) * Decimal(str(qty)))
        except Exception:  # noqa: BLE001
            pass

        is_filled = status in {"FILLED", "COMPLETED"} or str(
            getattr(event, "status", "") or ""
        ).upper() in {"FILLED", "COMPLETED"}
        is_partial = status in {"PARTIAL_FILLED", "PARTIALLY_FILLED"} or str(
            getattr(event, "status", "") or ""
        ).upper() in {"PARTIAL", "PARTIAL_FILLED", "PARTIALLY_FILLED"}

        if side == "SELL" and is_filled and (
            meta.get("position_closed") or meta.get("binding_closed")
        ):
            detail["dedupe_key"] = f"SELL_FILLED:{int(oid)}"
            emit_live_order_telegram(
                event_type="POSITION_CLOSED",
                title="매도 체결",
                message="",
                detail=detail,
            )
        elif side == "SELL" and is_filled:
            detail["dedupe_key"] = f"SELL_FILLED:{int(oid)}"
            emit_live_order_telegram(
                event_type="ORDER_FILLED",
                title="매도 체결",
                message="",
                detail=detail,
            )
        elif side == "BUY" and is_filled:
            detail["dedupe_key"] = f"BUY_FILLED:{int(oid)}"
            emit_live_order_telegram(
                event_type="ORDER_FILLED",
                title="매수 체결",
                message="",
                detail=detail,
            )
        elif is_partial:
            detail["dedupe_key"] = f"PARTIAL_FILLED:{int(oid)}"
            emit_live_order_telegram(
                event_type="ORDER_PARTIAL_FILLED",
                title="부분 체결",
                message="",
                detail=detail,
            )
        else:
            return

        # best-effort mark (caller session may commit after)
        try:
            meta["fill_lifecycle_notified"] = True
            order.metadata_payload = meta
            from sqlalchemy.orm.attributes import flag_modified

            flag_modified(order, "metadata_payload")
        except Exception:  # noqa: BLE001
            pass
    except Exception:  # noqa: BLE001 — NOTIFICATION_FAIL_OPEN
        return


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
