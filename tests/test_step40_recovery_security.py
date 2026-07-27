"""STEP40 장애 복구·보안 가드 검증."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

from stock_platform.broker.factory import BrokerAdapterFactory
from stock_platform.broker.models import BrokerEnvironment
from stock_platform.order.models import OrderStatus
from stock_platform.order.timeout_service import OrderTimeoutService
from stock_platform.trading.execution_sync_service import (
    ExecutionSyncService,
)


def test_duplicate_execution_is_idempotent() -> None:
    service = ExecutionSyncService.__new__(ExecutionSyncService)
    executions = MagicMock()
    executions.exists.return_value = True
    service._executions = executions
    service._orders = MagicMock()
    service._session = MagicMock()

    from stock_platform.broker.kiwoom.execution_models import (
        KiwoomExecutionEvent,
    )

    result = service.synchronize(
        KiwoomExecutionEvent(
            broker_order_id="B1",
            broker_execution_id="DUP",
            symbol="005930",
            side_code="BUY",
            execution_price=Decimal("1"),
            execution_quantity=Decimal("1"),
            remaining_quantity=Decimal("0"),
            executed_at=datetime.now(timezone.utc),
            raw_payload={},
        )
    )
    assert result.duplicate is True


def test_order_timeout_marks_stale_pending() -> None:
    service = OrderTimeoutService.__new__(OrderTimeoutService)
    entity = SimpleNamespace(
        order_id=1,
        status_code=OrderStatus.PENDING.value,
    )
    repo = MagicMock()
    repo.list_stale_open_orders.return_value = [entity]

    def change_status(*, entity, new_status, **kwargs):
        entity.status_code = new_status.value
        return entity

    repo.change_status.side_effect = change_status
    service._repository = repo
    service._session = MagicMock()

    summary = service.fail_stale_orders(timeout_seconds=60)
    assert summary.timed_out == 1
    assert entity.status_code == OrderStatus.FAILED.value


def test_live_trading_blocked_by_default(monkeypatch) -> None:
    monkeypatch.setenv("KIWOOM_LIVE_ORDER_ENABLED", "false")
    from stock_platform.common.settings import get_settings

    get_settings.cache_clear()
    try:
        try:
            BrokerAdapterFactory.create(
                BrokerEnvironment.LIVE,
                "KIWOOM",
                session=object(),
            )
            blocked = False
        except PermissionError:
            blocked = True
        assert blocked is True
    finally:
        get_settings.cache_clear()


def test_security_defaults(monkeypatch) -> None:
    """단위 테스트는 머신 secrets 와 무관하게 안전 기본값을 보장한다."""

    from stock_platform.common.settings import (
        Settings,
        clear_settings_cache,
        get_settings,
    )

    monkeypatch.setenv("KIWOOM_LIVE_ORDER_ENABLED", "false")
    monkeypatch.setenv("KIWOOM_USE_MOCK", "true")
    monkeypatch.setenv("UPBIT_LIVE_ORDER_ENABLED", "false")
    monkeypatch.setenv("GLOBAL_LIVE_ORDER_ENABLED", "false")
    clear_settings_cache()

    # get_settings 경로 (환경변수 오버라이드)
    settings = get_settings()
    assert settings.kiwoom_live_order_enabled is False
    assert settings.kiwoom_use_mock is True
    assert settings.upbit_live_order_enabled is False
    assert settings.global_live_order_enabled is False

    # 파일 없는 순수 생성 경로
    isolated = Settings(
        _env_file=None,
        db_host="localhost",
        db_name="stock_platform",
        db_user="stock_app",
        db_password="test",
    )
    assert isolated.kiwoom_live_order_enabled is False
    assert isolated.kiwoom_use_mock is True
