"""LIVE pre-order hardening — ORM recovery FK, market session, dry-run."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.order.execution_service import (
    OrderExecutionCommand,
    OrderExecutionService,
)
from stock_platform.order.live_dry_run import (
    dry_run_block_dispatch_result,
    is_live_dry_run_mode,
    reset_dry_run_counters,
    should_block_live_dry_run,
    validate_pre_submit_payload,
)
from stock_platform.order.models import OrderSide, OrderType
from stock_platform.order.outbox_dispatcher import OrderOutboxDispatcher
from stock_platform.order.outbox_models import OutboxEventType
from stock_platform.risk_engine.rules import TradingTimeRule
from stock_platform.risk_engine.models import RiskDecisionLevel, RiskOrderSide


def test_recovery_orm_mapper_registers_run_table() -> None:
    from stock_platform.database.base import Base
    from stock_platform.broker.recovery_account_state import (
        BrokerRecoveryAccountStateEntity,
    )
    from stock_platform.broker.recovery_entities import BrokerRecoveryRunEntity

    assert "broker_recovery_run" in {
        t.name for t in Base.metadata.tables.values()
    }
    assert BrokerRecoveryRunEntity.__tablename__ == "broker_recovery_run"
    assert (
        BrokerRecoveryAccountStateEntity.__tablename__
        == "broker_recovery_account_state"
    )
    # FK 대상이 metadata에 존재
    assert (
        "operation.broker_recovery_run"
        in Base.metadata.tables
        or any(
            t.fullname == "operation" and t.name == "broker_recovery_run"
            for t in Base.metadata.tables.values()
        )
    )


def test_recovery_lock_acquire_release_orm() -> None:
    from stock_platform.broker.recovery_adapter import AccountRecoveryContext
    from stock_platform.broker.recovery_lock import RecoveryAccountLockService
    from stock_platform.database.session import get_session_factory

    SessionLocal = get_session_factory()
    with SessionLocal() as session:
        uba = session.execute(
            __import__("sqlalchemy", fromlist=["text"]).text(
                """
                SELECT user_broker_account_id, user_id
                FROM trading.user_broker_account
                WHERE broker_code='KIWOOM' AND is_active IS TRUE
                ORDER BY user_broker_account_id DESC LIMIT 1
                """
            )
        ).first()
        if uba is None:
            pytest.skip("no KIWOOM UBA")
        uba_id, user_id = int(uba[0]), int(uba[1])
        ctx = AccountRecoveryContext(
            broker_code="KIWOOM",
            user_id=user_id,
            market_type="STOCK",
            user_broker_account_id=uba_id,
        )
        svc = RecoveryAccountLockService(session)
        row, paused_before = svc.acquire(
            ctx, holder="TEST_ORM_PAUSE", ttl_seconds=30
        )
        assert row.trading_paused is True
        assert svc.is_trading_paused(
            user_broker_account_id=uba_id, broker_code="KIWOOM"
        )
        svc.release(
            ctx,
            status_code="SUCCESS",
            keep_paused=False,
            run_id=None,
            paused_before=False,
        )
        session.commit()
        assert not svc.is_trading_paused(
            user_broker_account_id=uba_id, broker_code="KIWOOM"
        )
        _ = paused_before


def test_shadow_does_not_skip_trading_time_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LIVE_SHADOW_MODE_ENABLED", "true")
    from stock_platform.common.settings import clear_settings_cache

    clear_settings_cache()
    order = SimpleNamespace(
        exchange_code="KRX",
        side=RiskOrderSide.BUY,
        requested_at=datetime.now(timezone.utc),
        is_risk_reducing=False,
    )
    policy = SimpleNamespace(enforce_krx_market_hours=True)
    with patch(
        "stock_platform.operation.session_timeline.resolve_krx_timeline"
    ) as resolve:
        timeline = MagicMock()
        timeline.phase_at.return_value = SimpleNamespace(value="NON_TRADING_DAY")
        timeline.allows_any_order.return_value = False
        timeline.revision = 1
        resolve.return_value = timeline
        with patch(
            "stock_platform.operation.session_timeline.phase_reason_code",
            return_value="MARKET_NON_TRADING_DAY",
        ):
            result = TradingTimeRule().evaluate(
                order=order, account=None, policy=policy
            )
    assert result.level == RiskDecisionLevel.BLOCK
    clear_settings_cache()


def test_dry_run_flag_default_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LIVE_ORDER_DRY_RUN_ENABLED", "false")
    from stock_platform.common.settings import clear_settings_cache, get_settings

    clear_settings_cache()
    assert get_settings().live_order_dry_run_enabled is False
    assert is_live_dry_run_mode() is False


def test_validate_pre_submit_payload() -> None:
    ok = validate_pre_submit_payload(
        {
            "client_order_id": "C1",
            "account_id": 1,
            "broker_code": "UPBIT",
            "exchange_code": "UPBIT",
            "symbol": "KRW-BTC",
            "side": "BUY",
            "order_type": "LIMIT",
            "quantity": "0.001",
            "price": "100",
            "user_broker_account_id": 58,
        }
    )
    assert ok == []
    bad = validate_pre_submit_payload({"order_type": "LIMIT"})
    assert "MISSING_SYMBOL" in bad
    assert "MISSING_PRICE" in bad


def test_dispatcher_dry_run_blocks_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LIVE_ORDER_DRY_RUN_ENABLED", "true")
    from stock_platform.common.settings import clear_settings_cache

    clear_settings_cache()
    reset_dry_run_counters()
    adapter = MagicMock()
    adapter.submit_order.side_effect = AssertionError("must not submit")
    dispatcher = OrderOutboxDispatcher(adapter=adapter, session=MagicMock())
    payload = {
        "environment": "LIVE",
        "dry_run": True,
        "client_order_id": "D1",
        "account_id": 1,
        "broker_code": "UPBIT",
        "exchange_code": "UPBIT",
        "symbol": "KRW-BTC",
        "side": "BUY",
        "order_type": "LIMIT",
        "quantity": "0.001",
        "price": "100",
        "user_broker_account_id": 58,
    }
    result = dispatcher.dispatch(
        event_type=OutboxEventType.SUBMIT_ORDER.value,
        payload=payload,
        idempotency_key="DRY-1",
        session=MagicMock(),
    )
    assert result["reject_code"] == "DRY_RUN_BLOCKED"
    assert result["broker_order_id"] is None
    assert result["pre_submit_ok"] is True
    assert adapter.submit_order.call_count == 0
    clear_settings_cache()


def test_execution_service_dry_run_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LIVE_ORDER_DRY_RUN_ENABLED", "true")
    from stock_platform.common.settings import clear_settings_cache

    clear_settings_cache()
    session = MagicMock()
    svc = OrderExecutionService.__new__(OrderExecutionService)
    svc._session = session
    created = SimpleNamespace(
        order_id=501,
        client_order_id="C-DRY",
        account_id=1,
        user_broker_account_id=58,
        broker_code="UPBIT",
        exchange_code="UPBIT",
        symbol="KRW-BTC",
        side_code="BUY",
        order_type_code="LIMIT",
        order_quantity=Decimal("0.001"),
        order_price=Decimal("100"),
        time_in_force_code="DAY",
        status_code="CREATED",
        broker_order_id=None,
        metadata_payload={},
        reject_code=None,
        reject_message=None,
    )
    svc._order_service = SimpleNamespace(
        create=lambda *a, **k: created
    )
    svc._order_repository = SimpleNamespace(
        get=lambda oid: created,
    )
    svc._outbox_repository = SimpleNamespace(
        get_by_idempotency_key=lambda k: None,
        enqueue=MagicMock(side_effect=AssertionError("no outbox")),
    )
    svc._sizing_engine = SimpleNamespace()

    with patch.object(
        OrderExecutionService,
        "_resolve_size",
        return_value=(Decimal("0.001"), Decimal("100"), None),
    ):
        result = svc.submit(
            OrderExecutionCommand(
                account_id=1,
                broker_code="UPBIT",
                exchange_code="UPBIT",
                symbol="KRW-BTC",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.001"),
                price=Decimal("100"),
                environment="LIVE",
                user_broker_account_id=58,
                user_id=7,
                skip_risk_checks=True,
                actor="TEST",
                idempotency_key="DRY-IDEM-1",
                client_order_id="C-DRY",
            )
        )

    assert result.allowed is True
    assert result.reason_code == "DRY_RUN_BLOCKED"
    assert result.outbox_id is None
    assert created.reject_code == "DRY_RUN_BLOCKED"
    assert created.broker_order_id is None
    clear_settings_cache()


def test_should_block_live_dry_run() -> None:
    assert should_block_live_dry_run({"environment": "PAPER"}) is False
    assert (
        should_block_live_dry_run(
            {"environment": "LIVE", "dry_run": True}
        )
        is True
    )


def test_dry_run_block_result_shape() -> None:
    reset_dry_run_counters()
    out = dry_run_block_dispatch_result(
        event_type="SUBMIT_ORDER",
        payload={
            "client_order_id": "x",
            "account_id": 1,
            "broker_code": "KIWOOM",
            "exchange_code": "KRX",
            "symbol": "005930",
            "side": "BUY",
            "order_type": "LIMIT",
            "quantity": "1",
            "price": "70000",
            "user_broker_account_id": 1,
        },
    )
    assert out["status"] == "DRY_RUN_BLOCKED"
    assert out["pre_submit_ok"] is True
