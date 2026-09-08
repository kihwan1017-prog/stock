"""AUTO ENTRY sizing — effective Risk SoT (하드코딩 금액 금지).

RealtimeExecutionConfig.order_amount 는 nominal budget 일 뿐이며
effective max_order_amount / max_order_quantity 로 clamp 한다.
Risk Guard reject 에만 의존하지 않는다.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from stock_platform.operation.upbit_full_market.portfolio_entry_sizing import (
    effective_max_order_cap,
    resolve_portfolio_entry_risk_limits,
)
from stock_platform.position.lot_rounding import round_share_quantity
from stock_platform.risk_engine.resolved_policy import ResolvedRiskPolicyResolver

ZERO = Decimal("0")


def resolve_risk_aware_entry_size(
    session: Session,
    *,
    user_broker_account_id: int | None,
    user_id: int | None,
    signal_price: Decimal,
    nominal_order_amount: Decimal,
    exchange_code: str,
    activation_max_order_amount: Decimal | None = None,
) -> dict[str, Any]:
    """nominal budget → risk-compliant qty/amount.

    Returns:
      ok, quantity, order_amount, max_order_amount, max_order_quantity,
      effective_budget, skip_reason, source_layers
    """

    price = Decimal(str(signal_price or 0))
    nominal = Decimal(str(nominal_order_amount or 0))
    if price <= ZERO:
        return {
            "ok": False,
            "skip_reason": "INVALID_SIGNAL_PRICE",
            "quantity": ZERO,
            "order_amount": ZERO,
        }
    if nominal <= ZERO:
        return {
            "ok": False,
            "skip_reason": "INVALID_NOMINAL_ORDER_AMOUNT",
            "quantity": ZERO,
            "order_amount": ZERO,
        }

    max_amount = nominal
    max_qty: Decimal | None = None
    source_layers: list[str] = ["nominal_config"]

    if user_broker_account_id is not None:
        limits = resolve_portfolio_entry_risk_limits(
            session,
            user_broker_account_id=int(user_broker_account_id),
            user_id=user_id,
        )
        max_amount = effective_max_order_cap(
            limits,
            activation_max_order_amount=activation_max_order_amount,
            legacy_explicit_cap=nominal,
        )
        source_layers = list(limits.source_layers) + ["nominal_config"]
        resolved = ResolvedRiskPolicyResolver(session).resolve(
            user_id=user_id,
            user_broker_account_id=int(user_broker_account_id),
        )
        max_qty = Decimal(str(resolved.max_order_quantity))
    elif activation_max_order_amount is not None and activation_max_order_amount > ZERO:
        max_amount = min(nominal, Decimal(str(activation_max_order_amount)))

    budget = min(nominal, max_amount)
    if budget <= ZERO:
        return {
            "ok": False,
            "skip_reason": "EFFECTIVE_BUDGET_ZERO",
            "quantity": ZERO,
            "order_amount": ZERO,
            "max_order_amount": max_amount,
            "max_order_quantity": max_qty,
            "effective_budget": budget,
            "source_layers": source_layers,
        }

    raw_qty = budget / price
    quantity = round_share_quantity(
        raw_qty,
        exchange_code=str(exchange_code or "KRX"),
    )
    if max_qty is not None and max_qty > ZERO:
        quantity = min(quantity, max_qty.to_integral_value())

    if quantity <= ZERO:
        return {
            "ok": False,
            "skip_reason": "ORDER_AMOUNT_BELOW_EXECUTABLE",
            "quantity": ZERO,
            "order_amount": ZERO,
            "max_order_amount": max_amount,
            "max_order_quantity": max_qty,
            "effective_budget": budget,
            "nominal_order_amount": nominal,
            "source_layers": source_layers,
        }

    order_amount = (quantity * price).quantize(Decimal("0.00000001"))
    # 최종 notional 도 amount cap 준수 (가격 변동/반올림 방어)
    if order_amount > max_amount:
        # qty 를 한 단계 더 줄여 cap 맞춤
        while quantity > ZERO and (quantity * price) > max_amount:
            quantity -= Decimal("1") if str(exchange_code or "").upper() not in {
                "UPBIT",
                "CRYPTO",
            } else Decimal("0.00000001")
            quantity = round_share_quantity(
                quantity, exchange_code=str(exchange_code or "KRX")
            )
        if quantity <= ZERO:
            return {
                "ok": False,
                "skip_reason": "ORDER_AMOUNT_BELOW_EXECUTABLE",
                "quantity": ZERO,
                "order_amount": ZERO,
                "max_order_amount": max_amount,
                "max_order_quantity": max_qty,
                "effective_budget": budget,
                "nominal_order_amount": nominal,
                "source_layers": source_layers,
            }
        order_amount = (quantity * price).quantize(Decimal("0.00000001"))

    return {
        "ok": True,
        "quantity": quantity,
        "order_amount": order_amount,
        "max_order_amount": max_amount,
        "max_order_quantity": max_qty,
        "effective_budget": budget,
        "nominal_order_amount": nominal,
        "source_layers": source_layers,
        "risk_reject_dependency": False,
    }


__all__ = ["resolve_risk_aware_entry_size"]
