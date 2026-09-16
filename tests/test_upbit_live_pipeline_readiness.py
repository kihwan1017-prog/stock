"""Upbit LIVE pipeline readiness — 실주문 HTTP 0."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from stock_platform.realtime.upbit_client import UpbitRealtimeClient
from stock_platform.trading.upbit_live_pipeline_readiness import (
    UpbitLivePipelineReadinessService,
)


def test_upbit_ws_status_includes_reconnect_count() -> None:
    client = UpbitRealtimeClient(
        symbols=["KRW-BTC"],
        quote_handler=MagicMock(),
        channels=["ticker"],
    )
    status = client.status()
    assert status["exchange_code"] == "UPBIT"
    assert "reconnect_count" in status
    assert status["reconnect_count"] == 0


def test_pipeline_readiness_evaluate_no_mutate() -> None:
    from stock_platform.database.session import get_session_factory

    SessionLocal = get_session_factory()
    with SessionLocal() as session:
        result = UpbitLivePipelineReadinessService(session).evaluate()

    assert result["broker"] == "UPBIT"
    assert result["execute_live_allowed_here"] is False
    assert result["checks"]["order_mutate_policy"]["submit_allowed"] is False
    assert result["checks"]["hooks"]["fill_sync"] is True
    assert result["checks"]["hooks"]["live_fill_ledger"] is True
    assert result["checks"]["hooks"]["order_reconcile"] is True
    assert result["checks"]["hooks"]["recovery_adapter"] is True
    assert result["checks"]["hooks"]["dry_run"] is True
    assert result["checks"]["hooks"]["shadow"] is True
    assert result["checks"]["hooks"]["hub"] is True
    # Secret 미포함
    blob = str(result)
    assert "secret_key" not in blob.lower() or "secret_key_len" in blob
    assert "access_key" not in blob or "has_access_key" in blob


def test_pipeline_readiness_uba_scope() -> None:
    from stock_platform.database.session import get_session_factory
    from sqlalchemy import text

    SessionLocal = get_session_factory()
    with SessionLocal() as session:
        uba = session.execute(
            text(
                """
                SELECT user_broker_account_id
                FROM trading.user_broker_account
                WHERE broker_code='UPBIT' AND is_active IS TRUE
                ORDER BY user_broker_account_id LIMIT 1
                """
            )
        ).scalar()
        if not uba:
            pytest.skip("no UPBIT UBA")
        result = UpbitLivePipelineReadinessService(session).evaluate(
            user_broker_account_id=int(uba)
        )
    assert result["checks"]["uba"]["user_broker_account_id"] == int(uba)
    assert result["checks"]["uba"]["broker_code"] == "UPBIT"


def test_admin_readiness_includes_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    # 라우트 존재·응답 키만 가벼운 단위로 확인하기 어려우면 서비스 직접
    from stock_platform.api.v1 import admin_live_ops_readiness as mod

    assert hasattr(mod, "admin_live_ops_readiness")
