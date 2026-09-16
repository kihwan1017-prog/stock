"""ARM renew / open-order gate hardening + exit submit suppression — focused tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.broker.open_order_gate_classification import (
    OPEN_CLASS_AMBIGUOUS,
    OPEN_CLASS_AUTO_ENTRY_BUY,
    OPEN_CLASS_MANUAL,
    evaluate_open_order_gate_for_uba,
)
from stock_platform.broker.recovery_conflict_service import (
    BrokerRecoveryConflictService,
)
from stock_platform.position.exit_submission_suppression import (
    reset_exit_suppression_for_uba,
    should_suppress_exit_submit,
)
from stock_platform.trading.live_arm_service import LiveArmError, LiveArmService


def _order(
    *,
    oid: int,
    side: str,
    source: str = "AUTO",
    uuid: str | None = "uuid-1",
    strategy_id: int = 17483,
):
    return SimpleNamespace(
        order_id=oid,
        symbol="KRW-ENSO",
        side_code=side,
        status_code="ACCEPTED",
        broker_order_id=uuid,
        strategy_id=strategy_id,
        strategy_deployment_id=None,
        metadata_payload={"order_source": source, "environment": "LIVE"},
        broker_code="UPBIT",
        user_broker_account_id=1380,
    )


def test_arm_renew_allows_known_auto_entry_buy_open() -> None:
    session = MagicMock()
    auto_buy = _order(oid=2279, side="BUY")
    session.scalars = MagicMock(return_value=[auto_buy])
    session.get = MagicMock(
        return_value=SimpleNamespace(broker_code="UPBIT", user_broker_account_id=1380)
    )
    session.scalar = MagicMock(side_effect=[0, 0, 0])

    with patch(
        "stock_platform.broker.credential_adapter_factory.build_upbit_adapter_for_uba"
    ) as ad:
        ad.return_value._client.get_order.return_value = {"state": "wait"}
        summary = evaluate_open_order_gate_for_uba(
            session,
            1380,
            gate_mode="arm_renew",
            verify_upbit_broker_state=True,
        )
    assert summary.db_open_blocking == 0
    assert summary.auto_entry_buy_excluded == 1
    assert summary.class_counts[OPEN_CLASS_AUTO_ENTRY_BUY] == 1


def test_arm_renew_blocks_ambiguous_auto_buy() -> None:
    session = MagicMock()
    ambiguous = _order(oid=1, side="BUY", uuid=None)
    session.scalars = MagicMock(return_value=[ambiguous])
    session.get = MagicMock(
        return_value=SimpleNamespace(broker_code="UPBIT", user_broker_account_id=1380)
    )
    session.scalar = MagicMock(side_effect=[0, 0, 0])

    summary = evaluate_open_order_gate_for_uba(
        session,
        1380,
        gate_mode="arm_renew",
        verify_upbit_broker_state=True,
    )
    assert summary.db_open_blocking == 1
    assert summary.class_counts[OPEN_CLASS_AMBIGUOUS] == 1


def test_initial_arm_strict_blocks_auto_entry_buy() -> None:
    session = MagicMock()
    auto_buy = _order(oid=2279, side="BUY")
    session.scalars = MagicMock(return_value=[auto_buy])
    session.get = MagicMock(
        return_value=SimpleNamespace(broker_code="UPBIT", user_broker_account_id=1380)
    )
    session.scalar = MagicMock(side_effect=[0, 0, 0])

    summary = evaluate_open_order_gate_for_uba(
        session,
        1380,
        gate_mode="initial_arm",
        verify_upbit_broker_state=False,
    )
    assert summary.db_open_blocking == 1


def test_restore_gate_allows_broker_confirmed_auto_entry_buy() -> None:
    """lease restore LIVE ON은 ARM force_renew와 대칭 — wait AUTO ENTRY BUY 허용."""

    session = MagicMock()
    auto_buy = _order(oid=3337, side="BUY", uuid="f4349578-89b3-4ce8-97a6-3426afd407b8")
    session.scalars = MagicMock(return_value=[auto_buy])
    session.get = MagicMock(
        return_value=SimpleNamespace(broker_code="UPBIT", user_broker_account_id=1380)
    )
    session.scalar = MagicMock(side_effect=[0, 0, 0])

    with patch(
        "stock_platform.broker.credential_adapter_factory.build_upbit_adapter_for_uba"
    ) as ad:
        ad.return_value._client.get_order.return_value = {"state": "wait"}
        summary = evaluate_open_order_gate_for_uba(
            session,
            1380,
            gate_mode="restore",
            verify_upbit_broker_state=True,
        )
    assert summary.db_open_blocking == 0
    assert summary.auto_entry_buy_excluded == 1
    assert summary.orders[0].blocks_restore is False
    assert summary.orders[0].blocks_initial_arm is True


def test_restore_gate_blocks_manual_open() -> None:
    session = MagicMock()
    # strategy_id 없이 MANUAL ownership이 유지되도록
    manual = _order(oid=99, side="BUY", source="MANUAL", strategy_id=None, uuid="manual-uuid")
    manual.strategy_deployment_id = None
    manual.metadata_payload = {"order_source": "MANUAL", "environment": "LIVE"}
    session.scalars = MagicMock(return_value=[manual])
    session.get = MagicMock(
        return_value=SimpleNamespace(broker_code="UPBIT", user_broker_account_id=1380)
    )
    session.scalar = MagicMock(side_effect=[0, 0, 0])

    with patch(
        "stock_platform.broker.credential_adapter_factory.build_upbit_adapter_for_uba"
    ) as ad:
        ad.return_value._client.get_order.return_value = {"state": "wait"}
        summary = evaluate_open_order_gate_for_uba(
            session,
            1380,
            gate_mode="restore",
            verify_upbit_broker_state=True,
        )
    assert summary.class_counts.get("MANUAL_OPEN", 0) == 1
    assert summary.db_open_blocking == 1
    assert summary.auto_entry_buy_excluded == 0


def test_recovery_conflict_service_restore_uses_restore_gate_mode() -> None:
    session = MagicMock()
    with patch(
        "stock_platform.broker.open_order_gate_classification.evaluate_open_order_gate_for_uba"
    ) as ev:
        ev.return_value = SimpleNamespace(
            blocking_dict=lambda: {
                "db_open": 0,
                "submission_unknown": 0,
                "cancel_pending": 0,
                "replace_pending": 0,
                "auto_protective_open_excluded": 0,
                "auto_entry_buy_excluded": 1,
            },
            class_counts={OPEN_CLASS_AUTO_ENTRY_BUY: 1},
            arm_renew_block_reason=None,
        )
        out = BrokerRecoveryConflictService(session).count_blocking_orders_for_uba(
            1380,
            exclude_auto_protective_exits=True,
            exclude_known_auto_entry_buys=True,
            verify_upbit_broker_for_entry_buys=True,
        )
    assert out["db_open"] == 0
    assert ev.call_args.kwargs.get("gate_mode") == "restore"
    assert ev.call_args.kwargs.get("verify_upbit_broker_state") is True


def test_live_enable_restore_flags_exclude_known_entry_buy() -> None:
    """Unattended restore LIVE ON — protective+known entry flags가 count에 전달되는지."""

    from stock_platform.trading.live_order_approval_service import (
        LiveOrderApprovalService,
    )

    session = MagicMock()
    uba = SimpleNamespace(
        user_broker_account_id=1380,
        user_id=61,
        is_active=True,
        live_armed=False,
        broker_code="UPBIT",
        live_order_enabled=False,
    )
    session.get = MagicMock(return_value=uba)
    session.scalar = MagicMock(return_value=0)
    seen: dict = {}

    with (
        patch(
            "stock_platform.operation.runtime_process_stability.assert_stable_runtime_for_real_trading"
        ),
        patch(
            "stock_platform.trading.live_order_approval_service.assert_uba_connection_ready"
        ),
        patch(
            "stock_platform.trading.live_order_approval_service.assert_recovery_ready",
            return_value={"recovery_status": "SUCCESS"},
        ),
        patch(
            "stock_platform.trading.live_order_approval_service.assert_risk_account_not_paused",
            return_value={"account_paused": False},
        ),
        patch(
            "stock_platform.trading.live_order_approval_service.BrokerRecoveryConflictService"
        ) as brc,
        patch(
            "stock_platform.trading.live_order_approval_service.BrokerCredentialVaultService"
        ) as vault,
        patch(
            "stock_platform.trading.live_order_approval_service.KillSwitchService"
        ) as ks,
        patch(
            "stock_platform.trading.live_order_approval_service.evaluate_live_order_health",
            return_value={"live_orders_allowed": True, "status": "HEALTHY"},
        ),
        patch(
            "stock_platform.trading.live_order_approval_service.collect_scheduler_readiness",
            return_value=SimpleNamespace(
                trading_scheduler_actual_state="PAUSED",
                trading_scheduler_desired_state="PAUSE",
            ),
        ),
    ):
        def _count(uid, **kwargs):  # noqa: ANN001
            seen.update(kwargs)
            return {
                "db_open": 0,
                "submission_unknown": 0,
                "cancel_pending": 0,
                "replace_pending": 0,
            }

        brc.return_value.count_blocking_orders_for_uba = _count
        vault.return_value.assert_live_order_allowed = MagicMock()
        ks.return_value.is_active_for_scopes = MagicMock(return_value=False)
        LiveOrderApprovalService(session).assert_live_enable_preconditions(
            1380,
            allow_auto_protective_open_orders=True,
            allow_known_auto_entry_buys=True,
        )
    assert seen.get("exclude_auto_protective_exits") is True
    assert seen.get("exclude_known_auto_entry_buys") is True
    assert seen.get("verify_upbit_broker_for_entry_buys") is True


def test_recovery_conflict_service_arm_renew_entry_exclude() -> None:
    session = MagicMock()
    with patch(
        "stock_platform.broker.open_order_gate_classification.evaluate_open_order_gate_for_uba"
    ) as ev:
        ev.return_value = SimpleNamespace(
            blocking_dict=lambda: {
                "db_open": 0,
                "submission_unknown": 0,
                "cancel_pending": 0,
                "replace_pending": 0,
                "auto_protective_open_excluded": 0,
                "auto_entry_buy_excluded": 1,
            },
            class_counts={OPEN_CLASS_AUTO_ENTRY_BUY: 1},
            arm_renew_block_reason=None,
        )
        out = BrokerRecoveryConflictService(session).count_blocking_orders_for_uba(
            1380,
            exclude_auto_protective_exits=True,
            exclude_known_auto_entry_buys=True,
            verify_upbit_broker_for_entry_buys=True,
        )
    assert out["db_open"] == 0
    assert out["auto_entry_buy_excluded"] == 1


def test_initial_arm_activation_no_entry_exclude_flag() -> None:
    session, _uba, svc, cred, _, _ = _arm_precond_ctx()
    with (
        patch.object(
            svc,
            "_require_session_activation",
            return_value=SimpleNamespace(
                expires_at=datetime.now(timezone.utc) + timedelta(hours=5),
                live_trading_transition_id=1,
            ),
        ),
        patch("stock_platform.trading.live_arm_service.assert_uba_connection_ready"),
        patch(
            "stock_platform.trading.live_arm_service.assert_recovery_ready",
            return_value={"recovery_status": "SUCCESS", "trading_paused": False},
        ),
        patch(
            "stock_platform.trading.live_arm_service.assert_risk_account_not_paused",
            return_value={"account_paused": False},
        ),
        patch(
            "stock_platform.trading.live_arm_service.BrokerRecoveryConflictService"
        ) as brc,
        patch(
            "stock_platform.trading.live_arm_service.BrokerCredentialVaultService",
            return_value=cred,
        ),
        patch("stock_platform.trading.live_arm_service.KillSwitchService") as ks,
        patch(
            "stock_platform.trading.live_arm_service.evaluate_live_order_health",
            return_value={"live_orders_allowed": True, "status": "HEALTHY"},
        ),
        patch(
            "stock_platform.trading.live_arm_service.collect_scheduler_readiness"
        ) as sch,
    ):
        brc.return_value.count_blocking_orders_for_uba.return_value = {
            "db_open": 1,
            "submission_unknown": 0,
            "cancel_pending": 0,
            "replace_pending": 0,
        }
        ks.return_value.is_active_for_scopes.return_value = False
        sch.return_value = SimpleNamespace(
            trading_scheduler_actual_state="PAUSED",
            trading_scheduler_desired_state="PAUSE",
        )
        with pytest.raises(LiveArmError) as exc:
            svc.assert_arm_enable_preconditions(
                1380,
                allow_auto_protective_open_orders=False,
                allow_known_auto_entry_buys=False,
            )
    assert exc.value.code == "db_open_orders"


def test_force_renew_passes_known_auto_entry_flag() -> None:
    session = MagicMock()
    uba = SimpleNamespace(
        user_broker_account_id=1380,
        user_id=61,
        broker_code="UPBIT",
        is_active=True,
        live_order_enabled=True,
        live_armed=True,
        arm_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        arm_token_hash="x",
        arm_armed_by="t",
        arm_armed_at=datetime.now(timezone.utc),
    )
    session.get = MagicMock(return_value=uba)
    svc = LiveArmService(session)
    seen: dict = {}

    def _assert(uid, **kwargs):  # noqa: ANN001
        seen.update(kwargs)
        return {"blocking": {}}

    svc.assert_arm_enable_preconditions = _assert  # type: ignore[method-assign]
    svc._clamp_arm_ttl = MagicMock(  # type: ignore[method-assign]
        return_value=(
            3600,
            datetime.now(timezone.utc) + timedelta(hours=1),
            SimpleNamespace(live_trading_transition_id=1, expires_at=None),
        )
    )
    with patch(
        "stock_platform.trading.live_arm_service.ResolvedRiskPolicyResolver"
    ) as pol:
        pol.return_value.resolve.return_value = SimpleNamespace(
            arm_ttl_seconds=3600
        )
        with patch(
            "stock_platform.trading.live_arm_service.emit_live_safety_audit"
        ):
            svc.arm(
                1380,
                actor="SYSTEM_UNATTENDED",
                ttl_seconds=3600,
                reason="UNATTENDED_ARM_RENEWAL",
                correlation_id="unatt-6",
                enforce_gates=True,
                force_renew=True,
                allow_auto_protective_open_orders=True,
            )
    assert seen.get("allow_known_auto_entry_buys") is True


def _arm_precond_ctx(scheduler_actual: str = "PAUSED", desired: str = "PAUSE"):
    session = MagicMock()
    session.scalar.return_value = 0
    uba = SimpleNamespace(
        user_broker_account_id=1380,
        user_id=61,
        broker_code="UPBIT",
        is_active=True,
        live_order_enabled=True,
        live_armed=True,
        arm_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    session.get.return_value = uba
    svc = LiveArmService(session)
    cred = MagicMock()
    cred.assert_live_order_allowed = MagicMock()
    return session, uba, svc, cred, scheduler_actual, desired


def test_exit_suppression_first_allowed_then_blocked() -> None:
    reset_exit_suppression_for_uba(1380)
    now = datetime.now(timezone.utc)
    exp = now + timedelta(hours=1)
    kwargs = dict(
        user_broker_account_id=1380,
        symbol="KRW-ENSO",
        binding_id=238,
        exit_reason="TRAILING_STOP",
        blocker_code="LIVE_ORDER_DISABLED",
        live_order_enabled=False,
        live_armed=False,
        arm_expires_at=exp,
    )
    first = should_suppress_exit_submit(**kwargs)
    assert first.suppress is False
    second = should_suppress_exit_submit(**kwargs)
    assert second.suppress is True

    kwargs["live_order_enabled"] = True
    kwargs["live_armed"] = True
    third = should_suppress_exit_submit(**kwargs)
    assert third.suppress is False


def test_history_85_incident_model_arm_renew_with_entry_buy() -> None:
    session = MagicMock()
    auto_buy = _order(oid=2279, side="BUY")
    session.scalars = MagicMock(return_value=[auto_buy])
    session.get = MagicMock(
        return_value=SimpleNamespace(broker_code="UPBIT", user_broker_account_id=1380)
    )
    session.scalar = MagicMock(side_effect=[0, 0, 0])

    with patch(
        "stock_platform.broker.credential_adapter_factory.build_upbit_adapter_for_uba"
    ) as ad:
        ad.return_value._client.get_order.return_value = {
            "state": "wait",
            "remaining_volume": "7.98",
        }
        summary = evaluate_open_order_gate_for_uba(
            session,
            1380,
            gate_mode="arm_renew",
            verify_upbit_broker_state=True,
        )
    assert summary.db_open_blocking == 0
    assert summary.auto_entry_buy_excluded == 1


def test_kiwoom_auto_entry_buy_renew_isolated_from_upbit_verify() -> None:
    """KIWOOM — UPBIT broker API 없이 UUID 있는 AUTO BUY는 renew 허용."""
    session = MagicMock()
    auto_buy = _order(oid=3001, side="BUY")
    auto_buy.broker_code = "KIWOOM"
    session.scalars = MagicMock(return_value=[auto_buy])
    session.get = MagicMock(
        return_value=SimpleNamespace(broker_code="KIWOOM", user_broker_account_id=9001)
    )
    session.scalar = MagicMock(side_effect=[0, 0, 0])

    with patch(
        "stock_platform.broker.credential_adapter_factory.build_upbit_adapter_for_uba"
    ) as ad:
        summary = evaluate_open_order_gate_for_uba(
            session,
            9001,
            gate_mode="arm_renew",
            verify_upbit_broker_state=True,
        )
    ad.assert_not_called()
    assert summary.db_open_blocking == 0
    assert summary.auto_entry_buy_excluded == 1
    assert summary.broker_code == "KIWOOM"


def test_paper_broker_skips_upbit_remote_verify() -> None:
    """PAPER — LIVE ARM renew gate가 UPBIT API를 호출하지 않음."""
    session = MagicMock()
    auto_buy = _order(oid=4001, side="BUY")
    auto_buy.broker_code = "PAPER"
    session.scalars = MagicMock(return_value=[auto_buy])
    session.get = MagicMock(
        return_value=SimpleNamespace(broker_code="PAPER", user_broker_account_id=5001)
    )
    session.scalar = MagicMock(side_effect=[0, 0, 0])

    with patch(
        "stock_platform.broker.credential_adapter_factory.build_upbit_adapter_for_uba"
    ) as ad:
        summary = evaluate_open_order_gate_for_uba(
            session,
            5001,
            gate_mode="arm_renew",
            verify_upbit_broker_state=True,
        )
    ad.assert_not_called()
    assert summary.broker_code == "PAPER"


def test_restore_mode_still_blocks_known_auto_entry_buy() -> None:
    """만료 ARM restore — known AUTO entry BUY도 여전히 blocking."""
    session = MagicMock()
    auto_buy = _order(oid=2279, side="BUY")
    session.scalars = MagicMock(return_value=[auto_buy])
    session.get = MagicMock(
        return_value=SimpleNamespace(broker_code="UPBIT", user_broker_account_id=1380)
    )
    session.scalar = MagicMock(side_effect=[0, 0, 0])

    summary = evaluate_open_order_gate_for_uba(
        session,
        1380,
        gate_mode="restore",
        verify_upbit_broker_state=False,
    )
    assert summary.db_open_blocking == 1


def test_auto_exit_sell_excluded_manual_still_blocks() -> None:
    session = MagicMock()
    auto_sell = _order(oid=99, side="SELL", source="AUTO")
    auto_sell.metadata_payload = {
        "order_source": "AUTO",
        "environment": "LIVE",
        "signal_reason": "MA_DEAD_CROSS",
    }
    manual = _order(oid=100, side="BUY", source="MANUAL", strategy_id=None)
    manual.metadata_payload = {"order_source": "MANUAL", "environment": "LIVE"}
    session.scalars = MagicMock(return_value=[auto_sell, manual])
    session.get = MagicMock(
        return_value=SimpleNamespace(broker_code="UPBIT", user_broker_account_id=1380)
    )
    session.scalar = MagicMock(side_effect=[0, 0, 0])

    summary = evaluate_open_order_gate_for_uba(
        session,
        1380,
        gate_mode="arm_renew",
        verify_upbit_broker_state=False,
    )
    assert summary.auto_protective_excluded == 1
    assert summary.db_open_blocking == 1
    assert summary.class_counts[OPEN_CLASS_MANUAL] == 1
