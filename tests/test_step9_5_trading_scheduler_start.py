"""STEP 9-5 — Trading Scheduler Start Only 계약 테스트."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.realtime.session_models import TradingSessionPhase
from stock_platform.realtime.session_service import (
    RealtimeTradingSessionService,
)
from stock_platform.trading.trading_scheduler_control import (
    get_trading_scheduler_desired_state,
    reset_trading_scheduler_control_for_tests,
    set_trading_scheduler_desired_state,
)
from stock_platform.trading.trading_scheduler_control_service import (
    TradingSchedulerControlError,
    TradingSchedulerControlService,
)


@pytest.fixture(autouse=True)
def _reset_control():
    reset_trading_scheduler_control_for_tests()
    yield
    reset_trading_scheduler_control_for_tests()


def test_desired_state_defaults_pause() -> None:
    assert get_trading_scheduler_desired_state() == "PAUSE"


def test_set_desired_run_and_pause() -> None:
    set_trading_scheduler_desired_state("RUN", actor="a", reason="r")
    assert get_trading_scheduler_desired_state() == "RUN"
    set_trading_scheduler_desired_state("PAUSE", actor="a", reason="p")
    assert get_trading_scheduler_desired_state() == "PAUSE"


@pytest.mark.asyncio
async def test_market_open_does_not_auto_start_runners() -> None:
    session = MagicMock()
    cal = MagicMock()
    cal.evaluate.return_value = SimpleNamespace(
        is_trading_day=True,
        live_allowed=True,
        reason_code="OK",
    )
    with (
        patch(
            "stock_platform.realtime.session_service.TradingCalendarService",
            return_value=cal,
        ),
        patch(
            "stock_platform.realtime.session_service.realtime_execution_runner"
        ) as ex,
        patch(
            "stock_platform.realtime.session_service.realtime_strategy_runner"
        ) as st,
    ):
        ex.status.return_value = {"running": False}
        st.status.return_value = {"running": False}
        # TradingCalendarService is constructed with repo — patch repository path instead
        svc = RealtimeTradingSessionService.__new__(
            RealtimeTradingSessionService
        )
        svc._calendar = cal
        result = await svc.execute(
            phase=TradingSessionPhase.MARKET_OPEN, exchange_code="KRX"
        )
    assert result.executed is True
    # Runner 자동 기동 금지 — message 문구는 환경 설정에 따라 달라질 수 있음
    assert ex.start.call_count == 0
    assert st.start.call_count == 0
    assert "started': False" in result.message or "auto" in result.message.lower()
    ex.start.assert_not_called()
    st.start.assert_not_called()


def test_start_requires_reason() -> None:
    session = MagicMock()
    with pytest.raises(TradingSchedulerControlError) as ei:
        TradingSchedulerControlService(session).start(
            actor="admin",
            reason="",
            correlation_id="c1",
            user_broker_account_id=58,
            enforce_gates=False,
        )
    assert ei.value.code == "reason_required"


def test_start_requires_correlation() -> None:
    session = MagicMock()
    with pytest.raises(TradingSchedulerControlError) as ei:
        TradingSchedulerControlService(session).start(
            actor="admin",
            reason="R",
            correlation_id="",
            user_broker_account_id=58,
            enforce_gates=False,
        )
    assert ei.value.code == "correlation_id_required"


def test_start_blocks_live_off() -> None:
    session = MagicMock()
    uba = SimpleNamespace(
        is_active=True,
        connection_status="CONNECTED",
        live_order_enabled=False,
        live_armed=True,
        arm_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        user_id=7,
        broker_code="UPBIT",
        user_broker_account_id=58,
    )
    session.get.return_value = uba
    with pytest.raises(TradingSchedulerControlError) as ei:
        TradingSchedulerControlService(session).assert_start_preconditions(
            user_broker_account_id=58
        )
    assert ei.value.code == "live_required"


def test_start_blocks_arm_off() -> None:
    session = MagicMock()
    uba = SimpleNamespace(
        is_active=True,
        connection_status="CONNECTED",
        live_order_enabled=True,
        live_armed=False,
        arm_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        user_id=7,
        broker_code="UPBIT",
        user_broker_account_id=58,
    )
    session.get.return_value = uba
    with pytest.raises(TradingSchedulerControlError) as ei:
        TradingSchedulerControlService(session).assert_start_preconditions(
            user_broker_account_id=58
        )
    assert ei.value.code == "arm_required"


def test_start_blocks_arm_ttl_insufficient() -> None:
    session = MagicMock()
    uba = SimpleNamespace(
        is_active=True,
        connection_status="CONNECTED",
        live_order_enabled=True,
        live_armed=True,
        arm_expires_at=datetime.now(timezone.utc) + timedelta(seconds=30),
        user_id=7,
        broker_code="UPBIT",
        user_broker_account_id=58,
    )
    session.get.return_value = uba
    session.scalar.return_value = SimpleNamespace(
        trading_paused=False, recovery_status="SUCCESS"
    )
    with patch(
        "stock_platform.trading.runtime_control_gates.ResolvedRiskPolicyResolver"
    ) as risk:
        risk.return_value.resolve.return_value = SimpleNamespace(
            account_paused=False,
            max_order_amount=5000,
            max_order_quantity=1,
            daily_order_limit=10,
            daily_max_loss_amount=10000,
            arm_ttl_seconds=300,
        )
        with pytest.raises(TradingSchedulerControlError) as ei:
            TradingSchedulerControlService(session).assert_start_preconditions(
                user_broker_account_id=58, min_arm_remaining_seconds=120
            )
    assert ei.value.code == "arm_ttl_insufficient"


def test_start_idempotent_already_running() -> None:
    session = MagicMock()
    with (
        patch(
            "stock_platform.trading.trading_scheduler_control_service.realtime_trading_scheduler"
        ) as sched,
        patch(
            "stock_platform.trading.trading_scheduler_control_service.realtime_strategy_runner"
        ) as st,
        patch(
            "stock_platform.trading.trading_scheduler_control_service.realtime_execution_runner"
        ) as ex,
    ):
        sched.scheduler.running = True
        sched.scheduler.get_jobs.return_value = []
        st.status.return_value = {"running": False}
        ex.status.return_value = {"running": False}
        result = TradingSchedulerControlService(session).start(
            actor="admin",
            reason="AGAIN",
            correlation_id="dup",
            user_broker_account_id=58,
            enforce_gates=False,
        )
    assert result["already_running"] is True
    assert result["scheduler_changed"] is False


def test_pause_requires_reason() -> None:
    session = MagicMock()
    with pytest.raises(TradingSchedulerControlError) as ei:
        TradingSchedulerControlService(session).pause(
            actor="admin",
            reason="",
            correlation_id="c",
        )
    assert ei.value.code == "reason_required"


def test_start_allows_active_strategy_links_when_runtime_idle(
    monkeypatch,
) -> None:
    """자동매매 준비용 active link는 Scheduler RUN을 막지 않는다."""

    session = MagicMock()
    uba = SimpleNamespace(
        is_active=True,
        connection_status="CONNECTED",
        live_order_enabled=True,
        live_armed=True,
        arm_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        user_id=61,
        broker_code="UPBIT",
        user_broker_account_id=1380,
    )
    session.get.return_value = uba
    session.scalar.side_effect = [
        SimpleNamespace(trading_paused=False, recovery_status="SUCCESS"),
        0,  # unresolved conflicts
        0,  # pending review
    ]

    svc = TradingSchedulerControlService(session)
    monkeypatch.setattr(
        svc,
        "_strategy_runtime_counts",
        lambda uba_id: {"active_runtime": 0, "active_links": 1},
    )

    with (
        patch(
            "stock_platform.trading.trading_scheduler_control_service.assert_uba_connection_ready"
        ),
        patch(
            "stock_platform.trading.trading_scheduler_control_service.assert_recovery_ready"
        ),
        patch(
            "stock_platform.trading.trading_scheduler_control_service.assert_risk_account_not_paused"
        ),
        patch(
            "stock_platform.trading.trading_scheduler_control_service.BrokerRecoveryConflictService"
        ) as conflict_cls,
        patch(
            "stock_platform.trading.trading_scheduler_control_service.BrokerCredentialVaultService"
        ) as vault_cls,
        patch(
            "stock_platform.trading.trading_scheduler_control_service.KillSwitchService"
        ) as ks_cls,
        patch(
            "stock_platform.trading.trading_scheduler_control_service.evaluate_live_order_health",
            return_value={"live_orders_allowed": True, "status": "HEALTHY"},
        ),
        patch(
            "stock_platform.trading.trading_scheduler_control_service.realtime_strategy_runner"
        ) as st,
        patch(
            "stock_platform.trading.trading_scheduler_control_service.realtime_execution_runner"
        ) as ex,
        patch(
            "stock_platform.trading.runtime_control_gates.ResolvedRiskPolicyResolver"
        ) as risk,
    ):
        conflict_cls.return_value.count_blocking_orders_for_uba.return_value = {
            "db_open": 0,
            "submission_unknown": 0,
            "cancel_pending": 0,
            "replace_pending": 0,
        }
        vault = MagicMock()
        vault.assert_live_order_allowed = MagicMock(return_value=None)
        vault_cls.return_value = vault
        ks = MagicMock()
        ks.is_active_for_scopes.return_value = False
        ks.GLOBAL_SCOPE = "GLOBAL"
        ks_cls.return_value = ks
        ks_cls.GLOBAL_SCOPE = "GLOBAL"
        st.status.return_value = {"active_scopes": 0}
        ex.status.return_value = {"running": False}
        risk.return_value.resolve.return_value = SimpleNamespace(
            account_paused=False
        )

        # scalar for conflicts uses MagicMock — override with controlled values
        session.scalar = MagicMock(
            side_effect=[
                0,  # active conflicts
                0,  # pending
            ]
        )
        gate = svc.assert_start_preconditions(user_broker_account_id=1380)

    assert gate["strategy"]["active_links"] == 1
    assert gate["strategy"]["active_runtime"] == 0
    assert gate["active_links_allowed"] is True


def test_start_blocks_active_strategy_runtime(monkeypatch) -> None:
    session = MagicMock()
    uba = SimpleNamespace(
        is_active=True,
        connection_status="CONNECTED",
        live_order_enabled=True,
        live_armed=True,
        arm_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        user_id=61,
        broker_code="UPBIT",
        user_broker_account_id=1380,
    )
    session.get.return_value = uba
    svc = TradingSchedulerControlService(session)
    monkeypatch.setattr(
        svc,
        "_strategy_runtime_counts",
        lambda uba_id: {"active_runtime": 1, "active_links": 1},
    )

    with (
        patch(
            "stock_platform.trading.trading_scheduler_control_service.assert_uba_connection_ready"
        ),
        patch(
            "stock_platform.trading.trading_scheduler_control_service.assert_recovery_ready"
        ),
        patch(
            "stock_platform.trading.trading_scheduler_control_service.assert_risk_account_not_paused"
        ),
        patch(
            "stock_platform.trading.trading_scheduler_control_service.BrokerRecoveryConflictService"
        ) as conflict_cls,
        patch(
            "stock_platform.trading.trading_scheduler_control_service.BrokerCredentialVaultService"
        ) as vault_cls,
        patch(
            "stock_platform.trading.trading_scheduler_control_service.KillSwitchService"
        ) as ks_cls,
        patch(
            "stock_platform.trading.trading_scheduler_control_service.evaluate_live_order_health",
            return_value={"live_orders_allowed": True, "status": "HEALTHY"},
        ),
        patch(
            "stock_platform.trading.trading_scheduler_control_service.realtime_strategy_runner"
        ) as st,
        patch(
            "stock_platform.trading.trading_scheduler_control_service.realtime_execution_runner"
        ) as ex,
    ):
        conflict_cls.return_value.count_blocking_orders_for_uba.return_value = {
            "db_open": 0,
            "submission_unknown": 0,
            "cancel_pending": 0,
            "replace_pending": 0,
        }
        vault = MagicMock()
        vault.assert_live_order_allowed = MagicMock(return_value=None)
        vault_cls.return_value = vault
        ks = MagicMock()
        ks.is_active_for_scopes.return_value = False
        ks.GLOBAL_SCOPE = "GLOBAL"
        ks_cls.return_value = ks
        ks_cls.GLOBAL_SCOPE = "GLOBAL"
        st.status.return_value = {"active_scopes": 0}
        ex.status.return_value = {"running": False}
        session.scalar = MagicMock(side_effect=[0, 0])
        with pytest.raises(TradingSchedulerControlError) as ei:
            svc.assert_start_preconditions(user_broker_account_id=1380)
    assert ei.value.code == "strategy_runtime_active"


def test_collect_readiness_uses_desired_control() -> None:
    from stock_platform.trading.upbit_scheduler_readiness import (
        collect_scheduler_readiness,
    )

    set_trading_scheduler_desired_state("RUN", actor="t", reason="t")
    with patch(
        "stock_platform.realtime.session_runtime.realtime_trading_scheduler"
    ) as sched:
        sched.scheduler.running = True
        snap = collect_scheduler_readiness()
    assert snap.trading_scheduler_desired_state == "RUN"
    assert snap.trading_scheduler_actual_state == "RUNNING"
