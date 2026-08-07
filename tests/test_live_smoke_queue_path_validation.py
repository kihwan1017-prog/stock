"""LIVE Smoke QUEUED 경로 검증 — Adapter/실주문 API 0회.

실 Upbit 호출·UBA 1380 실데이터 변경·alembic upgrade 금지.
fixture/mock + session commit spy 로 queue 경로만 검증한다.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.order.execution_service import (
    OrderExecutionCommand,
    OrderExecutionResult,
    OrderExecutionService,
)
from stock_platform.order.models import OrderSide, OrderType
from stock_platform.trading.controlled_live_order_smoke_service import (
    ControlledLiveOrderSmokeService,
)
from stock_platform.trading.upbit_live_smoke_constants import (
    CONFIRMATION_TEXT,
    LIVE_ORDER_SMOKE_FAILED,
    LIVE_ORDER_SMOKE_SUBMITTED,
    LiveValidationRunStatus,
)
from stock_platform.trading.upbit_live_smoke_service import (
    UpbitLiveSmokeService,
)


def _preflight() -> SimpleNamespace:
    return SimpleNamespace(
        live_execution_ready=True,
        blockers=[],
        live_blockers=[],
        quantity="0.001",
        limit_price="100",
        estimated_amount="5000",
        preflight_id="pf-queue-1",
        user_id=61,
        to_dict=lambda: {
            "preflight_id": "pf-queue-1",
            "quantity": "0.001",
            "user_id": 61,
            "user_broker_account_id": 1380,
            "market": "KRW-BTC",
            "side": "BUY",
            "estimated_amount": "5000",
            "limit_price": "100",
            "request_fingerprint": "fp-q",
        },
        request_fingerprint="fp-q",
    )


def _run_entity() -> SimpleNamespace:
    return SimpleNamespace(
        run_id="uvs-queue-path-1",
        status_code=LiveValidationRunStatus.CREATED.value,
        internal_status=LiveValidationRunStatus.CREATED.value,
        detail={},
        failure_code=None,
        failure_summary=None,
        user_id=61,
        broker_order_status="NOT_SUBMITTED",
        order_id=None,
        execute_live=True,
        updated_at=None,
        completed_at=None,
        submitted_at=None,
        order_status=None,
        correlation_id=None,
        broker_identifier=None,
        watch_deadline_at=None,
        next_track_at=None,
    )


def test_order_execution_submit_queues_without_adapter() -> None:
    """OES.submit → trading_order + outbox + commit, create_order 0."""

    session = MagicMock()
    session.is_active = True
    created: list[object] = []
    enqueued: list[object] = []
    commits: list[str] = []

    order = SimpleNamespace(
        order_id=1001,
        client_order_id="cli-q-1",
        account_id=1380,
        user_broker_account_id=1380,
        broker_code="UPBIT",
        exchange_code="UPBIT",
        symbol="KRW-BTC",
        side_code="BUY",
        order_type_code="LIMIT",
        order_quantity=Decimal("0.001"),
        order_price=Decimal("100"),
        time_in_force_code="DAY",
        status_code="PENDING",
        strategy_code=None,
    )
    outbox = SimpleNamespace(outbox_id=2002, order_id=1001)

    svc = OrderExecutionService(session)
    svc._order_service.create = MagicMock(side_effect=lambda *a, **k: (
        created.append(order),
        order,
    )[1])
    svc._order_repository.change_status = MagicMock(return_value=order)
    svc._order_repository.get = MagicMock(return_value=None)
    svc._outbox_repository.get_by_idempotency_key = MagicMock(return_value=None)
    svc._outbox_repository.enqueue = MagicMock(
        side_effect=lambda **kw: (enqueued.append(kw), outbox)[1]
    )
    session.commit = MagicMock(side_effect=lambda: commits.append("commit"))
    session.refresh = MagicMock()

    safety = SimpleNamespace(allowed=True, reason_code=None)

    # LIVE 게이트는 모듈 내부 lazy import → 원본 모듈 경로를 patch
    with (
        patch(
            "stock_platform.order.live_safety_pipeline.LiveOrderSafetyPipeline"
        ) as Safety,
        patch(
            "stock_platform.operation.live_health_gate.assert_live_orders_allowed"
        ),
        patch(
            "stock_platform.order.execution_service.PersistentKillSwitchGuard"
        ) as KS,
        patch(
            "stock_platform.broker.recovery_lock.RecoveryAccountLockService"
        ) as Lock,
        patch(
            "stock_platform.broker.credential_vault_service.BrokerCredentialVaultService"
        ) as Vault,
        patch(
            "stock_platform.order.execution_service.DatabaseBackedRiskOrderGuard"
        ) as Risk,
        patch(
            "stock_platform.broker.upbit.order_client.UpbitOrderRestClient.create_order"
        ) as create_order,
        patch(
            "stock_platform.broker.upbit.adapter.UpbitBrokerAdapter.submit_order"
        ) as submit_order,
    ):
        Safety.return_value.evaluate.return_value = safety
        Safety.return_value.notify_submitted = MagicMock()
        KS.return_value.require_order_allowed = MagicMock()
        Lock.return_value.is_trading_paused.return_value = False
        Vault.return_value.assert_live_order_allowed = MagicMock()
        Risk.return_value.check.return_value = SimpleNamespace(
            allowed=True, blocked_reason=None
        )

        result = svc.submit(
            OrderExecutionCommand(
                account_id=None,
                broker_code="UPBIT",
                exchange_code="UPBIT",
                symbol="KRW-BTC",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                price=Decimal("100"),
                quantity=Decimal("0.001"),
                environment="LIVE",
                user_broker_account_id=1380,
                owner_user_id=61,
                user_id=61,
                arm_token="tok",
                order_source="UPBIT_LIVE_SMOKE",
                actor="queue-test",
                idempotency_key="smoke:uvs-queue-path-1",
            )
        )

    assert result.allowed is True
    assert result.reason_code == "QUEUED"
    assert result.order_id == 1001
    assert result.outbox_id == 2002
    assert len(created) == 1
    assert len(enqueued) == 1
    assert "commit" in commits
    create_order.assert_not_called()
    submit_order.assert_not_called()
    # session 재사용 가능
    session.rollback = MagicMock()
    session.rollback()
    session.rollback.assert_called_once()


def test_smoke_execute_queued_markers_and_no_adapter() -> None:
    """execute() → markers → QUEUED, Adapter create_order 0."""

    from datetime import datetime, timedelta, timezone

    session = MagicMock()
    session.is_active = True
    session.new = set()
    session.dirty = set()
    session.deleted = set()
    session.get.return_value = SimpleNamespace(
        user_broker_account_id=1380,
        user_id=61,
        live_armed=True,
        live_order_enabled=True,
        arm_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        broker_code="UPBIT",
        is_active=True,
    )
    run = _run_entity()
    transitions: list[str] = []
    submit_entered: list[bool] = []

    queued = OrderExecutionResult(
        allowed=True,
        reason_code="QUEUED",
        order_id=1001,
        outbox_id=2002,
        status_code="PENDING",
        client_order_id="cli-q-1",
        quantity=Decimal("0.001"),
        price=Decimal("100"),
    )

    def fake_submit(cmd: OrderExecutionCommand) -> OrderExecutionResult:
        submit_entered.append(True)
        assert cmd.environment == "LIVE"
        assert cmd.user_broker_account_id == 1380
        assert cmd.broker_code == "UPBIT"
        return queued

    with (
        patch(
            "stock_platform.trading.upbit_live_smoke_service.UpbitLivePreflightService"
        ) as PF,
        patch(
            "stock_platform.trading.upbit_live_tracking_service.UpbitLiveTrackingService"
        ) as Track,
        patch(
            "stock_platform.trading.upbit_live_smoke_service.emit_live_safety_audit"
        ),
        patch(
            "stock_platform.trading.upbit_live_smoke_service.emit_live_order_telegram"
        ),
        patch(
            "stock_platform.trading.upbit_live_smoke_service.LiveArmService"
        ),
        patch(
            "stock_platform.order.execution_service.OrderExecutionService.submit",
            side_effect=fake_submit,
        ),
        patch(
            "stock_platform.broker.upbit.order_client.UpbitOrderRestClient.create_order"
        ) as create_order,
        patch.object(UpbitLiveSmokeService, "_create_run", return_value=run),
        patch.object(UpbitLiveSmokeService, "_pause_uba_scope"),
        patch.object(
            UpbitLiveSmokeService,
            "_transition",
            side_effect=lambda r, st, actor: (
                transitions.append(st),
                setattr(r, "status_code", st),
                setattr(r, "internal_status", st),
            ),
        ),
        patch.object(
            UpbitLiveSmokeService, "_watch_and_maybe_cancel", return_value={}
        ),
    ):
        Track.return_value.blocks_new_order.return_value = False
        Track.return_value.attach_after_execution = MagicMock()
        PF.return_value.run.return_value = _preflight()

        result = UpbitLiveSmokeService(session).execute(
            user_broker_account_id=1380,
            market="KRW-BTC",
            side="BUY",
            amount=Decimal("5000"),
            limit_price=Decimal("100"),
            actor="queue-test",
            arm_token="tok",
            execute_live=True,
            confirmation_text=CONFIRMATION_TEXT,
            skip_live_network=True,
        )

    assert submit_entered == [True]
    assert LiveValidationRunStatus.EXECUTION_REQUESTED.value in transitions
    assert LiveValidationRunStatus.QUEUED.value in transitions
    markers = result["pipeline_markers"]
    assert "BEFORE_ORDER_EXECUTION_SUBMIT" in markers
    assert "AFTER_ORDER_EXECUTION_SUBMIT" in markers
    assert "SUBMIT_ALLOWED" in markers
    assert "AFTER_QUEUE_COMMIT" in markers
    assert result["status"] == "QUEUED"
    assert result["order_id"] == 1001
    assert result["outbox_id"] == 2002
    assert result["queued"] is True
    assert result["create_order_calls"] == 0
    assert result["order_submitted"] is False
    create_order.assert_not_called()


def test_controlled_confirm_submitted_audit_only_after_queued() -> None:
    """LIVE_ORDER_SMOKE_SUBMITTED는 QUEUED(order+outbox) 확인 후에만."""

    session = MagicMock()
    audits: list[tuple[str, dict]] = []

    def capture_audit(*_a, **kw):
        audits.append((str(kw.get("event_type") or ""), dict(kw.get("detail") or {})))

    queued_result = {
        "run_id": "uvs-queue-path-1",
        "queued": True,
        "reason_code": "QUEUED",
        "status": "QUEUED",
        "order_id": 1001,
        "outbox_id": 2002,
        "broker_order_status": "NOT_SUBMITTED",
        "create_order_calls": 0,
        "order_submitted": False,
        "pipeline_markers": [
            "BEFORE_ORDER_EXECUTION_SUBMIT",
            "AFTER_ORDER_EXECUTION_SUBMIT",
            "SUBMIT_ALLOWED",
            "AFTER_QUEUE_COMMIT",
        ],
    }

    with (
        patch.object(
            ControlledLiveOrderSmokeService,
            "_load_owned_upbit",
            return_value=SimpleNamespace(
                user_broker_account_id=1380,
                user_id=61,
                broker_code="UPBIT",
                live_order_enabled=True,
                live_armed=True,
            ),
        ),
        patch.object(
            ControlledLiveOrderSmokeService, "_assert_runtime_stopped"
        ),
        patch.object(
            ControlledLiveOrderSmokeService, "_assert_order_test_fresh"
        ),
        patch(
            "stock_platform.trading.controlled_live_order_smoke_service.RuntimePreflightService"
        ) as RPF,
        patch(
            "stock_platform.trading.controlled_live_order_smoke_service.evaluate_preflight_freshness",
            return_value={"fresh": True},
        ),
        patch(
            "stock_platform.trading.controlled_live_order_smoke_service.emit_live_safety_audit",
            side_effect=capture_audit,
        ),
        patch(
            "stock_platform.trading.controlled_live_order_smoke_service.UpbitLiveSmokeService.execute",
            return_value=queued_result,
        ),
        patch(
            "stock_platform.broker.upbit.order_client.UpbitOrderRestClient.create_order"
        ) as create_order,
    ):
        RPF.return_value.run_for_uba.return_value = {
            "manual_order_allowed": True,
            "checked_at": "2099-01-01T00:00:00+00:00",
        }
        out = ControlledLiveOrderSmokeService(session).confirm(
            uba_id=1380,
            user_id=61,
            actor="queue-test",
            market="KRW-BTC",
            side="BUY",
            amount=Decimal("5000"),
            limit_price=Decimal("100"),
            confirmation_text="UPBIT LIVE BUY CONFIRM",
            arm_token="tok",
            execute_live=True,
            order_test_fingerprint="fp",
            order_test_tested_at="2099-01-01T00:00:00+00:00",
        )

    event_types = [e for e, _ in audits]
    assert LIVE_ORDER_SMOKE_FAILED not in event_types
    assert LIVE_ORDER_SMOKE_SUBMITTED in event_types
    # CONFIRMED 후 SUBMITTED 순서
    assert event_types.index(LIVE_ORDER_SMOKE_SUBMITTED) > 0
    submitted_detail = next(
        d for e, d in audits if e == LIVE_ORDER_SMOKE_SUBMITTED
    )
    assert submitted_detail.get("reason_code") == "QUEUED"
    assert submitted_detail.get("order_id") == 1001
    assert submitted_detail.get("outbox_id") == 2002
    assert submitted_detail.get("status") == "QUEUED"
    assert out.get("order_id") == 1001
    assert out.get("outbox_id") == 2002
    create_order.assert_not_called()


def test_confirm_without_outbox_never_emits_submitted() -> None:
    session = MagicMock()
    audits: list[str] = []

    bad = {
        "run_id": "uvs-bad",
        "reason_code": "DRY_RUN_BLOCKED",
        "status": "CREATED",
        "order_id": 1,
        "outbox_id": None,
        "queued": False,
    }

    with (
        patch.object(
            ControlledLiveOrderSmokeService,
            "_load_owned_upbit",
            return_value=SimpleNamespace(
                user_broker_account_id=1380,
                user_id=61,
                broker_code="UPBIT",
                live_order_enabled=True,
                live_armed=True,
            ),
        ),
        patch.object(
            ControlledLiveOrderSmokeService, "_assert_runtime_stopped"
        ),
        patch.object(
            ControlledLiveOrderSmokeService, "_assert_order_test_fresh"
        ),
        patch(
            "stock_platform.trading.controlled_live_order_smoke_service.RuntimePreflightService"
        ) as RPF,
        patch(
            "stock_platform.trading.controlled_live_order_smoke_service.evaluate_preflight_freshness",
            return_value={"fresh": True},
        ),
        patch(
            "stock_platform.trading.controlled_live_order_smoke_service.emit_live_safety_audit",
            side_effect=lambda *a, **kw: audits.append(
                str(kw.get("event_type") or "")
            ),
        ),
        patch(
            "stock_platform.trading.controlled_live_order_smoke_service.UpbitLiveSmokeService.execute",
            return_value=bad,
        ),
        patch(
            "stock_platform.broker.upbit.order_client.UpbitOrderRestClient.create_order"
        ) as create_order,
    ):
        RPF.return_value.run_for_uba.return_value = {
            "manual_order_allowed": True,
            "checked_at": "2099-01-01T00:00:00+00:00",
        }
        with pytest.raises(Exception) as ei:
            ControlledLiveOrderSmokeService(session).confirm(
                uba_id=1380,
                user_id=61,
                actor="queue-test",
                market="KRW-BTC",
                side="BUY",
                amount=Decimal("5000"),
                limit_price=Decimal("100"),
                confirmation_text="UPBIT LIVE BUY CONFIRM",
                arm_token="tok",
                execute_live=True,
                order_test_fingerprint="fp",
                order_test_tested_at="2099-01-01T00:00:00+00:00",
            )
        assert "LIVE_SMOKE_NOT_QUEUED" in str(ei.value)
        assert LIVE_ORDER_SMOKE_SUBMITTED not in audits
        assert LIVE_ORDER_SMOKE_FAILED in audits
        create_order.assert_not_called()
