from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_DOWN

from sqlalchemy.orm import Session

from stock_platform.markets.repository import PriceDailyRepository
from stock_platform.markets.service import PriceDailyService
from stock_platform.trading.execution_service import (
    PaperExecutionService,
)
from stock_platform.trading.models import (
    OrderSide,
    OrderStatus,
    OrderType,
)
from stock_platform.trading.repository import (
    PaperOrderRepository,
)
from stock_platform.trading.simulation_models import (
    SimulatedFillResult,
    SimulationRequest,
)


ZERO = Decimal("0")
ONE = Decimal("1")


class PaperFillSimulationError(ValueError):
    """Raised when an order cannot be simulated."""


class DailyCloseFillSimulator:
    """
    지정 일자의 일봉 종가를 기준으로 미체결 모의 주문을 자동 체결한다.

    - MARKET: 종가 기준 체결
    - LIMIT BUY: 종가가 지정가 이하일 때 체결
    - LIMIT SELL: 종가가 지정가 이상일 때 체결
    - slippage_ratio로 매수/매도 체결가 보정
    - fill_ratio로 부분 체결 시뮬레이션
    """

    def __init__(self, session: Session) -> None:
        self._order_repository = PaperOrderRepository(session)
        self._price_service = PriceDailyService(
            PriceDailyRepository(session)
        )
        self._execution_service = PaperExecutionService(session)

    def simulate_order(
        self,
        *,
        order_id: int,
        request: SimulationRequest,
    ) -> SimulatedFillResult:
        self._validate_request(request)

        order = self._order_repository.get(order_id)
        if order is None:
            raise LookupError(
                f"Paper order not found: {order_id}"
            )

        allowed_statuses = {
            OrderStatus.CREATED.value,
            OrderStatus.ACCEPTED.value,
            OrderStatus.PARTIALLY_FILLED.value,
        }
        if order.status_code not in allowed_statuses:
            raise PaperFillSimulationError(
                f"Order cannot be filled in status "
                f"{order.status_code}"
            )

        if (
            order.exchange_code != request.exchange_code.upper()
            or order.symbol != request.symbol.upper()
        ):
            raise PaperFillSimulationError(
                "Order symbol does not match simulation request"
            )

        price = self._get_price(
            exchange_code=request.exchange_code,
            symbol=request.symbol,
            trade_date=request.trade_date,
        )

        reference_price = Decimal(price.close_price)

        if not self._is_limit_condition_met(
            side=OrderSide(order.side),
            order_type=OrderType(order.order_type),
            requested_price=(
                Decimal(order.requested_price)
                if order.requested_price is not None
                else None
            ),
            close_price=reference_price,
        ):
            raise PaperFillSimulationError(
                "Limit price condition was not met"
            )

        remaining_quantity = (
            Decimal(order.requested_quantity)
            - Decimal(order.filled_quantity)
        )

        fill_quantity = (
            remaining_quantity * request.fill_ratio
        ).quantize(
            Decimal("0.00000001"),
            rounding=ROUND_DOWN,
        )

        if fill_quantity <= ZERO:
            raise PaperFillSimulationError(
                "Calculated fill quantity is zero"
            )

        simulated_fill_price = (
            self._apply_slippage(
                side=OrderSide(order.side),
                price=reference_price,
                slippage_ratio=request.slippage_ratio,
            )
        )

        execution = self._execution_service.apply_fill(
            account_id=request.account_id,
            order_id=order_id,
            fill_quantity=fill_quantity,
            fill_price=simulated_fill_price,
        )

        return SimulatedFillResult(
            order_id=order_id,
            account_id=request.account_id,
            symbol=order.symbol,
            side=order.side,
            order_type=order.order_type,
            requested_quantity=Decimal(
                order.requested_quantity
            ),
            fill_quantity=fill_quantity,
            reference_price=reference_price,
            simulated_fill_price=simulated_fill_price,
            order_status=execution.order_status,
            trade_id=execution.trade_id,
        )

    def simulate_open_orders(
        self,
        *,
        request: SimulationRequest,
        limit: int = 100,
    ) -> list[SimulatedFillResult]:
        if limit <= 0:
            raise ValueError(
                "limit must be greater than zero"
            )

        orders = self._order_repository.list_recent(
            exchange_code=request.exchange_code,
            limit=limit,
        )

        results: list[SimulatedFillResult] = []

        for order in orders:
            if order.symbol != request.symbol.upper():
                continue
            if order.status_code not in {
                OrderStatus.CREATED.value,
                OrderStatus.ACCEPTED.value,
                OrderStatus.PARTIALLY_FILLED.value,
            }:
                continue

            try:
                results.append(
                    self.simulate_order(
                        order_id=order.order_id,
                        request=request,
                    )
                )
            except PaperFillSimulationError:
                continue

        return results

    def _get_price(
        self,
        *,
        exchange_code: str,
        symbol: str,
        trade_date: date,
    ):
        rows = self._price_service.get_between(
            exchange_code=exchange_code.upper(),
            symbol=symbol.upper(),
            start_date=trade_date,
            end_date=trade_date,
        )

        if not rows:
            raise LookupError(
                f"Daily price not found: "
                f"{exchange_code}/{symbol}/{trade_date}"
            )

        return rows[-1]

    @staticmethod
    def _is_limit_condition_met(
        *,
        side: OrderSide,
        order_type: OrderType,
        requested_price: Decimal | None,
        close_price: Decimal,
    ) -> bool:
        if order_type == OrderType.MARKET:
            return True

        if requested_price is None:
            return False

        if side == OrderSide.BUY:
            return close_price <= requested_price

        return close_price >= requested_price

    @staticmethod
    def _apply_slippage(
        *,
        side: OrderSide,
        price: Decimal,
        slippage_ratio: Decimal,
    ) -> Decimal:
        if side == OrderSide.BUY:
            adjusted = price * (
                ONE + slippage_ratio
            )
        else:
            adjusted = price * (
                ONE - slippage_ratio
            )

        return adjusted.quantize(
            Decimal("0.00000001")
        )

    @staticmethod
    def _validate_request(
        request: SimulationRequest,
    ) -> None:
        if request.account_id <= 0:
            raise ValueError(
                "account_id must be greater than zero"
            )
        if not request.exchange_code.strip():
            raise ValueError(
                "exchange_code is required"
            )
        if not request.symbol.strip():
            raise ValueError(
                "symbol is required"
            )
        if not ZERO <= request.slippage_ratio <= Decimal("0.20"):
            raise ValueError(
                "slippage_ratio must be between 0 and 0.20"
            )
        if not ZERO < request.fill_ratio <= ONE:
            raise ValueError(
                "fill_ratio must be between 0 and 1"
            )
