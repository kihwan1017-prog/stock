from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from stock_platform.broker.kiwoom.price import normalize_kiwoom_price
from stock_platform.order.execution_service import (
    PERSIST_COMMIT,
    PERSIST_CREATE_ORDER,
    PERSIST_ENQUEUE_OUTBOX,
    PERSIST_FLUSH_ORDER,
    OrderExecutionCommand,
    OrderExecutionService,
    REASON_ORDER_COMMIT_FAILED,
    REASON_ORDER_OUTBOX_ENQUEUE_FAILED,
    REASON_ORDER_PERSIST_FAILED,
    sanitize_persist_error_message,
)
from stock_platform.order.models import OrderSide, OrderType
from stock_platform.risk.engine import RiskManagementEngine


@pytest.fixture(autouse=True)
def _live_queue_allows_missing_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    """이 파일은 persist/queue 회귀용 — worker 백프레셔는 24x7 테스트에서 검증."""

    monkeypatch.setattr(
        "stock_platform.trading.upbit_24x7_control.live_outbox_queue_block_reason",
        lambda: None,
    )


def test_resolve_size_uses_explicit_quantity() -> None:
    service = OrderExecutionService.__new__(OrderExecutionService)
    service._sizing_engine = RiskManagementEngine()

    quantity, price, plan = service._resolve_size(
        OrderExecutionCommand(
            account_id=1,
            broker_code="KIWOOM",
            exchange_code="KRX",
            symbol="005930",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("3"),
            price=Decimal("70000"),
        )
    )
    assert quantity == Decimal("3")
    assert price == Decimal("70000")
    assert plan is None


def test_resolve_size_rejects_limit_without_price() -> None:
    service = OrderExecutionService.__new__(OrderExecutionService)
    service._sizing_engine = RiskManagementEngine()
    try:
        service._resolve_size(
            OrderExecutionCommand(
                account_id=1,
                broker_code="KIWOOM",
                exchange_code="KRX",
                symbol="005930",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("1"),
                price=None,
            )
        )
        raised = False
    except ValueError:
        raised = True
    assert raised is True


def _integrity_error(message: str = "duplicate key") -> IntegrityError:
    return IntegrityError("INSERT", {}, Exception(message))


def _kiwoom_live_command(**kwargs: object) -> OrderExecutionCommand:
    payload = {
        "account_id": None,
        "broker_code": "KIWOOM",
        "exchange_code": "KRX",
        "symbol": "009240",
        "side": OrderSide.BUY,
        "order_type": OrderType.LIMIT,
        "price": Decimal("40200"),
        "quantity": Decimal("1"),
        "environment": "LIVE",
        "user_broker_account_id": 1381,
        "owner_user_id": 61,
        "user_id": 61,
        "actor": "persist-test",
        "order_source": "MANUAL",
        "client_order_id": "K1381-TEST-CID",
        "idempotency_key": "kiwoom-persist-test:cid",
    }
    payload.update(kwargs)
    return OrderExecutionCommand(**payload)  # type: ignore[arg-type]


def _paper_command(**kwargs: object) -> OrderExecutionCommand:
    payload = {
        "account_id": 1,
        "broker_code": "PAPER",
        "exchange_code": "PAPER",
        "symbol": "005930",
        "side": OrderSide.BUY,
        "order_type": OrderType.LIMIT,
        "price": Decimal("70000"),
        "quantity": Decimal("1"),
        "environment": "PAPER",
        "account_number": "PAPER-1",
        "actor": "paper-persist-test",
        "order_source": "MANUAL",
        "skip_risk_checks": True,
        "client_order_id": "PAPER-TEST-CID",
        "idempotency_key": "paper-persist-test:cid",
    }
    payload.update(kwargs)
    return OrderExecutionCommand(**payload)  # type: ignore[arg-type]


def _queued_order(broker: str = "KIWOOM") -> SimpleNamespace:
    exchange = "KRX" if broker == "KIWOOM" else (
        "UPBIT" if broker == "UPBIT" else "PAPER"
    )
    symbol = "009240" if broker == "KIWOOM" else (
        "KRW-BTC" if broker == "UPBIT" else "005930"
    )
    return SimpleNamespace(
        order_id=9001,
        client_order_id="cli-persist-1",
        account_id=None if broker != "PAPER" else 1,
        user_broker_account_id=1381 if broker == "KIWOOM" else (
            1380 if broker == "UPBIT" else None
        ),
        broker_code=broker,
        exchange_code=exchange,
        symbol=symbol,
        side_code="BUY",
        order_type_code="LIMIT",
        order_quantity=Decimal("1"),
        order_price=Decimal("40200") if broker == "KIWOOM" else Decimal("100"),
        time_in_force_code="DAY",
        status_code="PENDING",
        strategy_code=None,
        strategy_id=None,
    )


