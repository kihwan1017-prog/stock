from decimal import Decimal

import pytest

from stock_platform.broker.live_transition_service import (
    LiveTradingTransitionService,
)
from stock_platform.common.settings import get_settings


def _configure_live_ready_env(monkeypatch) -> None:
    monkeypatch.setenv("KIWOOM_USE_MOCK", "false")
    monkeypatch.setenv("KIWOOM_LIVE_ORDER_ENABLED", "true")
    monkeypatch.setenv("KIWOOM_ACCOUNT_NUMBER", "123456")
    monkeypatch.setenv("KIWOOM_APP_KEY", "key")
    monkeypatch.setenv("KIWOOM_SECRET_KEY", "secret")
    monkeypatch.setenv("KIWOOM_ORDER_WS_SUBSCRIBE_JSON", "{}")
    monkeypatch.setenv("KIWOOM_RECOVERY_START_TRADING", "false")
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_validate_blocks_large_order(monkeypatch) -> None:
    _configure_live_ready_env(monkeypatch)

    service = LiveTradingTransitionService.__new__(
        LiveTradingTransitionService
    )

    plan = service.validate(
        max_order_amount=Decimal("200000"),
        max_daily_loss=Decimal("100000"),
        paper_validation_approved=True,
    )

    assert plan.ready is False


def test_validate_passes_safe_initial_limits(monkeypatch) -> None:
    _configure_live_ready_env(monkeypatch)

    service = LiveTradingTransitionService.__new__(
        LiveTradingTransitionService
    )

    plan = service.validate(
        max_order_amount=Decimal("10000"),
        max_daily_loss=Decimal("50000"),
        paper_validation_approved=True,
    )

    assert plan.ready is True
