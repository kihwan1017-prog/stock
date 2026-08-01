"""P0-5 / P0-2 / P0-3 unit tests (non-live)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from stock_platform.broker.kiwoom.ws_execution_bridge import (
    order_execution_event_to_kiwoom_execution,
)
from stock_platform.broker.kiwoom.ws_models import (
    KiwoomOrderEventType,
    KiwoomOrderExecutionEvent,
)
from stock_platform.order.paper_outbox_fill_service import (
    PaperOutboxFillService,
)
from stock_platform.strategy_deployment.default_registry import (
    configure_default_strategy_registry,
)
from stock_platform.strategy_deployment.registry import (
    strategy_factory_registry,
)
from stock_platform.strategy_deployment.runtime_start_service import (
    RuntimeStartError,
    promote_deployment_to_active,
)


def test_ws_bridge_ignores_accepted() -> None:
    event = KiwoomOrderExecutionEvent(
        account_number="1",
        broker_order_id="B1",
        original_order_id=None,
        exchange_code="KRX",
        symbol="005930",
        side="BUY",
        event_type=KiwoomOrderEventType.ACCEPTED,
        order_quantity=Decimal("10"),
        filled_quantity=Decimal("0"),
        remaining_quantity=Decimal("10"),
        fill_price=None,
        average_fill_price=None,
        event_time=datetime.now(timezone.utc),
        received_at=datetime.now(timezone.utc),
        raw_data={},
    )
    assert order_execution_event_to_kiwoom_execution(event) is None


def test_ws_bridge_maps_partial_fill_delta() -> None:
    event = KiwoomOrderExecutionEvent(
        account_number="1",
        broker_order_id="B1",
        original_order_id=None,
        exchange_code="KRX",
        symbol="005930",
        side="BUY",
        event_type=KiwoomOrderEventType.PARTIALLY_FILLED,
        order_quantity=Decimal("10"),
        filled_quantity=Decimal("4"),
        remaining_quantity=Decimal("6"),
        fill_price=Decimal("70000"),
        average_fill_price=Decimal("70000"),
        event_time=datetime.now(timezone.utc),
        received_at=datetime.now(timezone.utc),
        raw_data={},
    )
    mapped = order_execution_event_to_kiwoom_execution(
        event, previous_filled_quantity=Decimal("1")
    )
    assert mapped is not None
    assert mapped.execution_quantity == Decimal("3")
    assert mapped.broker_order_id == "B1"


def test_paper_outbox_fill_blocks_live() -> None:
    session = MagicMock()
    order = SimpleNamespace(
        order_id=1,
        status_code="ACCEPTED",
        user_broker_account_id=None,
        metadata_payload={"environment": "LIVE"},
        remaining_quantity=Decimal("1"),
        order_quantity=Decimal("1"),
        filled_quantity=Decimal("0"),
        order_price=Decimal("100"),
        account_id=1,
        exchange_code="KRX",
        symbol="005930",
        side_code="BUY",
        order_type_code="LIMIT",
    )
    session.scalar.return_value = order
    svc = PaperOutboxFillService.__new__(PaperOutboxFillService)
    svc._session = session
    svc._orders = SimpleNamespace(get=lambda oid: order)
    svc._paper_orders = SimpleNamespace()
    svc._paper_exec = SimpleNamespace()

    result = svc.fill_accepted_order(1)
    assert result.skipped is True
    assert result.reason_code == "LIVE_ENVIRONMENT_BLOCKED"


def test_live_fill_ledger_buy() -> None:
    from stock_platform.broker.live_fill_ledger_service import (
        LiveFillLedgerService,
    )
    from stock_platform.broker.kiwoom.execution_models import (
        KiwoomExecutionEvent,
    )

    session = MagicMock()
    session.scalar.return_value = None
    order = SimpleNamespace(
        order_id=10,
        user_broker_account_id=7,
        broker_code="KIWOOM",
        exchange_code="KRX",
        symbol="005930",
        side_code="BUY",
    )
    event = KiwoomExecutionEvent(
        broker_order_id="B1",
        broker_execution_id="E1",
        symbol="005930",
        side_code="BUY",
        execution_price=Decimal("70000"),
        execution_quantity=Decimal("2"),
        remaining_quantity=Decimal("0"),
        executed_at=datetime.now(timezone.utc),
        raw_payload={},
    )
    result = LiveFillLedgerService(session).apply_execution(
        order=order, event=event
    )
    assert result["applied"] is True
    assert session.add.called


def test_auto_start_master_off(monkeypatch) -> None:
    import asyncio
    from stock_platform.realtime import execution_auto_start as mod

    monkeypatch.setattr(
        mod,
        "get_settings",
        lambda: SimpleNamespace(
            realtime_execution_auto_start_enabled=False,
            realtime_paper_auto_start_enabled=True,
            realtime_live_auto_start_enabled=False,
        ),
    )
    result = asyncio.run(mod.maybe_auto_start_runners(source="TEST"))
    assert result["skipped_reason"] == "MASTER_FLAG_OFF"


def test_paper_outbox_fill_blocks_uba() -> None:
    session = MagicMock()
    order = SimpleNamespace(
        order_id=2,
        status_code="ACCEPTED",
        user_broker_account_id=99,
        metadata_payload={"environment": "PAPER"},
        remaining_quantity=Decimal("1"),
        order_quantity=Decimal("1"),
        filled_quantity=Decimal("0"),
        order_price=Decimal("100"),
        account_id=1,
        exchange_code="KRX",
        symbol="005930",
        side_code="BUY",
        order_type_code="LIMIT",
    )
    session.scalar.return_value = order
    svc = PaperOutboxFillService.__new__(PaperOutboxFillService)
    svc._session = session
    svc._orders = SimpleNamespace(get=lambda oid: order)
    svc._paper_orders = SimpleNamespace()
    svc._paper_exec = SimpleNamespace()

    result = svc.fill_accepted_order(2)
    assert result.skipped is True
    assert result.reason_code == "USER_BROKER_ACCOUNT_BLOCKED"


def test_default_registry_fallback_create() -> None:
    configure_default_strategy_registry()
    strategy = strategy_factory_registry.create(
        strategy_code="UNKNOWN_CODE_XYZ",
        parameter_payload={"a": 1},
    )
    assert getattr(strategy, "parameter_payload")["a"] == 1


def test_promote_requires_confirmation() -> None:
    session = MagicMock()
    with pytest.raises(RuntimeStartError) as exc:
        promote_deployment_to_active(
            session,
            strategy_deployment_id=1,
            actor="admin:1",
            confirmation_text="please go",
        )
    assert exc.value.code == "CONFIRMATION_REQUIRED"


def test_promote_rejects_non_startable_status() -> None:
    session = MagicMock()
    deployment = SimpleNamespace(
        strategy_deployment_id=1,
        status_code="PENDING",
        strategy_id=10,
        mode_code="PAPER",
        activated_at=None,
        error_message=None,
    )
    session.get.return_value = deployment
    with pytest.raises(RuntimeStartError) as exc:
        promote_deployment_to_active(
            session,
            strategy_deployment_id=1,
            actor="admin:1",
            confirmation_text="START RUNTIME NOW",
        )
    assert exc.value.code == "INVALID_STATUS"
