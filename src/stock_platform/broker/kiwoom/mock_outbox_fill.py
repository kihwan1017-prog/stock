"""Kiwoom MOCK Outbox ACCEPTED → 결정적 부분/완전 체결 (LIVE HTTP 0)."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from stock_platform.broker.kiwoom.mock_gateway import KiwoomMockOrderGateway
from stock_platform.broker.kiwoom.ws_models import KiwoomOrderEventType
from stock_platform.broker.live_fill_ledger_service import (
    LiveFillLedgerService,
)
from stock_platform.database.session import get_session_factory
from stock_platform.order.entities import TradingOrderEntity
from stock_platform.order.models import OrderStatus


def fill_mock_accepted_order(
    session: Session | None,
    order_id: int,
    *,
    actor: str = "OUTBOX_KIWOOM_MOCK_AUTO_FILL",
) -> dict:
    """ACCEPTED MOCK 주문을 부분→완전 체결로 반영.

    Worker 세션과 분리된 전용 Session을 사용해 Outbox PROCESSING
    트랜잭션을 중간 commit으로 깨지 않는다.
    """

    _ = session  # 호출부 호환 — 실제 작업은 전용 세션
    SessionLocal = get_session_factory()
    with SessionLocal() as own:
        order = own.get(TradingOrderEntity, int(order_id))
        if order is None:
            return {"filled": False, "reason": "ORDER_NOT_FOUND"}

        meta = dict(order.metadata_payload or {})
        env = str(meta.get("environment") or "PAPER").upper()
        if env == "LIVE":
            return {"filled": False, "reason": "LIVE_ENVIRONMENT_BLOCKED"}
        if env != "MOCK":
            return {"filled": False, "reason": "NOT_MOCK"}
        if str(order.broker_code or "").upper() != "KIWOOM":
            return {"filled": False, "reason": "NOT_KIWOOM"}
        if order.user_broker_account_id is None:
            return {"filled": False, "reason": "NO_UBA"}
        if order.status_code != OrderStatus.ACCEPTED.value:
            return {"filled": False, "reason": "NOT_ACCEPTED"}
        if not order.broker_order_id:
            return {"filled": False, "reason": "NO_BROKER_ORDER_ID"}

        qty = Decimal(str(order.order_quantity))
        price = Decimal(str(order.order_price or 0))
        if qty <= 0 or price <= 0:
            return {"filled": False, "reason": "INVALID_QTY_PRICE"}

        LiveFillLedgerService(own).ensure_cash_seed(
            user_broker_account_id=int(order.user_broker_account_id),
            broker_code="KIWOOM",
        )
        own.commit()

        broker_order_id = str(order.broker_order_id)
        symbol = str(order.symbol)
        side = str(order.side_code)
        oid = int(order.order_id)

        gw = KiwoomMockOrderGateway(own)
        partial = (qty / Decimal("2")).quantize(Decimal("0.00000001"))
        if partial <= 0 or partial >= qty:
            partial = qty

        if partial < qty:
            gw.apply_fill_event(
                broker_order_id=broker_order_id,
                filled_quantity=partial,
                remaining_quantity=qty - partial,
                fill_price=price,
                event_type=KiwoomOrderEventType.PARTIALLY_FILLED,
                symbol=symbol,
                side=side,
                broker_execution_id=f"MOCKAUTO:{oid}:P",
                actor=actor,
            )

        gw.apply_fill_event(
            broker_order_id=broker_order_id,
            filled_quantity=qty,
            remaining_quantity=Decimal("0"),
            fill_price=price,
            event_type=KiwoomOrderEventType.FILLED,
            symbol=symbol,
            side=side,
            broker_execution_id=f"MOCKAUTO:{oid}:F",
            actor=actor,
        )

        own.expire_all()
        order = own.get(TradingOrderEntity, oid)
        return {
            "filled": True,
            "reason": "OK",
            "order_status": order.status_code if order else None,
            "steps": 2 if partial < qty else 1,
        }