def _wired_service(
    session: MagicMock,
    *,
    order: SimpleNamespace | None = None,
) -> tuple[OrderExecutionService, list[object], list[object]]:
    created: list[object] = []
    enqueued: list[object] = []
    svc = OrderExecutionService(session)
    resolved = order or _queued_order()
    outbox = SimpleNamespace(outbox_id=8002, order_id=resolved.order_id)

    def _create(*_a: object, **_k: object) -> SimpleNamespace:
        created.append(resolved)
        return resolved

    def _enqueue(**kwargs: object) -> SimpleNamespace:
        enqueued.append(kwargs)
        return outbox

    svc._order_service.create = MagicMock(side_effect=_create)
    svc._order_repository.change_status = MagicMock(return_value=resolved)
    svc._order_repository.get = MagicMock(return_value=None)
    svc._outbox_repository.get_by_idempotency_key = MagicMock(return_value=None)
    svc._outbox_repository.enqueue = MagicMock(side_effect=_enqueue)
    return svc, created, enqueued


def _configure_live_pass(Safety, KS, Lock, Vault, Risk) -> None:
    Safety.return_value.evaluate.return_value = SimpleNamespace(
        allowed=True, reason_code="LIVE_SAFETY_PASS", detail={}
    )
    Safety.return_value.notify_submitted = MagicMock()
    KS.return_value.require_order_allowed = MagicMock()
    Lock.return_value.is_trading_paused.return_value = False
    Vault.return_value.assert_live_order_allowed = MagicMock()
    Risk.return_value.check.return_value = SimpleNamespace(
        allowed=True, blocked_reason=None
    )


def test_sanitize_persist_error_message_redacts_secrets() -> None:
    class _Boom(Exception):
        pass

    text = sanitize_persist_error_message(
        _Boom("arm_token=raw-secret account_number=1234567890 Bearer abcdefghijk")
    )
    assert "raw-secret" not in text
    assert "1234567890" not in text
    assert "abcdefghijk" not in text
    assert "<redacted>" in text or "[SECRET]" in text


def test_kiwoom_live_limit_buy_queues_without_broker() -> None:
    """KIWOOM LIVE LIMIT BUY 1주 — TO/Outbox persist, broker CREATE 0."""

    normalized = normalize_kiwoom_price("-40200")
    assert normalized == Decimal("40200")

    session = MagicMock()
    session.is_active = True
    rollbacks: list[str] = []
    session.rollback = MagicMock(side_effect=lambda: rollbacks.append("rollback"))
    session.commit = MagicMock()
    session.refresh = MagicMock()
    session.flush = MagicMock()

    svc, created, enqueued = _wired_service(session, order=_queued_order("KIWOOM"))
    kiwoom_submit = MagicMock()
    upbit_submit = MagicMock()

    with (
        patch("stock_platform.order.live_safety_pipeline.LiveOrderSafetyPipeline") as Safety,
        patch("stock_platform.operation.live_health_gate.assert_live_orders_allowed"),
        patch("stock_platform.order.execution_service.PersistentKillSwitchGuard") as KS,
        patch("stock_platform.broker.recovery_lock.RecoveryAccountLockService") as Lock,
        patch(
            "stock_platform.broker.credential_vault_service.BrokerCredentialVaultService"
        ) as Vault,
        patch("stock_platform.order.execution_service.DatabaseBackedRiskOrderGuard") as Risk,
        patch(
            "stock_platform.broker.kiwoom.adapter.KiwoomBrokerAdapter.submit_order",
            kiwoom_submit,
        ),
        patch(
            "stock_platform.broker.upbit.adapter.UpbitBrokerAdapter.submit_order",
            upbit_submit,
        ),
    ):
        _configure_live_pass(Safety, KS, Lock, Vault, Risk)
        result = svc.submit(_kiwoom_live_command(price=normalized, quantity=Decimal("1")))

    assert result.allowed is True
    assert result.reason_code == "QUEUED"
    assert result.order_id == 9001
    assert result.outbox_id == 8002
    assert result.failed_stage is None
    assert len(created) == 1
    assert len(enqueued) == 1
    assert enqueued[0]["payload_json"]["environment"] == "LIVE"
    assert enqueued[0]["payload_json"]["symbol"] == "009240"
    session.commit.assert_called()
    kiwoom_submit.assert_not_called()
    upbit_submit.assert_not_called()
    assert rollbacks == []


