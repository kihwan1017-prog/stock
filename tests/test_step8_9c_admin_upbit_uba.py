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
    assert UPBIT_LIVE_RECOMMENDED_MAX_ORDER_AMOUNT == Decimal("5000")
    assert UPBIT_LIVE_RECOMMENDED_MAX_OPEN_ORDERS == 1
    assert UPBIT_LIVE_RECOMMENDED_DAILY_ORDER_LIMIT == 1


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
