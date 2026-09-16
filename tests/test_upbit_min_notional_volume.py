"""Upbit KRW BUY 최소주문 notional 정밀도 보정 — focused tests."""

from __future__ import annotations

from decimal import Decimal

import pytest

from stock_platform.broker.upbit.rules import (
    UPBIT_MIN_NOTIONAL_KRW,
    round_upbit_volume,
    validate_upbit_notional,
    volume_from_krw_buy_amount,
)
from stock_platform.trading.controlled_live_order_smoke_service import (
    compute_upbit_order_preview,
)


def test_amount_5000_price_1445_notional_ge_5000() -> None:
    amount = Decimal("5000")
    price = Decimal("1445")
    qty = volume_from_krw_buy_amount(amount=amount, price=price)
    notional = qty * price
    assert notional >= amount
    assert notional >= UPBIT_MIN_NOTIONAL_KRW
    validate_upbit_notional(
        side="BUY",
        order_type="LIMIT",
        quantity=qty,
        price=price,
    )


def test_legacy_truncation_fails_but_helper_passes() -> None:
    amount = Decimal("5000")
    price = Decimal("1445")
    legacy = round_upbit_volume(amount / price)
    assert legacy == Decimal("3.46020761")
    assert legacy * price == Decimal("4999.99999645")
    with pytest.raises(ValueError, match="minimum order amount"):
        validate_upbit_notional(
            side="BUY",
            order_type="LIMIT",
            quantity=legacy,
            price=price,
        )
    fixed = volume_from_krw_buy_amount(amount=amount, price=price)
    assert fixed > legacy
    assert fixed * price >= amount
    validate_upbit_notional(
        side="BUY",
        order_type="LIMIT",
        quantity=fixed,
        price=price,
    )


def test_amount_below_min_stays_block() -> None:
    amount = Decimal("4999")
    price = Decimal("1445")
    qty = volume_from_krw_buy_amount(amount=amount, price=price)
    assert qty * price < UPBIT_MIN_NOTIONAL_KRW
    with pytest.raises(ValueError, match="minimum order amount"):
        validate_upbit_notional(
            side="BUY",
            order_type="LIMIT",
            quantity=qty,
            price=price,
        )


def test_amount_above_min_ok() -> None:
    amount = Decimal("7500")
    price = Decimal("1445")
    qty = volume_from_krw_buy_amount(amount=amount, price=price)
    assert qty * price >= amount
    validate_upbit_notional(
        side="BUY",
        order_type="LIMIT",
        quantity=qty,
        price=price,
    )


def test_correction_over_max_detected_by_caller() -> None:
    """보정 notional > max 이면 호출측이 BLOCK — helper는 Risk를 우회하지 않음."""

    amount = Decimal("5000")
    price = Decimal("1445")
    max_amount = Decimal("5000")
    qty = volume_from_krw_buy_amount(amount=amount, price=price)
    notional = qty * price
    assert notional >= amount
    # max=요청액 동일하면 보정 후 미세 초과 → Risk 우회 없이 BLOCK
    assert notional > max_amount


def test_preview_buy_matches_helper() -> None:
    preview = compute_upbit_order_preview(
        market="KRW-XRP",
        side="BUY",
        order_type="LIMIT",
        amount=Decimal("5000"),
        reference_price=Decimal("1445"),
        limit_price=Decimal("1445"),
    )
    qty = Decimal(str(preview["quantity"]))
    price = Decimal(str(preview["limit_price"]))
    helper_qty = volume_from_krw_buy_amount(
        amount=Decimal("5000"), price=price
    )
    assert qty == helper_qty
    assert qty * price >= Decimal("5000")
    validate_upbit_notional(
        side="BUY",
        order_type="LIMIT",
        quantity=qty,
        price=price,
    )


def test_sell_keeps_round_down() -> None:
    preview = compute_upbit_order_preview(
        market="KRW-XRP",
        side="SELL",
        order_type="LIMIT",
        amount=Decimal("5000"),
        reference_price=Decimal("1445"),
        limit_price=Decimal("1445"),
    )
    qty = Decimal(str(preview["quantity"]))
    price = Decimal(str(preview["limit_price"]))
    legacy = round_upbit_volume(Decimal("5000") / price)
    assert qty == legacy
    assert preview["quantity_note"] == "volume_equals_amount_div_limit_price"


def test_paper_adapter_untouched() -> None:
    """Paper 경로 import만 확인 — Upbit helper와 무관."""

    from stock_platform.broker.paper.adapter import PaperBrokerAdapter

    assert PaperBrokerAdapter is not None