def test_persist_create_valueerror_is_technical_block() -> None:
    session = MagicMock()
    session.is_active = True
    session.rollback = MagicMock()
    svc, created, enqueued = _wired_service(session)
    svc._order_service.create = MagicMock(
        side_effect=ValueError("client_order_id already exists")
    )

    with (
        patch("stock_platform.order.live_safety_pipeline.LiveOrderSafetyPipeline") as Safety,
        patch("stock_platform.operation.live_health_gate.assert_live_orders_allowed"),
        patch("stock_platform.order.execution_service.PersistentKillSwitchGuard") as KS,
        patch("stock_platform.broker.recovery_lock.RecoveryAccountLockService") as Lock,
        patch(
            "stock_platform.broker.credential_vault_service.BrokerCredentialVaultService"
        ) as Vault,
        patch("stock_platform.order.execution_service.DatabaseBackedRiskOrderGuard") as Risk,
        patch("stock_platform.order.outbox_fencing.record_outbox_audit"),
    ):
        _configure_live_pass(Safety, KS, Lock, Vault, Risk)
        result = svc.submit(_kiwoom_live_command())

    assert result.allowed is False
    assert result.reason_code == REASON_ORDER_PERSIST_FAILED
    assert result.failed_stage == PERSIST_CREATE_ORDER
    assert result.exception_class == "ValueError"
    assert "already exists" in (result.sanitized_message or "")
    assert created == []
    assert enqueued == []
    session.rollback.assert_called()


def test_persist_flush_integrityerror_rolls_back() -> None:
    session = MagicMock()
    session.is_active = True
    session.rollback = MagicMock()
    session.flush = MagicMock(side_effect=_integrity_error("uq_trading_order"))
    svc, created, enqueued = _wired_service(session)

    with (
        patch("stock_platform.order.live_safety_pipeline.LiveOrderSafetyPipeline") as Safety,
        patch("stock_platform.operation.live_health_gate.assert_live_orders_allowed"),
        patch("stock_platform.order.execution_service.PersistentKillSwitchGuard") as KS,
        patch("stock_platform.broker.recovery_lock.RecoveryAccountLockService") as Lock,
        patch(
            "stock_platform.broker.credential_vault_service.BrokerCredentialVaultService"
        ) as Vault,
        patch("stock_platform.order.execution_service.DatabaseBackedRiskOrderGuard") as Risk,
        patch("stock_platform.order.outbox_fencing.record_outbox_audit"),
    ):
        _configure_live_pass(Safety, KS, Lock, Vault, Risk)
        result = svc.submit(_kiwoom_live_command())

    assert result.allowed is False
    assert result.reason_code == REASON_ORDER_PERSIST_FAILED
    assert result.failed_stage == PERSIST_FLUSH_ORDER
    assert result.exception_class == "IntegrityError"
    assert enqueued == []
    session.rollback.assert_called()
    svc._outbox_repository.enqueue.assert_not_called()
    assert len(created) == 1  # create 호출 후 flush 실패 — 트랜잭션 rollback


def test_persist_outbox_enqueue_failure_rolls_back() -> None:
    session = MagicMock()
    session.is_active = True
    session.rollback = MagicMock()
    session.flush = MagicMock()
    svc, created, enqueued = _wired_service(session)
    svc._outbox_repository.enqueue = MagicMock(
        side_effect=_integrity_error("uq_order_outbox_idempotency")
    )

    with (
        patch("stock_platform.order.live_safety_pipeline.LiveOrderSafetyPipeline") as Safety,
        patch("stock_platform.operation.live_health_gate.assert_live_orders_allowed"),
        patch("stock_platform.order.execution_service.PersistentKillSwitchGuard") as KS,
        patch("stock_platform.broker.recovery_lock.RecoveryAccountLockService") as Lock,
        patch(
            "stock_platform.broker.credential_vault_service.BrokerCredentialVaultService"
        ) as Vault,
        patch("stock_platform.order.execution_service.DatabaseBackedRiskOrderGuard") as Risk,
        patch("stock_platform.order.outbox_fencing.record_outbox_audit"),
        patch("stock_platform.broker.kiwoom.adapter.KiwoomBrokerAdapter.submit_order") as kiwoom_submit,
    ):
        _configure_live_pass(Safety, KS, Lock, Vault, Risk)
        result = svc.submit(_kiwoom_live_command())

    assert result.allowed is False
    assert result.reason_code == REASON_ORDER_OUTBOX_ENQUEUE_FAILED
    assert result.failed_stage == PERSIST_ENQUEUE_OUTBOX
    assert result.exception_class == "IntegrityError"
    session.rollback.assert_called()
    kiwoom_submit.assert_not_called()
    # persist commit 전에 실패. audit 관측용 commit은 rollback 이후일 수 있음.


