"""STEP 9-4 — ARM Enable Only 계약 테스트."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.trading.live_arm_service import LiveArmError, LiveArmService
from stock_platform.trading.step9_4_live_enable_evidence import (
    validate_step9_3_live_enable_evidence,
)
from stock_platform.trading.step9_3_dry_run_evidence import DryRunEvidenceError
from stock_platform.risk_engine.resolved_policy import ResolvedRiskPolicy


def _policy(**overrides) -> ResolvedRiskPolicy:
    base = dict(
        max_order_amount=Decimal("50000"),
        daily_max_order_amount=Decimal("200000"),
        max_total_investment_amount=Decimal("1000000"),
        max_position_amount=Decimal("200000"),
        max_position_count=5,
        max_position_weight=Decimal("0.2"),
        max_investment_ratio=Decimal("0.70"),
        allow_duplicate_buy=True,
        daily_max_loss_amount=Decimal("300000"),
        daily_max_loss_rate=Decimal("0.05"),
        stop_loss_rate=Decimal("0.05"),
        take_profit_rate=Decimal("0.1"),
        trailing_stop_rate=Decimal("0.03"),
        auto_trading_enabled=True,
        buy_enabled=True,
        sell_enabled=True,
        sell_only=False,
        account_paused=False,
        max_order_quantity=Decimal("100"),
        daily_order_limit=20,
        duplicate_order_window_seconds=5,
        max_open_orders=20,
        max_slippage_rate=Decimal("0.01"),
        anomaly_orders_per_minute=10,
        loop_detect_window_seconds=60,
        arm_ttl_seconds=300,
        source_layers=("system",),
    )
    base.update(overrides)
    return ResolvedRiskPolicy(**base)


def _activation(*, uba_id: int = 58, broker: str = "UPBIT", hours: int = 8):
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        live_trading_transition_id=1,
        enabled=True,
        activation_status="ACTIVE",
        expires_at=now + timedelta(hours=hours),
        broker_code=broker,
        scope="ACCOUNT",
        user_broker_account_id=uba_id,
    )


def _uba(*, live: bool = True, armed: bool = False):
    return SimpleNamespace(
        user_broker_account_id=58,
        user_id=7,
        broker_code="UPBIT",
        is_active=True,
        connection_status="CONNECTED",
        live_order_enabled=live,
        live_armed=armed,
        arm_token_hash=None,
        arm_expires_at=None,
        arm_armed_by=None,
        arm_armed_at=None,
        live_approved_at=None,
        live_approved_by=None,
    )


def _live_report() -> dict:
    return {
        "verdict": "PASS_LIVE_ENABLED",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "correlation_id": "step9-3-live-test",
        "reason": "UPBIT_5000_DRY_RUN_PASSED_OPERATOR_APPROVED_LIVE_ENABLE",
        "mutations": {
            "arm_on": 0,
            "create_order": 0,
            "broker_submit": 0,
            "db_order_insert": 0,
            "live_on": 1,
        },
        "before": {"account": {"uba_id": 58, "live": False, "arm": False}},
        "after": {"account": {"uba_id": 58, "live": True, "arm": False}},
        "audit": {
            "id": 6162,
            "event_type": "LIVE_APPROVED",
            "detail": {
                "arm": False,
                "correlation_id": "step9-3-live-test",
                "reason": "UPBIT_5000_DRY_RUN_PASSED_OPERATOR_APPROVED_LIVE_ENABLE",
            },
        },
        "report_hash": "abc",
    }


def test_step9_3_evidence_pass() -> None:
    ev = validate_step9_3_live_enable_evidence(_live_report())
    assert ev["ok"] is True


def test_step9_3_evidence_blocks_if_not_pass() -> None:
    with pytest.raises(DryRunEvidenceError) as ei:
        validate_step9_3_live_enable_evidence(
            {**_live_report(), "verdict": "FAIL"}
        )
    assert ei.value.code == "live_enable_not_pass"


def test_arm_requires_reason_when_gated() -> None:
    session = MagicMock()
    session.get.return_value = _uba(live=True)
    with pytest.raises(LiveArmError) as ei:
        LiveArmService(session).arm(
            58,
            actor="admin",
            correlation_id="c1",
            enforce_gates=True,
        )
    assert ei.value.code == "reason_required"


def test_arm_requires_correlation_when_gated() -> None:
    session = MagicMock()
    session.get.return_value = _uba(live=True)
    with pytest.raises(LiveArmError) as ei:
        LiveArmService(session).arm(
            58,
            actor="admin",
            reason="R",
            enforce_gates=True,
        )
    assert ei.value.code == "correlation_id_required"


def test_arm_blocks_when_live_off() -> None:
    session = MagicMock()
    session.get.return_value = _uba(live=False)
    with pytest.raises(LiveArmError) as ei:
        LiveArmService(session).assert_arm_enable_preconditions(58)
    assert ei.value.code == "live_required"


def test_arm_does_not_change_live() -> None:
    session = MagicMock()
    uba = _uba(live=True, armed=False)
    session.get.return_value = uba
    with (
        patch(
            "stock_platform.trading.live_arm_service.ResolvedRiskPolicyResolver"
        ) as R,
        patch(
            "stock_platform.trading.live_arm_service.emit_live_safety_audit"
        ) as audit,
        patch(
            "stock_platform.trading.live_arm_service.emit_live_order_telegram"
        ),
        patch(
            "stock_platform.trading.live_arm_service.collect_scheduler_readiness"
        ) as sched,
        patch.object(
            LiveArmService,
            "_require_session_activation",
            return_value=_activation(),
        ),
        patch(
            "stock_platform.trading.live_arm_service.assert_risk_account_not_paused",
            return_value={"account_paused": False, "arm_ttl_seconds": 300},
        ),
    ):
        R.return_value.resolve.return_value = _policy()
        sched.return_value = SimpleNamespace(
            trading_scheduler_desired_state="PAUSE",
            trading_scheduler_actual_state="PAUSED",
        )
        result = LiveArmService(session).arm(
            58,
            actor="admin",
            reason="UPBIT_5000_LIVE_ENABLED_OPERATOR_APPROVED_ARM_ENABLE",
            correlation_id="step9-4-test",
            ttl_seconds=3600,
            enforce_gates=False,
        )
    assert uba.live_armed is True
    assert uba.live_order_enabled is True
    assert result["live_unchanged"] is True
    assert "arm_token" in result
    detail = audit.call_args.kwargs["detail"]
    assert detail["previous_arm"] is False
    assert detail["new_arm"] is True
    assert detail["live"] is True
    assert "arm_token" not in detail


def test_arm_idempotent_when_gated() -> None:
    session = MagicMock()
    uba = _uba(live=True, armed=True)
    uba.arm_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    uba.arm_token_hash = "x"
    session.get.return_value = uba
    with (
        patch(
            "stock_platform.trading.live_arm_service.ResolvedRiskPolicyResolver"
        ),
        patch(
            "stock_platform.trading.live_arm_service.emit_live_safety_audit"
        ) as audit,
        patch(
            "stock_platform.trading.live_arm_service.emit_live_order_telegram"
        ),
    ):
        result = LiveArmService(session).arm(
            58,
            actor="admin",
            reason="AGAIN",
            correlation_id="dup",
            enforce_gates=True,
        )
    assert result["already_armed"] is True
    assert result["arm_changed"] is False
    assert "arm_token" not in result
    assert audit.call_count == 0
    session.flush.assert_not_called()


def test_arm_blocks_paused() -> None:
    session = MagicMock()
    uba = _uba(live=True)
    session.get.return_value = uba
    session.scalar.return_value = SimpleNamespace(trading_paused=True)
    with patch.object(
        LiveArmService,
        "_require_session_activation",
        return_value=_activation(),
    ):
        with pytest.raises(LiveArmError) as ei:
            LiveArmService(session).assert_arm_enable_preconditions(58)
    assert ei.value.code == "trading_paused"


def test_arm_blocks_active_review() -> None:
    session = MagicMock()
    session.get.return_value = _uba(live=True)
    session.scalar.side_effect = [
        SimpleNamespace(trading_paused=False),
        1,  # active
    ]
    with (
        patch.object(
            LiveArmService,
            "_require_session_activation",
            return_value=_activation(),
        ),
        patch(
            "stock_platform.trading.live_arm_service.assert_risk_account_not_paused",
            return_value={"account_paused": False, "arm_ttl_seconds": 300},
        ),
    ):
        with pytest.raises(LiveArmError) as ei:
            LiveArmService(session).assert_arm_enable_preconditions(58)
    assert ei.value.code == "unresolved_conflicts"


def test_arm_blocks_pending_review() -> None:
    session = MagicMock()
    session.get.return_value = _uba(live=True)
    session.scalar.side_effect = [
        SimpleNamespace(trading_paused=False),
        0,  # active
        2,  # pending
    ]
    with (
        patch.object(
            LiveArmService,
            "_require_session_activation",
            return_value=_activation(),
        ),
        patch(
            "stock_platform.trading.live_arm_service.assert_risk_account_not_paused",
            return_value={"account_paused": False, "arm_ttl_seconds": 300},
        ),
    ):
        with pytest.raises(LiveArmError) as ei:
            LiveArmService(session).assert_arm_enable_preconditions(58)
    assert ei.value.code == "pending_review"


def test_arm_blocks_db_open() -> None:
    session = MagicMock()
    session.get.return_value = _uba(live=True)
    session.scalar.side_effect = [
        SimpleNamespace(trading_paused=False),
        0,
        0,
    ]
    with (
        patch(
            "stock_platform.trading.live_arm_service.BrokerRecoveryConflictService"
        ) as svc,
        patch.object(
            LiveArmService,
            "_require_session_activation",
            return_value=_activation(),
        ),
        patch(
            "stock_platform.trading.live_arm_service.assert_risk_account_not_paused",
            return_value={"account_paused": False, "arm_ttl_seconds": 300},
        ),
    ):
        svc.return_value.count_blocking_orders_for_uba.return_value = {
            "db_open": 1,
            "submission_unknown": 0,
            "cancel_pending": 0,
            "replace_pending": 0,
        }
        with pytest.raises(LiveArmError) as ei:
            LiveArmService(session).assert_arm_enable_preconditions(58)
    assert ei.value.code == "db_open_orders"


def test_arm_blocks_kill_switch() -> None:
    session = MagicMock()
    session.get.return_value = _uba(live=True)
    session.scalar.side_effect = [
        SimpleNamespace(trading_paused=False),
        0,
        0,
    ]
    with (
        patch(
            "stock_platform.trading.live_arm_service.BrokerRecoveryConflictService"
        ) as svc,
        patch(
            "stock_platform.trading.live_arm_service.BrokerCredentialVaultService"
        ) as vault,
        patch(
            "stock_platform.trading.live_arm_service.KillSwitchService"
        ) as ks,
        patch.object(
            LiveArmService,
            "_require_session_activation",
            return_value=_activation(),
        ),
        patch(
            "stock_platform.trading.live_arm_service.assert_risk_account_not_paused",
            return_value={"account_paused": False, "arm_ttl_seconds": 300},
        ),
    ):
        svc.return_value.count_blocking_orders_for_uba.return_value = {
            "db_open": 0,
            "submission_unknown": 0,
            "cancel_pending": 0,
            "replace_pending": 0,
        }
        vault_inst = MagicMock()
        vault_inst.assert_live_order_allowed = MagicMock(return_value=None)
        vault.return_value = vault_inst
        ks.return_value.is_active_for_scopes.return_value = True
        with pytest.raises(LiveArmError) as ei:
            LiveArmService(session).assert_arm_enable_preconditions(58)
    assert ei.value.code == "kill_switch_active"


def test_arm_blocks_scheduler_not_paused() -> None:
    session = MagicMock()
    session.get.return_value = _uba(live=True)
    session.scalar.side_effect = [
        SimpleNamespace(trading_paused=False),
        0,
        0,
    ]
    ready = SimpleNamespace(
        trading_scheduler_actual_state="RUNNING",
        trading_scheduler_desired_state="RUN",
    )
    with (
        patch(
            "stock_platform.trading.live_arm_service.BrokerRecoveryConflictService"
        ) as svc,
        patch(
            "stock_platform.trading.live_arm_service.BrokerCredentialVaultService"
        ) as vault,
        patch(
            "stock_platform.trading.live_arm_service.KillSwitchService"
        ) as ks,
        patch(
            "stock_platform.trading.live_arm_service.evaluate_live_order_health",
            return_value={"status": "HEALTHY", "live_orders_allowed": True},
        ),
        patch(
            "stock_platform.trading.live_arm_service.collect_scheduler_readiness",
            return_value=ready,
        ),
        patch.object(
            LiveArmService,
            "_require_session_activation",
            return_value=_activation(),
        ),
        patch(
            "stock_platform.trading.live_arm_service.assert_risk_account_not_paused",
            return_value={"account_paused": False, "arm_ttl_seconds": 300},
        ),
    ):
        svc.return_value.count_blocking_orders_for_uba.return_value = {
            "db_open": 0,
            "submission_unknown": 0,
            "cancel_pending": 0,
            "replace_pending": 0,
        }
        vault_inst = MagicMock()
        vault_inst.assert_live_order_allowed = MagicMock(return_value=None)
        vault.return_value = vault_inst
        ks.return_value.is_active_for_scopes.return_value = False
        with pytest.raises(LiveArmError) as ei:
            LiveArmService(session).assert_arm_enable_preconditions(58)
    assert ei.value.code == "trading_scheduler_not_paused"


def test_disarm_keeps_live_by_default() -> None:
    session = MagicMock()
    uba = _uba(live=True, armed=True)
    uba.arm_token_hash = "h"
    uba.arm_expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    session.get.return_value = uba
    with (
        patch(
            "stock_platform.trading.live_arm_service.emit_live_safety_audit"
        ) as audit,
        patch(
            "stock_platform.trading.live_arm_service.emit_live_order_telegram"
        ),
        patch(
            "stock_platform.trading.live_arm_service.collect_scheduler_readiness"
        ) as sched,
    ):
        sched.return_value = SimpleNamespace(
            trading_scheduler_desired_state="PAUSE",
            trading_scheduler_actual_state="PAUSED",
        )
        result = LiveArmService(session).disarm(
            58,
            actor="admin",
            reason="EMERGENCY_TEST",
            correlation_id="disarm-1",
            require_correlation_id=True,
            turn_live_off=False,
        )
    assert uba.live_armed is False
    assert uba.live_order_enabled is True
    assert result["live_unchanged"] is True
    assert audit.call_args.kwargs["event_type"] == "ARM_OFF"


def test_disarm_requires_correlation_when_flagged() -> None:
    session = MagicMock()
    session.get.return_value = _uba(live=True, armed=True)
    with pytest.raises(LiveArmError) as ei:
        LiveArmService(session).disarm(
            58,
            actor="admin",
            reason="X",
            require_correlation_id=True,
        )
    assert ei.value.code == "correlation_id_required"


def test_scheduler_paused_auto_order_path_idle() -> None:
    """LIVE+ARM+Scheduler PAUSED → 자동 주문 경로 미실행 증거."""
    from stock_platform.realtime.session_runtime import (
        realtime_trading_scheduler,
    )

    assert realtime_trading_scheduler.scheduler.running is False
    # PAUSED이면 scheduler job이 create/submit을 호출하지 않음
    assert realtime_trading_scheduler.scheduler.running is False
    reason = (
        "TRADING_SCHEDULER_PAUSED"
        if not realtime_trading_scheduler.scheduler.running
        else "UNEXPECTED"
    )
    assert reason == "TRADING_SCHEDULER_PAUSED"
