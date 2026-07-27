"""STEP 9-2 — Dry Run 단위 테스트 (실주문 없음)."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.broker.upbit.rules import UPBIT_MIN_NOTIONAL_KRW
from stock_platform.trading.step9_2_upbit_dry_run import (
    CallCounters,
    Step92UpbitDryRunService,
    analyze_fee_model,
    build_market_buy_body,
)


def test_fee_model_is_adapter_a_not_b() -> None:
    model = analyze_fee_model(requested_amount=Decimal("5000"))
    assert model["adapter_model"] == "A_ORDER_AMOUNT_FEE_SEPARATE"
    assert model["model_b_used"] is False
    assert model["broker_body_includes_fee"] is False
    assert Decimal(model["minimum_order_amount"]) == UPBIT_MIN_NOTIONAL_KRW
    assert Decimal(model["estimated_fee"]) == Decimal("2.5000")


def test_market_buy_transform_uses_ord_type_price() -> None:
    body = build_market_buy_body(
        market="KRW-BTC",
        amount_krw=Decimal("5000"),
        client_order_id="dryabcdefghijklmnop",
        uba_id=58,
        user_id=7,
    )
    assert body["broker_order_type"] == "price"
    assert body["requested_volume"] is None
    assert body["price"] == "5000"
    assert body["dry_run"] is True
    assert "volume" not in body["broker_body_sanitized"]


def test_allowlist_reject_in_service() -> None:
    session = MagicMock()
    uba = SimpleNamespace(
        user_id=7,
        is_active=True,
        live_order_enabled=False,
        live_armed=False,
        user_broker_account_id=58,
    )
    session.get.return_value = uba
    session.scalar.return_value = SimpleNamespace(trading_paused=False)

    svc = Step92UpbitDryRunService(session)
    with patch(
        "stock_platform.trading.step9_2_upbit_dry_run.get_settings"
    ) as gs:
        gs.return_value = SimpleNamespace(
            upbit_live_smoke_allowlist="KRW-BTC,KRW-ETH,KRW-XRP"
        )
        result = svc.run(uba_id=58, market="KRW-DOGE", amount=Decimal("5000"))
    assert result.verdict in {"BLOCKED_DEFECT", "ERROR"}
    codes = [g["code"] for g in result.guards if g["status"] == "FAIL"]
    assert "MARKET_ALLOWLIST" in codes


def test_min_notional_validate_raises() -> None:
    from stock_platform.broker.upbit.rules import validate_upbit_notional

    with pytest.raises(ValueError, match="minimum order amount"):
        validate_upbit_notional(
            side="BUY",
            order_type="MARKET",
            quantity=Decimal("0"),
            price=Decimal("1000"),
        )


def test_min_notional_guard_via_analyze() -> None:
    assert Decimal("1000") < UPBIT_MIN_NOTIONAL_KRW
    model = analyze_fee_model(requested_amount=Decimal("1000"))
    assert Decimal(model["minimum_order_amount"]) == UPBIT_MIN_NOTIONAL_KRW



def test_counters_start_zero() -> None:
    assert CallCounters().all_zero() is True


def test_mapper_does_not_call_broker() -> None:
    """변환만 수행 — create_order 경로 없음."""
    body = build_market_buy_body(
        market="KRW-BTC",
        amount_krw=Decimal("5000"),
        client_order_id="drytestclientorder01",
        uba_id=58,
        user_id=7,
    )
    assert body["broker_body_sanitized"]["ord_type"] == "price"
    assert body["broker_body_sanitized"]["side"] == "bid"