def test_persist_commit_failure_is_technical_block() -> None:
    session = MagicMock()
    session.is_active = True
    session.rollback = MagicMock()
    session.flush = MagicMock()
    session.commit = MagicMock(side_effect=_integrity_error("commit failed"))
    svc, created, enqueued = _wired_service(session)

    with (
        patch("stock_platform.order.live_safety_pipeline.LiveOrderSafetyPipeline") as Safety,
        patch("stock_platform.operation.live_health_gate.assert_live_orders_allowed"),
        patch("stock_platform.order.execution_service.PersistentKillSwitchGuard") as KS,
        patch("stock_platform.broker.recovery_lock.RecoveryAccountLockService") as Lock,
        patch(
            "stock_platform.broker.credential_vault_service.BrokerCredentialVaultService"
        ) as Vault,
        patch("stock_platform.order.execution_service.DatabaseBackedRiskOrderGuard") as Risk,
        patch("stock_platform.order.outbox_fencing.record_outbox_audit"),
        patch("stock_platform.broker.kiwoom.adapter.KiwoomBrokerAdapter.submit_order") as kiwoom_submit,
    ):
        _configure_live_pass(Safety, KS, Lock, Vault, Risk)
        result = svc.submit(_kiwoom_live_command())

    assert result.allowed is False
    assert result.reason_code == REASON_ORDER_COMMIT_FAILED
    assert result.failed_stage == PERSIST_COMMIT
    assert result.exception_class == "IntegrityError"
    session.rollback.assert_called()
    kiwoom_submit.assert_not_called()
    assert len(enqueued) == 1


def test_duplicate_idempotency_replay_does_not_create_second_row() -> None:
    session = MagicMock()
    existing_order = _queued_order("KIWOOM")
    existing_outbox = SimpleNamespace(outbox_id=77, order_id=existing_order.order_id)
    svc, created, enqueued = _wired_service(session, order=existing_order)
    svc._outbox_repository.get_by_idempotency_key = MagicMock(
        return_value=existing_outbox
    )
    svc._order_repository.get = MagicMock(return_value=existing_order)

    with (
        patch("stock_platform.order.live_safety_pipeline.LiveOrderSafetyPipeline") as Safety,
        patch("stock_platform.operation.live_health_gate.assert_live_orders_allowed"),
        patch("stock_platform.order.execution_service.PersistentKillSwitchGuard") as KS,
        patch("stock_platform.broker.recovery_lock.RecoveryAccountLockService") as Lock,
        patch(
            "stock_platform.broker.credential_vault_service.BrokerCredentialVaultService"
        ) as Vault,
        patch("stock_platform.order.execution_service.DatabaseBackedRiskOrderGuard") as Risk,
    ):
        _configure_live_pass(Safety, KS, Lock, Vault, Risk)
        result = svc.submit(_kiwoom_live_command())

    assert result.allowed is True
    assert result.reason_code == "IDEMPOTENT_REPLAY"
    assert result.order_id == existing_order.order_id
    assert result.outbox_id == 77
    svc._order_service.create.assert_not_called()
    svc._outbox_repository.enqueue.assert_not_called()
    assert created == []
    assert enqueued == []


