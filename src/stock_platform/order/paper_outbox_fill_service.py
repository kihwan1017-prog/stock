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
        from sqlalchemy import select

        from stock_platform.order.entities import TradingOrderEntity

        # 경합 시 동일 주문 이중 Fill 방지 — row lock
        order = self._session.scalar(
            select(TradingOrderEntity)
            .where(TradingOrderEntity.order_id == int(order_id))
            .with_for_update()
        )
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

        side = OrderSide(str(order.side_code).upper())
        # SELL: 포지션 없으면 재시도 무의미 — CANCEL 로 ACCEPTED 고착 해소
        if side == OrderSide.SELL:
            from sqlalchemy import select

            from stock_platform.trading.account_models import PaperPosition

            held = self._session.scalar(
                select(PaperPosition.quantity).where(
                    PaperPosition.account_id == int(order.account_id),
                    PaperPosition.symbol == str(order.symbol).upper(),
                    PaperPosition.quantity > 0,
                )
            )
            held_qty = Decimal(str(held or 0))
            if held_qty <= 0:
                # ACCEPTED → CANCELLED 직접 전이 불가: CANCEL_REQUESTED 경유
                self._orders.change_status(
                    entity=order,
                    new_status=OrderStatus.CANCEL_REQUESTED,
                    actor=actor,
                    reason_code="PAPER_NO_POSITION_TO_FILL",
                    message="SELL ACCEPTED without position — cancelling",
                    commit=False,
                )
                self._orders.change_status(
                    entity=order,
                    new_status=OrderStatus.CANCELLED,
                    actor=actor,
                    reason_code="PAPER_NO_POSITION_TO_FILL",
                    message="SELL ACCEPTED without position — cancelled",
                    commit=False,
                )
                # PaperOrder가 ACCEPTED면 cancel로 terminal 처리 (고착 방지)
                if existing_paper_id is not None:
                    paper_entity = self._paper_orders._repository.get(
                        int(existing_paper_id)
                    )
                    if paper_entity is not None:
                        paper_status = str(
                            getattr(paper_entity, "status_code", "")
                            or getattr(paper_entity, "status", "")
                            or ""
                        ).upper()
                        if paper_status in {
                            OrderStatus.ACCEPTED.value,
                            "PARTIALLY_FILLED",
                        }:
                            self._paper_orders.cancel(
                                order_id=int(existing_paper_id)
                            )
                metadata["paper_auto_fill_last_error"] = "NO_POSITION_CANCELLED"
                order.metadata_payload = metadata
                return PaperOutboxFillResult(
                    filled=False,
                    skipped=True,
                    reason_code="NO_POSITION_CANCELLED",
                    order_id=order.order_id,
                    order_status=OrderStatus.CANCELLED.value,
                )
            if remaining > held_qty:
                remaining = held_qty

        try:
            if existing_paper_id is not None:
                paper_order_id = int(existing_paper_id)
                # PaperOrder가 이미 FILLED면 TradingOrder만 동기화 (이중 원장 금지)
                existing_paper = self._paper_orders._repository.get(
                    paper_order_id
                )
                if (
                    existing_paper is not None
                    and str(
                        getattr(existing_paper, "status_code", "")
                        or getattr(existing_paper, "status", "")
                        or ""
                    ).upper()
                    == "FILLED"
                ):
                    order.filled_quantity = Decimal(str(order.order_quantity))
                    order.remaining_quantity = Decimal("0")
                    if order.average_fill_price is None:
                        order.average_fill_price = fill_price
                    self._orders.change_status(
                        entity=order,
                        new_status=OrderStatus.FILLED,
                        actor=actor,
                        reason_code="PAPER_OUTBOX_IDEMPOTENT_REPLAY",
                        message=f"paper_order_id={paper_order_id}",
                        commit=False,
                    )
                    metadata["paper_outbox_auto_fill"] = True
                    order.metadata_payload = metadata
                    return PaperOutboxFillResult(
                        filled=True,
                        skipped=False,
                        reason_code="IDEMPOTENT_REPLAY",
                        order_id=order.order_id,
                        paper_order_id=paper_order_id,
                        order_status=OrderStatus.FILLED.value,
                    )
            else:
                paper_order = self._paper_orders.create(
                    account_id=int(order.account_id),
                    exchange_code=str(order.exchange_code),
                    symbol=str(order.symbol),
                    side=side,
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
                reason_code=(
                    f"PAPER_LEDGER_BLOCKED:{type(exc).__name__}:"
                    f"{str(exc)[:120]}"
                ),
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
        metadata.pop("paper_auto_fill_last_error", None)
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
