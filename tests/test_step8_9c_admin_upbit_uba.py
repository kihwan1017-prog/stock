"""STEP 8-9C — Admin UBA / recommended risk / readiness OpenAPI 계약."""

from __future__ import annotations

from decimal import Decimal

from fastapi.testclient import TestClient

from stock_platform.api.main import app
from stock_platform.api.router import collect_duplicate_operation_ids
from stock_platform.trading.upbit_live_ops_constants import (
    UPBIT_LIVE_RECOMMENDED_DAILY_ORDER_LIMIT,
    UPBIT_LIVE_RECOMMENDED_MAX_OPEN_ORDERS,
    UPBIT_LIVE_RECOMMENDED_MAX_ORDER_AMOUNT,
    upbit_live_recommended_risk_payload,
)


def test_recommended_risk_constants() -> None:
    payload = upbit_live_recommended_risk_payload()
    assert payload["max_order_amount"] == Decimal("5000")
    assert payload["max_open_orders"] == 1
    assert payload["daily_order_limit"] == 1
    assert payload["max_investment_ratio"] == Decimal("1.0")
    assert payload["daily_max_loss_amount"] == Decimal("10000000")
    assert payload["max_position_amount"] == Decimal("10000000")
    assert payload["max_position_weight"] == Decimal("1.0")
    assert payload["max_total_investment_amount"] == Decimal("10000000")
    assert UPBIT_LIVE_RECOMMENDED_MAX_ORDER_AMOUNT == Decimal("5000")
    assert UPBIT_LIVE_RECOMMENDED_MAX_OPEN_ORDERS == 1
    assert UPBIT_LIVE_RECOMMENDED_DAILY_ORDER_LIMIT == 1


def test_to_engine_policy_uses_resolved_investment_ratio() -> None:
    from stock_platform.risk_engine.resolved_policy import ResolvedRiskPolicy

    resolved = ResolvedRiskPolicy(
        max_order_amount=Decimal("5000"),
        daily_max_order_amount=Decimal("1000000"),
        max_total_investment_amount=Decimal("10000000"),
        max_position_amount=Decimal("10000000"),
        max_position_count=20,
        max_position_weight=Decimal("1.0"),
        max_investment_ratio=Decimal("1.0"),
        allow_duplicate_buy=True,
        daily_max_loss_amount=Decimal("10000000"),
        daily_max_loss_rate=Decimal("0.05"),
        stop_loss_rate=Decimal("0.05"),
        take_profit_rate=Decimal("0.10"),
        trailing_stop_rate=Decimal("0.03"),
        auto_trading_enabled=True,
        buy_enabled=True,
        sell_enabled=True,
        sell_only=False,
        account_paused=False,
        max_order_quantity=Decimal("100"),
        daily_order_limit=1,
        duplicate_order_window_seconds=5,
        max_open_orders=1,
        max_slippage_rate=Decimal("0.01"),
        anomaly_orders_per_minute=10,
        loop_detect_window_seconds=60,
        arm_ttl_seconds=300,
        source_layers=("system", "account"),
    )
    engine = resolved.to_engine_policy()
    assert engine.max_investment_ratio == Decimal("1.0")
    assert engine.max_daily_loss == Decimal("10000000")
    assert engine.max_position_amount == Decimal("10000000")


def test_admin_broker_accounts_openapi_registered() -> None:
    paths = set(app.openapi()["paths"].keys())
    assert "/api/v1/admin/broker-accounts" in paths
    assert "/api/v1/admin/broker-accounts/{uba_id}" in paths
    assert (
        "/api/v1/admin/broker-accounts/{uba_id}/apply-recommended-risk"
        in paths
    )
    assert "/api/v1/admin/live-ops/readiness" in paths
    assert "/api/v1/admin/accounts/{uba_id}/credentials" in paths
    assert collect_duplicate_operation_ids(app.router) == []


def test_admin_broker_accounts_require_auth() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/api/v1/admin/broker-accounts").status_code == 401
    assert (
        client.post(
            "/api/v1/admin/broker-accounts",
            json={
                "owner_user_id": 1,
                "broker_code": "UPBIT",
                "account_number": "MAIN",
            },
        ).status_code
        == 401
    )
    assert client.get("/api/v1/admin/live-ops/readiness").status_code == 401
    assert (
        client.post(
            "/api/v1/admin/accounts/1/credentials",
            json={"access_key": "a", "secret_key": "b"},
        ).status_code
        == 401
    )


def test_admin_credential_upsert_openapi_methods() -> None:
    spec = app.openapi()["paths"]["/api/v1/admin/accounts/{uba_id}/credentials"]
    assert "post" in spec
    assert "put" in spec