def test_risk_business_block_is_not_persist_exception() -> None:
    session = MagicMock()
    session.rollback = MagicMock()
    svc, created, enqueued = _wired_service(session)

    with (
        patch("stock_platform.order.live_safety_pipeline.LiveOrderSafetyPipeline") as Safety,
        patch("stock_platform.operation.live_health_gate.assert_live_orders_allowed"),
        patch("stock_platform.order.execution_service.PersistentKillSwitchGuard") as KS,
        patch("stock_platform.broker.recovery_lock.RecoveryAccountLockService") as Lock,
        patch(
            "stock_platform.broker.credential_vault_service.BrokerCredentialVaultService"
        ) as Vault,
        patch("stock_platform.order.execution_service.DatabaseBackedRiskOrderGuard") as Risk,
    ):
        _configure_live_pass(Safety, KS, Lock, Vault, Risk)
        Risk.return_value.check.return_value = SimpleNamespace(
            allowed=False,
            blocked_reason="projected symbol position exceeds limit",
        )
        result = svc.submit(_kiwoom_live_command())

    assert result.allowed is False
    assert result.reason_code == "RISK_SYMBOL_POSITION_LIMIT_EXCEEDED"
    assert result.failed_stage is None
    assert result.exception_class is None
    svc._order_service.create.assert_not_called()
    assert created == []
    assert enqueued == []


def test_upbit_live_queue_regression_still_queued() -> None:
    session = MagicMock()
    session.is_active = True
    session.commit = MagicMock()
    session.refresh = MagicMock()
    session.flush = MagicMock()
    order = _queued_order("UPBIT")
    order.order_quantity = Decimal("0.001")
    order.order_price = Decimal("10000000")
    svc, created, enqueued = _wired_service(session, order=order)

    with (
        patch("stock_platform.order.live_safety_pipeline.LiveOrderSafetyPipeline") as Safety,
        patch("stock_platform.operation.live_health_gate.assert_live_orders_allowed"),
        patch("stock_platform.order.execution_service.PersistentKillSwitchGuard") as KS,
        patch("stock_platform.broker.recovery_lock.RecoveryAccountLockService") as Lock,
        patch(
            "stock_platform.broker.credential_vault_service.BrokerCredentialVaultService"
        ) as Vault,
        patch("stock_platform.order.execution_service.DatabaseBackedRiskOrderGuard") as Risk,
        patch("stock_platform.broker.upbit.adapter.UpbitBrokerAdapter.submit_order") as upbit_submit,
    ):
        _configure_live_pass(Safety, KS, Lock, Vault, Risk)
        result = svc.submit(
            OrderExecutionCommand(
                account_id=None,
                broker_code="UPBIT",
                exchange_code="UPBIT",
                symbol="KRW-BTC",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                price=Decimal("10000000"),
                quantity=Decimal("0.001"),
                environment="LIVE",
                user_broker_account_id=1380,
                owner_user_id=61,
                user_id=61,
                actor="upbit-regression",
                order_source="MANUAL",
                client_order_id="UPBIT-TEST-CID",
                idempotency_key="upbit-persist-test:cid",
            )
        )

    assert result.allowed is True
    assert result.reason_code == "QUEUED"
    assert len(created) == 1
    assert len(enqueued) == 1
    upbit_submit.assert_not_called()


def test_paper_submit_success_and_risk_block() -> None:
    session = MagicMock()
    session.is_active = True
    session.commit = MagicMock()
    session.refresh = MagicMock()
    session.flush = MagicMock()
    paper_order = _queued_order("PAPER")
    paper_order.order_price = Decimal("70000")
    svc, created, enqueued = _wired_service(session, order=paper_order)

    result = svc.submit(_paper_command())
    assert result.allowed is True
    assert result.reason_code == "QUEUED"
    assert len(created) == 1
    assert len(enqueued) == 1

    session2 = MagicMock()
    svc2, created2, enqueued2 = _wired_service(session2, order=paper_order)
    with (
        patch("stock_platform.order.execution_service.PersistentKillSwitchGuard") as KS,
        patch("stock_platform.broker.recovery_lock.RecoveryAccountLockService") as Lock,
        patch("stock_platform.order.execution_service.DatabaseBackedRiskOrderGuard") as Risk,
    ):
        KS.return_value.require_order_allowed = MagicMock()
        Lock.return_value.is_trading_paused.return_value = False
        Risk.return_value.check.return_value = SimpleNamespace(
            allowed=False,
            blocked_reason="projected symbol position exceeds limit",
        )
        blocked = svc2.submit(_paper_command(skip_risk_checks=False))

    assert blocked.allowed is False
    assert blocked.reason_code == "RISK_SYMBOL_POSITION_LIMIT_EXCEEDED"
    assert blocked.failed_stage is None
    svc2._order_service.create.assert_not_called()
    assert created2 == []
    assert enqueued2 == []
