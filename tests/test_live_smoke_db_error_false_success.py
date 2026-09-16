"""LIVE Smoke — SQLAlchemyError false-success 방지 / stage 계측."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import SQLAlchemyError

from stock_platform.api.v1.user_live_order_smoke import _map_error
from stock_platform.order.execution_service import (
    OrderExecutionResult,
    OrderExecutionService,
)
from stock_platform.trading.controlled_live_order_smoke_service import (
    ControlledLiveOrderSmokeError,
    ControlledLiveOrderSmokeService,
)
from stock_platform.trading.upbit_live_smoke_constants import (
    CONFIRMATION_TEXT,
    LIVE_ORDER_SMOKE_FAILED,
    LIVE_ORDER_SMOKE_SUBMITTED,
    LiveValidationRunStatus,
)
from stock_platform.trading.upbit_live_smoke_service import (
    UpbitLiveSmokeError,
    UpbitLiveSmokeService,
)


def _preflight() -> SimpleNamespace:
    return SimpleNamespace(
        live_execution_ready=True,
        blockers=[],
        live_blockers=[],
        quantity="0.0001",
        limit_price="100",
        estimated_amount="5000",
        preflight_id="pf-1",
        user_id=1,
        to_dict=lambda: {
            "preflight_id": "pf-1",
            "quantity": "0.0001",
            "user_id": 1,
            "user_broker_account_id": 1380,
            "market": "KRW-BTC",
            "side": "BUY",
            "estimated_amount": "5000",
            "limit_price": "100",
        },
        request_fingerprint="fp",
    )


def _run(**overrides):
    base = dict(
        run_id="uvs-dberr-1",
        status_code=LiveValidationRunStatus.CREATED.value,
        internal_status=LiveValidationRunStatus.CREATED.value,
        detail={},
        failure_code=None,
        failure_summary=None,
        user_id=1,
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
    base.update(overrides)
    return SimpleNamespace(**base)


def _session() -> MagicMock:
    session = MagicMock()
    session.is_active = True
    session.new = set()
    session.dirty = set()
    session.deleted = set()
    session.get.return_value = SimpleNamespace(
        user_broker_account_id=1380, user_id=1
    )
    return session


def test_transition_sqlalchemy_error_raises_db_error_no_submit() -> None:
    session = _session()
    run = _run()
    submit = MagicMock()

    def boom_transition(r, st, actor):
        raise SQLAlchemyError("flush failed at transition")

    with (
        patch(
            "stock_platform.trading.upbit_live_smoke_service.UpbitLivePreflightService"
        ) as PF,
        patch(
            "stock_platform.trading.upbit_live_tracking_service.UpbitLiveTrackingService"
        ) as Track,
        patch(
            "stock_platform.trading.upbit_live_smoke_service.emit_live_safety_audit"
        ) as audit,
        patch(
            "stock_platform.trading.upbit_live_smoke_service.emit_live_order_telegram"
        ),
        patch(
            "stock_platform.trading.upbit_live_smoke_service.LiveArmService"
        ),
        patch(
            "stock_platform.order.execution_service.OrderExecutionService.submit",
            submit,
        ),
        patch.object(UpbitLiveSmokeService, "_create_run", return_value=run),
        patch.object(UpbitLiveSmokeService, "_pause_uba_scope"),
        patch.object(
            UpbitLiveSmokeService, "_transition", side_effect=boom_transition
        ),
        patch.object(
            UpbitLiveSmokeService, "_watch_and_maybe_cancel", return_value={}
        ),
    ):
        Track.return_value.blocks_new_order.return_value = False
        PF.return_value.run.return_value = _preflight()
        with pytest.raises(UpbitLiveSmokeError) as ei:
            UpbitLiveSmokeService(session).execute(
                user_broker_account_id=1380,
                market="KRW-BTC",
                side="BUY",
                amount=Decimal("5000"),
                limit_price=Decimal("100"),
                actor="tester",
                arm_token="tok",
                execute_live=True,
                confirmation_text=CONFIRMATION_TEXT,
                skip_live_network=True,
            )
        err = ei.value
        assert err.code == "LIVE_SMOKE_DB_ERROR"
        assert err.http_status == 500
        assert err.status_code == "FAILED"
        assert err.order_submitted is False
        assert err.create_order_calls == 0
        submit.assert_not_called()
        event_types = [
            c.kwargs.get("event_type") for c in audit.call_args_list
        ]
        assert "UPBIT_LIVE_SMOKE_FAILED_CLOSED" in event_types


def test_submit_internal_sqlalchemy_error_markers() -> None:
    session = _session()
    run = _run()

    def boom_submit(_cmd):
        raise SQLAlchemyError("submit flush boom")

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
            side_effect=boom_submit,
        ),
        patch.object(UpbitLiveSmokeService, "_create_run", return_value=run),
        patch.object(UpbitLiveSmokeService, "_pause_uba_scope"),
        patch.object(
            UpbitLiveSmokeService,
            "_transition",
            side_effect=lambda r, st, actor: setattr(r, "status_code", st)
            or setattr(r, "internal_status", st),
        ),
        patch.object(
            UpbitLiveSmokeService, "_watch_and_maybe_cancel", return_value={}
        ),
    ):
        Track.return_value.blocks_new_order.return_value = False
        PF.return_value.run.return_value = _preflight()
        with pytest.raises(UpbitLiveSmokeError) as ei:
            UpbitLiveSmokeService(session).execute(
                user_broker_account_id=1380,
                market="KRW-BTC",
                side="BUY",
                amount=Decimal("5000"),
                limit_price=Decimal("100"),
                actor="tester",
                arm_token="tok",
                execute_live=True,
                confirmation_text=CONFIRMATION_TEXT,
                skip_live_network=True,
            )
        err = ei.value
        assert err.code == "LIVE_SMOKE_DB_ERROR"
        assert any("stage=" in d for d in err.details)
        assert any(
            "ORDER_EXECUTION_SUBMIT" in d for d in err.details
        )
        session.rollback.assert_called()


def test_reject_flush_sqlalchemy_error() -> None:
    session = _session()
    run = _run()
    blocked = OrderExecutionService._blocked(
        "RISK_ENGINE_BLOCKED", message="Daily loss limit reached"
    )
    session.flush.side_effect = SQLAlchemyError("reject flush boom")

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
            return_value=blocked,
        ),
        patch.object(UpbitLiveSmokeService, "_create_run", return_value=run),
        patch.object(UpbitLiveSmokeService, "_pause_uba_scope"),
        patch.object(
            UpbitLiveSmokeService,
            "_transition",
            side_effect=lambda r, st, actor: setattr(r, "status_code", st)
            or setattr(r, "internal_status", st),
        ),
        patch.object(
            UpbitLiveSmokeService, "_watch_and_maybe_cancel", return_value={}
        ),
    ):
        Track.return_value.blocks_new_order.return_value = False
        PF.return_value.run.return_value = _preflight()
        with pytest.raises(UpbitLiveSmokeError) as ei:
            UpbitLiveSmokeService(session).execute(
                user_broker_account_id=1380,
                market="KRW-BTC",
                side="BUY",
                amount=Decimal("5000"),
                limit_price=Decimal("100"),
                actor="tester",
                arm_token="tok",
                execute_live=True,
                confirmation_text=CONFIRMATION_TEXT,
                skip_live_network=True,
            )
        err = ei.value
        assert err.code == "LIVE_SMOKE_DB_ERROR"
        assert err.create_order_calls == 0
        assert err.order_submitted is False
        assert any("REJECT_FLUSH" in d or "stage=" in d for d in err.details)


def test_map_error_db_is_500_not_success() -> None:
    exc = ControlledLiveOrderSmokeError(
        "LIVE_SMOKE_DB_ERROR",
        message="실주문 요청을 저장하지 못했습니다.",
        http_status=500,
        order_submitted=False,
        create_order_calls=0,
        run_id="uvs-x",
        status_code="FAILED",
    )
    http = _map_error(exc)
    assert http.status_code == 500
    assert isinstance(http.detail, dict)
    assert http.detail["error_code"] == "LIVE_SMOKE_DB_ERROR"
    assert http.detail["status"] == "FAILED"
    assert http.detail["broker_order_status"] == "NOT_SUBMITTED"
    assert http.detail["order_submitted"] is False
    assert http.detail["create_order_calls"] == 0


def test_controlled_confirm_no_submitted_audit_on_db_error() -> None:
    session = MagicMock()
    audits: list[str] = []

    def capture_audit(*_a, **kw):
        audits.append(str(kw.get("event_type") or ""))

    with (
        patch.object(
            ControlledLiveOrderSmokeService,
            "_load_owned_upbit",
            return_value=SimpleNamespace(
                user_broker_account_id=1380,
                user_id=1,
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
            side_effect=UpbitLiveSmokeError(
                "LIVE_SMOKE_DB_ERROR",
                http_status=500,
                order_submitted=False,
                create_order_calls=0,
                run_id="uvs-db",
                status_code="FAILED",
            ),
        ),
    ):
        RPF.return_value.run_for_uba.return_value = {
            "manual_order_allowed": True,
            "checked_at": "2099-01-01T00:00:00+00:00",
        }
        with pytest.raises(ControlledLiveOrderSmokeError) as ei:
            ControlledLiveOrderSmokeService(session).confirm(
                uba_id=1380,
                user_id=1,
                actor="u",
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
        assert ei.value.code == "LIVE_SMOKE_DB_ERROR"
        assert LIVE_ORDER_SMOKE_SUBMITTED not in audits
        assert LIVE_ORDER_SMOKE_FAILED in audits


def test_queued_success_requires_order_and_outbox() -> None:
    session = _session()
    run = _run()
    queued = OrderExecutionResult(
        allowed=True,
        reason_code="QUEUED",
        order_id=42,
        outbox_id=99,
        status_code="PENDING",
        client_order_id="c1",
        quantity=Decimal("0.0001"),
        price=Decimal("100"),
    )
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
            return_value=queued,
        ),
        patch.object(UpbitLiveSmokeService, "_create_run", return_value=run),
        patch.object(UpbitLiveSmokeService, "_pause_uba_scope"),
        patch.object(
            UpbitLiveSmokeService,
            "_transition",
            side_effect=lambda r, st, actor: setattr(r, "status_code", st)
            or setattr(r, "internal_status", st),
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
            actor="tester",
            arm_token="tok",
            execute_live=True,
            confirmation_text=CONFIRMATION_TEXT,
            skip_live_network=True,
        )
        assert result["order_id"] == 42
        assert result["outbox_id"] == 99
        assert result["reason_code"] == "QUEUED"
        assert result["status"] == "QUEUED"
        assert result["create_order_calls"] == 0
        markers = result["pipeline_markers"]
        assert "BEFORE_ORDER_EXECUTION_SUBMIT" in markers
        assert "AFTER_ORDER_EXECUTION_SUBMIT" in markers
        assert "SUBMIT_ALLOWED" in markers
        assert "AFTER_QUEUE_COMMIT" in markers


def test_business_rejection_still_409() -> None:
    from tests.test_live_smoke_risk_rejection import (
        test_smoke_execute_risk_rejection_no_adapter_no_unknown,
    )

    test_smoke_execute_risk_rejection_no_adapter_no_unknown()
