"""Daily entry quota semantics — consumed/reserved vs zero-fill cancel."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from stock_platform.operation.upbit_full_market.portfolio_daily_entry_count import (
    order_counts_toward_daily_quota,
)
from stock_platform.order.models import OrderStatus


def _order(**kwargs) -> SimpleNamespace:
    base = {
        "side_code": "BUY",
        "broker_code": "UPBIT",
        "filled_quantity": Decimal("0"),
        "status_code": OrderStatus.ACCEPTED.value,
        "execution_mode": "LIVE",
        "metadata_payload": {"order_source": "AUTO", "environment": "LIVE"},
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_filled_buy_counts() -> None:
    o = _order(
        status_code=OrderStatus.FILLED.value,
        filled_quantity=Decimal("5"),
    )
    assert order_counts_toward_daily_quota(o) is True


def test_partial_buy_counts() -> None:
    o = _order(
        status_code=OrderStatus.PARTIALLY_FILLED.value,
        filled_quantity=Decimal("1.5"),
    )
    assert order_counts_toward_daily_quota(o) is True


def test_cancelled_zero_fill_not_counted() -> None:
    """#1896 케이스 — 0-fill CANCELLED는 quota 미소비."""

    o = _order(
        order_id=1896,
        status_code=OrderStatus.CANCELLED.value,
        filled_quantity=Decimal("0"),
    )
    assert order_counts_toward_daily_quota(o) is False


def test_accepted_open_reserved_counts() -> None:
    o = _order(status_code=OrderStatus.ACCEPTED.value)
    assert order_counts_toward_daily_quota(o) is True


def test_manual_not_counted() -> None:
    o = _order(metadata_payload={"order_source": "MANUAL", "environment": "LIVE"})
    assert order_counts_toward_daily_quota(o) is False


def test_sell_not_counted() -> None:
    o = _order(side_code="SELL")
    assert order_counts_toward_daily_quota(o) is False


def test_cancelled_after_partial_still_counts() -> None:
    o = _order(
        status_code=OrderStatus.CANCELLED.value,
        filled_quantity=Decimal("2"),
    )
    assert order_counts_toward_daily_quota(o) is True


def test_order1896_semantics_documentation() -> None:
    """BEFORE: all AUTO BUY created counted. AFTER: 1896 excluded."""

    order1896 = _order(
        order_id=1896,
        status_code=OrderStatus.CANCELLED.value,
        filled_quantity=Decimal("0"),
        metadata_payload={
            "order_source": "AUTO",
            "environment": "LIVE",
            "signal_reason": "PORTFOLIO_BULLISH_STATE_ENTRY",
        },
    )
    assert order_counts_toward_daily_quota(order1896) is False
    assert order1896.order_id == 1896
