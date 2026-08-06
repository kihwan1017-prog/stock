"""STEP 9-3 — LIVE Enable Only 계약 테스트."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.order.live_safety_pipeline import LiveOrderSafetyPipeline
from stock_platform.risk_engine.resolved_policy import ResolvedRiskPolicy
from stock_platform.trading.live_order_approval_service import (
    LiveOrderApprovalError,
    LiveOrderApprovalService,
)
from stock_platform.trading.step9_3_dry_run_evidence import (
    DryRunEvidenceError,
    validate_step9_2_dry_run_evidence,
)


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


def _uba(*, live: bool = False, armed: bool = False):
    return SimpleNamespace(
        user_broker_account_id=58,
        user_id=7,
        broker_code="UPBIT",
        account_alias="u",
        masked_account_number="***",
        is_active=True,
        live_order_enabled=live,
        live_approved_at=None,
        live_approved_by=None,
        live_armed=armed,
        arm_token_hash=None,
        arm_expires_at=None,
    )


def _dry_report(**overrides) -> dict:
    base = {
        "step": "9-2",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "correlation_id": "step9-2-dry-test",
        "mutations": {
            "live_on": 0,
            "arm_on": 0,
            "create_order": 0,
            "cancel_order": 0,
            "replace_order": 0,
        },
        "precheck": {
            "market_arg": "KRW-BTC",
            "account": {"uba_id": 58},
        },
        "dry_run": {
            "verdict": "PASS_DRY_RUN",
            "market": "KRW-BTC",
            "requested_amount": "5000",
            "deltas": {
                "broker_submit": 0,
                "db_order_insert": 0,
                "actual_order_count": 0,
            },
        },
    }
    base.update(overrides)
    return base


def test_dry_run_evidence_pass() -> None:
    ev = validate_step9_2_dry_run_evidence(_dry_report())
    assert ev["ok"] is True
    assert ev["market"] == "KRW-BTC"


def test_dry_run_evidence_mismatch_blocks() -> None:
    with pytest.raises(DryRunEvidenceError) as ei:
        validate_step9_2_dry_run_evidence(
            _dry_report(
                dry_run={
                    "verdict": "PASS_DRY_RUN",
                    "market": "KRW-ETH",
                    "requested_amount": "5000",
                }
            )
        )
    assert ei.value.code == "dry_run_market_mismatch"


def test_dry_run_missing_blocks() -> None:
    with pytest.raises(DryRunEvidenceError) as ei:
        validate_step9_2_dry_run_evidence(
            {"dry_run": {"verdict": "FAIL"}, "checked_at": datetime.now(timezone.utc).isoformat()}
        )
    assert ei.value.code == "dry_run_not_pass"


def test_live_enable_requires_reason() -> None:
    session = MagicMock()
    session.get.return_value = _uba(live=False)
    with pytest.raises(LiveOrderApprovalError) as ei:
        LiveOrderApprovalService(session).set_live_enabled(
            58,
            enabled=True,
            actor="admin",
            correlation_id="c1",
            enforce_enable_gates=False,
        )
    assert ei.value.code == "reason_required"


def test_live_enable_requires_correlation_id() -> None:
    session = MagicMock()
    session.get.return_value = _uba(live=False)
    with pytest.raises(LiveOrderApprovalError) as ei:
        LiveOrderApprovalService(session).set_live_enabled(
            58,
            enabled=True,
            actor="admin",
            reason="R",
            enforce_enable_gates=False,
        )
    assert ei.value.code == "correlation_id_required"


def test_live_enable_does_not_change_arm() -> None:
    session = MagicMock()
    uba = _uba(live=False, armed=False)
    session.get.return_value = uba
    with (
        patch(
            "stock_platform.trading.live_order_approval_service.ResolvedRiskPolicyResolver"
        ) as resolver,
        patch(
            "stock_platform.trading.live_order_approval_service.emit_live_safety_audit"
        ) as audit,
    ):
        resolver.return_value.resolve.return_value = _policy()
        result = LiveOrderApprovalService(session).set_live_enabled(
            58,
            enabled=True,
            actor="admin",
            reason="UPBIT_5000_DRY_RUN_PASSED_OPERATOR_APPROVED_LIVE_ENABLE",
            correlation_id="step9-3-test",
            enforce_enable_gates=False,
        )
    assert uba.live_order_enabled is True
    assert uba.live_armed is False
    assert result["arm_unchanged"] is True
    assert result["live_changed"] is True
    detail = audit.call_args.kwargs["detail"]
    assert detail["previous_live"] is False
    assert detail["new_live"] is True
    assert detail["arm"] is False
    assert detail["correlation_id"] == "step9-3-test"


def test_live_enable_idempotent_no_duplicate_side_effects() -> None:
    session = MagicMock()
    uba = _uba(live=True, armed=False)
    session.get.return_value = uba
    with (
        patch(
            "stock_platform.trading.live_order_approval_service.ResolvedRiskPolicyResolver"
        ) as resolver,
        patch(
            "stock_platform.trading.live_order_approval_service.emit_live_safety_audit"
        ) as audit,
    ):
        resolver.return_value.resolve.return_value = _policy()
        result = LiveOrderApprovalService(session).set_live_enabled(
            58,
            enabled=True,
            actor="admin",
            reason="AGAIN",
            correlation_id="dup",
            enforce_enable_gates=False,
        )
    assert result["already_enabled"] is True
    assert result["live_changed"] is False
    assert audit.call_count == 0
    session.flush.assert_not_called()


def test_live_enable_blocks_when_paused() -> None:
    session = MagicMock()
    uba = _uba(live=False)
    pause = SimpleNamespace(trading_paused=True)
    session.get.return_value = uba
    session.scalar.return_value = pause
    with pytest.raises(LiveOrderApprovalError) as ei:
        LiveOrderApprovalService(session).assert_live_enable_preconditions(58)
    assert ei.value.code == "trading_paused"


def test_live_enable_blocks_when_arm_on() -> None:
    session = MagicMock()
    session.get.return_value = _uba(live=False, armed=True)
    with pytest.raises(LiveOrderApprovalError) as ei:
        LiveOrderApprovalService(session).assert_live_enable_preconditions(58)
    assert ei.value.code == "arm_must_be_off"


def test_live_on_arm_off_blocks_with_live_not_armed() -> None:
    uba = _uba(live=True, armed=False)
    session = MagicMock()
    session.get.return_value = uba
    session.scalar.side_effect = [0, None, None, 0, 0]
    session.scalars.return_value = []
    with (
        patch(
            "stock_platform.order.live_safety_pipeline.ResolvedRiskPolicyResolver"
        ) as resolver_cls,
        patch(
            "stock_platform.order.live_safety_pipeline.PersistentKillSwitchGuard"
        ) as ks,
    ):
        ks.return_value.require_order_allowed.return_value = None
        resolver_cls.return_value.resolve.return_value = _policy()
        decision = LiveOrderSafetyPipeline(session).evaluate(
            user_id=7,
            user_broker_account_id=58,
            broker_code="UPBIT",
            exchange_code="UPBIT",
            symbol="KRW-BTC",
            side="BUY",
            quantity=Decimal("0"),
            price=Decimal("5000"),
            emit_side_effects=False,
            require_arm=True,
            arm_token=None,
        )
    assert decision.allowed is False
    assert decision.reason_code == "LIVE_NOT_ARMED"


def test_live_enable_blocks_active_review() -> None:
    session = MagicMock()
    uba = _uba(live=False)
    session.get.return_value = uba
    # scalar: pause row, then active count
    session.scalar.side_effect = [
        SimpleNamespace(trading_paused=False),
        2,
    ]
    with pytest.raises(LiveOrderApprovalError) as ei:
        LiveOrderApprovalService(session).assert_live_enable_preconditions(58)
    assert ei.value.code == "unresolved_conflicts"


def test_live_enable_blocks_db_open_orders() -> None:
    session = MagicMock()
    uba = _uba(live=False)
    session.get.return_value = uba
    session.scalar.side_effect = [
        SimpleNamespace(trading_paused=False),
        0,
    ]
    with patch(
        "stock_platform.trading.live_order_approval_service.BrokerRecoveryConflictService"
    ) as svc:
        svc.return_value.count_blocking_orders_for_uba.return_value = {
            "db_open": 1,
            "submission_unknown": 0,
            "cancel_pending": 0,
            "replace_pending": 0,
        }
        with pytest.raises(LiveOrderApprovalError) as ei:
            LiveOrderApprovalService(session).assert_live_enable_preconditions(
                58
            )
    assert ei.value.code == "db_open_orders"


def test_live_enable_blocks_kill_switch() -> None:
    session = MagicMock()
    uba = _uba(live=False)
    session.get.return_value = uba
    session.scalar.side_effect = [
        SimpleNamespace(trading_paused=False),
        0,
    ]
    with (
        patch(
            "stock_platform.trading.live_order_approval_service.BrokerRecoveryConflictService"
        ) as svc,
        patch(
            "stock_platform.trading.live_order_approval_service.BrokerCredentialVaultService"
        ) as vault,
        patch(
            "stock_platform.trading.live_order_approval_service.KillSwitchService"
        ) as ks,
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
        with pytest.raises(LiveOrderApprovalError) as ei:
            LiveOrderApprovalService(session).assert_live_enable_preconditions(
                58
            )
    assert ei.value.code == "kill_switch_active"


def test_live_enable_blocks_unhealthy() -> None:
    session = MagicMock()
    uba = _uba(live=False)
    session.get.return_value = uba
    session.scalar.side_effect = [
        SimpleNamespace(trading_paused=False),
        0,
    ]
    with (
        patch(
            "stock_platform.trading.live_order_approval_service.BrokerRecoveryConflictService"
        ) as svc,
        patch(
            "stock_platform.trading.live_order_approval_service.BrokerCredentialVaultService"
        ) as vault,
        patch(
            "stock_platform.trading.live_order_approval_service.KillSwitchService"
        ) as ks,
        patch(
            "stock_platform.trading.live_order_approval_service.evaluate_live_order_health",
            return_value={"status": "CRITICAL", "live_orders_allowed": False},
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
        with pytest.raises(LiveOrderApprovalError) as ei:
            LiveOrderApprovalService(session).assert_live_enable_preconditions(
                58
            )
    assert ei.value.code == "broker_unhealthy"


def test_live_enable_blocks_scheduler_not_paused() -> None:
    session = MagicMock()
    uba = _uba(live=False)
    session.get.return_value = uba
    session.scalar.side_effect = [
        SimpleNamespace(trading_paused=False),
        0,
    ]
    ready = SimpleNamespace(
        trading_scheduler_actual_state="RUNNING",
        trading_scheduler_desired_state="RUN",
    )
    with (
        patch(
            "stock_platform.trading.live_order_approval_service.BrokerRecoveryConflictService"
        ) as svc,
        patch(
            "stock_platform.trading.live_order_approval_service.BrokerCredentialVaultService"
        ) as vault,
        patch(
            "stock_platform.trading.live_order_approval_service.KillSwitchService"
        ) as ks,
        patch(
            "stock_platform.trading.live_order_approval_service.evaluate_live_order_health",
            return_value={"status": "HEALTHY", "live_orders_allowed": True},
        ),
        patch(
            "stock_platform.trading.live_order_approval_service.collect_scheduler_readiness",
            return_value=ready,
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
        with pytest.raises(LiveOrderApprovalError) as ei:
            LiveOrderApprovalService(session).assert_live_enable_preconditions(
                58
            )
    assert ei.value.code == "trading_scheduler_not_paused"
