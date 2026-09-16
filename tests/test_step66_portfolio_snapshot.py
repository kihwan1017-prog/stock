"""STEP66 — MDD·기간·API 계약 테스트."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient

from stock_platform.api.main import app
from stock_platform.api.router import collect_duplicate_operation_ids
from stock_platform.trading.portfolio_snapshot_service import (
    compute_max_drawdown,
    compute_period_return,
    resolve_period_range,
)


def test_compute_max_drawdown() -> None:
    series = [
        Decimal("100"),
        Decimal("120"),
        Decimal("90"),
        Decimal("95"),
        Decimal("110"),
    ]
    # peak 120 → 90 = 25%
    mdd = compute_max_drawdown(series)
    assert mdd == Decimal("0.250000")


def test_compute_max_drawdown_empty() -> None:
    assert compute_max_drawdown([]) == Decimal("0")


def test_compute_period_return() -> None:
    assert compute_period_return(
        Decimal("100"), Decimal("110")
    ) == Decimal("10.0000")
    assert compute_period_return(Decimal("0"), Decimal("10")) == Decimal(
        "0"
    )


def test_resolve_period_range() -> None:
    today = date(2026, 7, 20)
    start, end = resolve_period_range("7d", today=today)
    assert end == today
    assert start == today - timedelta(days=6)
    start_all, end_all = resolve_period_range("all", today=today)
    assert start_all is None
    assert end_all == today


def test_portfolio_openapi_registered() -> None:
    paths = set(app.openapi()["paths"].keys())
    assert "/api/v1/user/portfolio/history" in paths
    assert "/api/v1/user/portfolio/summary" in paths
    assert "/api/v1/user/portfolio/snapshot" in paths
    assert collect_duplicate_operation_ids(app.router) == []


def test_portfolio_apis_require_auth() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    assert (
        client.get(
            "/api/v1/user/portfolio/history",
            params={"account_id": 1},
        ).status_code
        == 401
    )
    assert (
        client.get(
            "/api/v1/user/portfolio/summary",
            params={"account_id": 1},
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/user/portfolio/snapshot",
            json={"account_id": 1},
        ).status_code
        == 401
    )


def test_portfolio_equity_snapshot_job_registered() -> None:
    from unittest.mock import MagicMock

    from stock_platform.scheduler.factory import build_job_registry

    session = MagicMock()
    registry = build_job_registry(session)
    names = {job.name for job in registry.list_jobs()}
    assert "portfolio_equity_snapshot" in names
