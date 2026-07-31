"""Paper Outbox ACCEPTED → PaperOrder + Position/Balance/PnL 반영.

LIVE 경로와 혼입 금지. TradingOrder.order_id 는 paper_trade FK 대상이
아니므로 PaperOrder를 미러 생성한 뒤 PaperExecutionService로 체결한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from stock_platform.order.models import OrderStatus
from stock_platform.order.repository import TradingOrderRepository
from stock_platform.trading.execution_service import PaperExecutionService
from stock_platform.trading.models import OrderSide, OrderType
from stock_platform.trading.paper_engine import PaperOrderValidationError
from stock_platform.trading.repository import PaperOrderRepository
from stock_platform.trading.service import PaperOrderService


@dataclass(frozen=True, slots=True)
class PaperOutboxFillResult:
    filled: bool
    skipped: bool
    reason_code: str
    order_id: int | None
    trade_id: int | None = None
    paper_order_id: int | None = None
    order_status: str | None = None


class PaperOutboxFillService:
    """ACCEPTED TradingOrder → PaperOrder fill → TradingOrder FILLED."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._orders = TradingOrderRepository(session)
        self._paper_orders = PaperOrderService(PaperOrderRepository(session))
        self._paper_exec = PaperExecutionService(session)

    def fill_accepted_order(
        self,
        order_id: int,
        *,
        actor: str = "PAPER_OUTBOX_AUTO_FILL",
        environment_hint: str | None = None,
    ) -> PaperOutboxFillResult:
        order = self._orders.get(int(order_id))
        if order is None:
            return PaperOutboxFillResult(
                filled=False,
                skipped=True,
                reason_code="ORDER_NOT_FOUND",
                order_id=None,
            )

        metadata: dict[str, Any] = dict(order.metadata_payload or {})
        environment = str(
            environment_hint
            or metadata.get("environment")
            or "PAPER"
        ).strip().upper()

        if environment == "LIVE":
            return PaperOutboxFillResult(
                filled=False,
                skipped=True,
                reason_code="LIVE_ENVIRONMENT_BLOCKED",
                order_id=order.order_id,
                order_status=order.status_code,
            )
        if order.user_broker_account_id is not None:
            return PaperOutboxFillResult(
                filled=False,
                skipped=True,
                reason_code="USER_BROKER_ACCOUNT_BLOCKED",
                order_id=order.order_id,
                order_status=order.status_code,
            )

        status = OrderStatus(order.status_code)
        if status in {
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
        }:
            return PaperOutboxFillResult(
                filled=False,
                skipped=True,
                reason_code="ALREADY_TERMINAL",
                order_id=order.order_id,
                order_status=order.status_code,
            )
        if status not in {
            OrderStatus.ACCEPTED,
            OrderStatus.PARTIALLY_FILLED,
        }:
            return PaperOutboxFillResult(
                filled=False,
                skipped=True,
                reason_code="NOT_ACCEPTED",
                order_id=order.order_id,
                order_status=order.status_code,
            )

        # 이미 미러 PaperOrder가 있으면 재사용 (idempotent)
        existing_paper_id = metadata.get("paper_order_id")
        remaining = Decimal(str(order.remaining_quantity or 0))
        if remaining <= 0:
            remaining = Decimal(str(order.order_quantity or 0)) - Decimal(
                str(order.filled_quantity or 0)
            )
        if remaining <= 0:
            return PaperOutboxFillResult(
                filled=False,
                skipped=True,
                reason_code="NO_REMAINING_QUANTITY",
                order_id=order.order_id,
                order_status=order.status_code,
            )

        fill_price = order.order_price
        if fill_price is None or Decimal(str(fill_price)) <= 0:
            return PaperOutboxFillResult(
                filled=False,
                skipped=True,
                reason_code="FILL_PRICE_MISSING",
                order_id=order.order_id,
                order_status=order.status_code,
            )
        fill_price = Decimal(str(fill_price))

        try:
            if existing_paper_id is not None:
                paper_order_id = int(existing_paper_id)
            else:
                paper_order = self._paper_orders.create(
                    account_id=int(order.account_id),
                    exchange_code=str(order.exchange_code),
                    symbol=str(order.symbol),
                    side=OrderSide(str(order.side_code).upper()),
                    order_type=OrderType(
                        str(order.order_type_code or "LIMIT").upper()
                    )
                    if str(order.order_type_code or "").upper()
                    in {"LIMIT", "MARKET"}
                    else OrderType.LIMIT,
                    quantity=remaining,
                    price=fill_price,
                    auto_accept=True,
                )
                paper_order_id = int(paper_order.order_id)
                metadata["paper_order_id"] = paper_order_id
                metadata["trading_order_id"] = int(order.order_id)

            fill_result = self._paper_exec.apply_fill(
                account_id=int(order.account_id),
                order_id=paper_order_id,
                fill_quantity=remaining,
                fill_price=fill_price,
            )
        except (
            PaperOrderValidationError,
            LookupError,
            ValueError,
            RuntimeError,
        ) as exc:
            return PaperOutboxFillResult(
                filled=False,
                skipped=True,
                reason_code=f"PAPER_LEDGER_BLOCKED:{type(exc).__name__}",
                order_id=order.order_id,
                order_status=order.status_code,
            )

        order.filled_quantity = Decimal(str(order.order_quantity))
        order.remaining_quantity = Decimal("0")
        order.average_fill_price = fill_price
        order.filled_amount = (
            Decimal(str(order.filled_quantity)) * fill_price
        ).quantize(Decimal("0.00000001"))

        self._orders.change_status(
            entity=order,
            new_status=OrderStatus.FILLED,
            actor=actor,
            reason_code="PAPER_OUTBOX_AUTO_FILL",
            message=(
                f"paper_order_id={paper_order_id};"
                f"paper_trade_id={fill_result.trade_id}"
            ),
            commit=False,
        )

        metadata["paper_outbox_auto_fill"] = True
        metadata["paper_trade_id"] = fill_result.trade_id
        order.metadata_payload = metadata

        return PaperOutboxFillResult(
            filled=True,
            skipped=False,
            reason_code="FILLED",
            order_id=order.order_id,
            trade_id=fill_result.trade_id,
            paper_order_id=paper_order_id,
            order_status=OrderStatus.FILLED.value,
        )
