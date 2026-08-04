"""LIVE Smoke Risk 거절 — failure_code 정규화 / 500 방지."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from stock_platform.api.v1.user_live_order_smoke import _map_error
from stock_platform.order.execution_service import OrderExecutionService
from stock_platform.trading.controlled_live_order_smoke_service import (
    ControlledLiveOrderSmokeError,
    ControlledLiveOrderSmokeService,
)
from stock_platform.trading.failure_code_normalize import (
    FAILURE_CODE_MAX_LEN,
    classify_risk_blocked_reason,
    normalize_failure_code,
)
from stock_platform.trading.upbit_live_smoke_constants import (
    CONFIRMATION_TEXT,
    LiveValidationRunStatus,
)
from stock_platform.trading.upbit_live_smoke_service import (
    UpbitLiveSmokeError,
    UpbitLiveSmokeService,
)


LONG_RISK = (
    "Projected investment ratio exceeds limit; "
    "Daily loss limit reached; "
    "Projected symbol position exceeds amount limit"
)


def test_normalize_failure_code_rejects_sentences() -> None:
    code = normalize_failure_code(LONG_RISK, fallback="RISK_ENGINE_BLOCKED")
    assert code == "RISK_ENGINE_BLOCKED"
    assert len(code) <= FAILURE_CODE_MAX_LEN


def test_classify_compound_risk_keeps_details() -> None:
    code, details, summary = classify_risk_blocked_reason(LONG_RISK)
    assert code == "RISK_ENGINE_BLOCKED"
    assert len(code) <= 80
    assert len(details) >= 3
    assert "Projected investment ratio exceeds limit" in details
    assert "Daily loss limit reached" in details
    assert "Projected symbol position" in details[2]
    assert "investment ratio" in summary.lower()


def test_classify_single_risk_detail_code() -> None:
    code, details, _ = classify_risk_blocked_reason(
        "Daily loss limit reached"
    )
    assert code == "RISK_DAILY_LOSS_LIMIT_REACHED"
    assert details == ["Daily loss limit reached"]


def test_order_execution_blocks_with_short_risk_code() -> None:
    code, details, summary = classify_risk_blocked_reason(LONG_RISK)
    blocked = OrderExecutionService._blocked(code, message=summary)
    assert blocked.allowed is False
    assert blocked.reason_code == "RISK_ENGINE_BLOCKED"
    assert len(blocked.reason_code) <= 80
    assert blocked.position_plan is not None
    assert "Daily loss" in str(blocked.position_plan.get("message"))
    assert len(details) >= 3


def test_smoke_execute_risk_rejection_no_adapter_no_unknown() -> None:
    session = MagicMock()
    session.is_active = True
    run = SimpleNamespace(
        run_id="run-risk-1",
        status_code=LiveValidationRunStatus.EXECUTION_REQUESTED.value,
        internal_status=LiveValidationRunStatus.EXECUTION_REQUESTED.value,
        detail={},
        failure_code=None,
        failure_summary=None,
        user_id=1,
        broker_order_status="NOT_SUBMITTED",
        order_id=None,
        execute_live=True,
        updated_at=None,
        completed_at=None,
    )
    preflight = SimpleNamespace(
        live_execution_ready=True,
        blockers=[],
        live_blockers=[],
        quantity="0.0001",
        limit_price="100",
        estimated_amount="5000",
        preflight_id="pf-1",
        user_id=1,
        to_dict=lambda: {"preflight_id": "pf-1", "quantity": "0.0001"},
        request_fingerprint="fp",
    )
    uba = SimpleNamespace(
        user_broker_account_id=1380,
        user_id=1,
        live_order_enabled=True,
    )
    session.get.return_value = uba

    blocked = OrderExecutionService._blocked(
        "RISK_ENGINE_BLOCKED",
        message=LONG_RISK,
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
            return_value=blocked,
        ) as submit,
        patch.object(
            UpbitLiveSmokeService,
            "_create_run",
            return_value=run,
        ),
        patch.object(UpbitLiveSmokeService, "_pause_uba_scope"),
        patch.object(
            UpbitLiveSmokeService,
            "_transition",
            side_effect=lambda r, st, actor: setattr(r, "status_code", st)
            or setattr(r, "internal_status", st),
        ),
    ):
        Track.return_value.blocks_new_order.return_value = False
        PF.return_value.run.return_value = preflight
        svc = UpbitLiveSmokeService(session)
        with pytest.raises(UpbitLiveSmokeError) as ei:
            svc.execute(
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
        assert err.code == "RISK_ENGINE_BLOCKED"
        assert err.http_status == 409
        assert err.create_order_calls == 0
        assert err.order_submitted is False
        assert len(err.details) >= 3
        assert run.status_code == LiveValidationRunStatus.REJECTED.value
        assert run.failure_code == "RISK_ENGINE_BLOCKED"
        assert len(run.failure_code) <= 80
        assert run.failure_summary and "Daily loss" in run.failure_summary
        submit.assert_called_once()


def test_rejected_to_unknown_forbidden() -> None:
    session = MagicMock()
    run = SimpleNamespace(
        status_code=LiveValidationRunStatus.REJECTED.value,
        detail={},
        updated_at=None,
        internal_status=LiveValidationRunStatus.REJECTED.value,
    )
    with pytest.raises(UpbitLiveSmokeError, match="INVALID_TRANSITION"):
        UpbitLiveSmokeService(session)._transition(
            run,  # type: ignore[arg-type]
            LiveValidationRunStatus.UNKNOWN.value,
            actor="t",
        )


def test_finalize_protect_skips_flush_when_session_inactive() -> None:
    session = MagicMock()
    session.is_active = False
    session.rollback = MagicMock()
    run = SimpleNamespace(
        run_id="r",
        status_code=LiveValidationRunStatus.REJECTED.value,
        internal_status=LiveValidationRunStatus.REJECTED.value,
        broker_order_status="NOT_SUBMITTED",
        user_id=1,
        order_id=None,
        execute_live=True,
        completed_at=None,
        detail={},
    )
    with (
        patch(
            "stock_platform.trading.upbit_live_smoke_service.LiveArmService"
        ) as ARM,
        patch(
            "stock_platform.trading.upbit_live_smoke_service.emit_live_safety_audit"
        ) as audit,
        patch(
            "stock_platform.trading.upbit_live_smoke_service.emit_live_order_telegram"
        ),
        patch.object(UpbitLiveSmokeService, "_pause_uba_scope"),
    ):
        UpbitLiveSmokeService(session)._finalize_protect(
            user_broker_account_id=7,
            run=run,  # type: ignore[arg-type]
            actor="t",
        )
        ARM.return_value.disarm.assert_called_once()
        session.flush.assert_not_called()
        audit.assert_not_called()


def test_map_error_risk_returns_409_structured() -> None:
    exc = ControlledLiveOrderSmokeError(
        "RISK_ENGINE_BLOCKED",
        message="Risk policy blocked this order.",
        details=[
            "Projected investment ratio exceeds limit",
            "Daily loss limit reached",
            "Projected symbol position exceeds amount limit",
        ],
        http_status=409,
        order_submitted=False,
        create_order_calls=0,
        status_code="REJECTED",
        run_id="run-1",
    )
    http = _map_error(exc)
    assert isinstance(http, HTTPException)
    assert http.status_code == 409
    assert isinstance(http.detail, dict)
    assert http.detail["error_code"] == "RISK_ENGINE_BLOCKED"
    assert http.detail["create_order_calls"] == 0
    assert http.detail["order_submitted"] is False
    assert http.detail["broker_order_id"] is None
    assert len(http.detail["details"]) >= 3


def test_confirm_propagates_risk_error() -> None:
    session = MagicMock()
    session.get.return_value = SimpleNamespace(
        user_broker_account_id=1380,
        user_id=1,
        broker_code="UPBIT",
        deleted_at=None,
    )
    svc = ControlledLiveOrderSmokeService(session)
    with (
        patch(
            "stock_platform.trading.controlled_live_order_smoke_service.emit_live_safety_audit"
        ),
        patch(
            "stock_platform.trading.controlled_live_order_smoke_service.RuntimePreflightService"
        ) as RPS,
        patch.object(
            ControlledLiveOrderSmokeService,
            "_assert_order_test_fresh",
        ),
        patch(
            "stock_platform.trading.controlled_live_order_smoke_service.UpbitLiveSmokeService.execute",
            side_effect=UpbitLiveSmokeError(
                "RISK_ENGINE_BLOCKED",
                message="Risk policy blocked this order.",
                details=["Daily loss limit reached"],
                http_status=409,
                create_order_calls=0,
                status_code="REJECTED",
            ),
        ) as execute,
    ):
        RPS.return_value.run_for_uba.return_value = {
            "manual_order_allowed": True,
            "checked_at": "2099-01-01T00:00:00+00:00",
        }
        with pytest.raises(ControlledLiveOrderSmokeError) as ei:
            svc.confirm(
                uba_id=1380,
                user_id=1,
                actor="t",
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
        assert ei.value.code == "RISK_ENGINE_BLOCKED"
        assert ei.value.http_status == 409
        execute.assert_called_once()
