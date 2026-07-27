"""STEP 8-5-20 — v1.0 RC validation smoke tests."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from stock_platform.common.settings import get_settings
from stock_platform.operation.live_health_gate import (
    LiveHealthBlockedError,
    assert_live_orders_allowed,
    evaluate_live_order_health,
)
from tests.migration_helpers import (
    alembic_current_head,
    assert_revision_exists,
)


def test_step8_5_20_revision_head() -> None:
    assert_revision_exists("g0a1b2c3d4e5")
    assert_revision_exists("h1b2c3d4e5f6")
    head = alembic_current_head()
    assert_revision_exists(head)
    # 8-5-21에서 head 전진 — h1 체인 존재만 고정 검증


def test_live_safety_defaults() -> None:
    settings = get_settings()
    assert settings.kiwoom_use_mock is True or settings.kiwoom_live_order_enabled is False
    assert settings.kiwoom_live_order_enabled is False
    assert settings.upbit_live_order_enabled is False
    assert settings.global_live_order_enabled is False


def test_pending_order_entity_has_uba() -> None:
    from stock_platform.broker.pending_entities import BrokerPendingOrderEntity

    cols = {c.name for c in BrokerPendingOrderEntity.__table__.columns}
    assert "user_broker_account_id" in cols
    assert "masked_account_ref" in cols


def test_pending_repo_rejects_account_number_only() -> None:
    from stock_platform.broker.pending_repository import (
        BrokerPendingOrderRepository,
    )
    from stock_platform.trading.account_identity import AccountIdentityError

    repo = BrokerPendingOrderRepository(MagicMock())
    with pytest.raises(AccountIdentityError):
        repo.list_for_account("KIWOOM", "123")
    with pytest.raises(AccountIdentityError):
        repo.replace_for_account("KIWOOM", "123", [])


def test_live_health_gate_allows_when_clean(monkeypatch) -> None:
    session = MagicMock()
    # scalar returns 0 for both counts
    session.scalar.return_value = 0
    result = evaluate_live_order_health(session)
    assert result["status"] == "HEALTHY"
    assert result["live_orders_allowed"] is True
    assert_live_orders_allowed(session)


def test_live_health_gate_blocks_on_missing_uba(monkeypatch) -> None:
    session = MagicMock()
    # evaluate 2회(assert 재호출) × scalar 2회 = 4
    session.scalar.side_effect = [1, 0, 1, 0]
    result = evaluate_live_order_health(session)
    assert result["status"] == "CRITICAL"
    assert result["live_orders_allowed"] is False
    with pytest.raises(LiveHealthBlockedError):
        assert_live_orders_allowed(session)
