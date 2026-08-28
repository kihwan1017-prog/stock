"""UPBIT unattended stack recovery + WAITING restore-epoch safety."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.operation.upbit_full_market.waiting_revalidation_gate import (
    REASON_EXIT_MONITOR_NOT_RUNNING,
    REASON_MARKET_FEED_NOT_FRESH,
    REASON_STALE_PRE_RESTORE_WAITING,
    evaluate_waiting_buy_revalidation_gate,
)
from stock_platform.trading.upbit_execution_restore_epoch import (
    UpbitExecutionRestoreEpoch,
)


def test_restore_epoch_blocks_pre_restore_waiting() -> None:
    epoch = UpbitExecutionRestoreEpoch()
    t0 = datetime(2026, 8, 26, 8, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 8, 26, 10, 0, tzinfo=timezone.utc)
    epoch.mark_outage("LIVE_ARM_EXPIRED")
    epoch._state.outage_started_at = t0
    epoch.mark_restored(actor="TEST")
    epoch._state.restored_at = t1
    epoch._state.outage_active = False

    pre = t0 + timedelta(hours=1)  # before restore
    assert epoch.is_pre_or_during_outage_waiting(pre) is True
    fresh = t1 + timedelta(minutes=5)
    assert epoch.is_pre_or_during_outage_waiting(fresh) is False


def test_restore_epoch_blocks_during_active_outage() -> None:
    epoch = UpbitExecutionRestoreEpoch()
    epoch.mark_outage("TEST_OUTAGE")
    assert epoch.is_pre_or_during_outage_waiting(
        datetime.now(timezone.utc)
    ) is True


def test_cold_start_blocks_waiting_before_process_start() -> None:
    """restart 직후 mark_restored 전이라도 기동 이전 WAITING은 차단."""

    epoch = UpbitExecutionRestoreEpoch()
    before = epoch._process_started_at - timedelta(hours=1)
    after = epoch._process_started_at + timedelta(minutes=1)
    assert epoch.is_pre_or_during_outage_waiting(before) is True
    assert epoch.is_pre_or_during_outage_waiting(after) is False


def test_waiting_gate_blocks_exit_monitor_stopped() -> None:
    session = MagicMock()
    with (
        patch(
            "stock_platform.operation.upbit_full_market.waiting_revalidation_gate._exit_monitor_running",
            return_value=(False, {"status": "STOPPED"}),
        ),
        patch(
            "stock_platform.operation.upbit_full_market.waiting_revalidation_gate._feed_real_fresh",
            return_value=(True, {"status": "REAL_FRESH"}),
        ),
    ):
        result = evaluate_waiting_buy_revalidation_gate(
            session,
            user_broker_account_id=1380,
            symbol="KRW-LINK",
            order_source="AUTO",
            broker_code="UPBIT",
            side="BUY",
            waiting_updated_at=datetime.now(timezone.utc),
        )
    assert result["allowed"] is False
    assert result["reason"] == REASON_EXIT_MONITOR_NOT_RUNNING


def test_waiting_gate_blocks_feed_not_fresh() -> None:
    session = MagicMock()
    with (
        patch(
            "stock_platform.operation.upbit_full_market.waiting_revalidation_gate._exit_monitor_running",
            return_value=(True, {"status": "RUNNING"}),
        ),
        patch(
            "stock_platform.operation.upbit_full_market.waiting_revalidation_gate._feed_real_fresh",
            return_value=(False, {"status": "DISCONNECTED"}),
        ),
    ):
        result = evaluate_waiting_buy_revalidation_gate(
            session,
            user_broker_account_id=1380,
            symbol="KRW-LINK",
            order_source="AUTO",
            broker_code="UPBIT",
            side="BUY",
            waiting_updated_at=datetime.now(timezone.utc),
        )
    assert result["allowed"] is False
    assert result["reason"] == REASON_MARKET_FEED_NOT_FRESH


def test_waiting_gate_blocks_stale_pre_restore() -> None:
    session = MagicMock()
    from stock_platform.trading.upbit_execution_restore_epoch import (
        upbit_execution_restore_epoch,
    )

    restored_at = datetime.now(timezone.utc)
    waiting_at = restored_at - timedelta(hours=2)
    with (
        patch(
            "stock_platform.operation.upbit_full_market.waiting_revalidation_gate._exit_monitor_running",
            return_value=(True, {"status": "RUNNING"}),
        ),
        patch(
            "stock_platform.operation.upbit_full_market.waiting_revalidation_gate._feed_real_fresh",
            return_value=(True, {"status": "REAL_FRESH"}),
        ),
        patch.object(
            upbit_execution_restore_epoch,
            "is_pre_or_during_outage_waiting",
            return_value=True,
        ),
        patch.object(
            upbit_execution_restore_epoch,
            "snapshot",
            return_value={"restored_at": restored_at.isoformat()},
        ),
    ):
        result = evaluate_waiting_buy_revalidation_gate(
            session,
            user_broker_account_id=1380,
            symbol="KRW-LINK",
            order_source="AUTO",
            broker_code="UPBIT",
            side="BUY",
            waiting_updated_at=waiting_at,
        )
    assert result["allowed"] is False
    assert result["reason"] == REASON_STALE_PRE_RESTORE_WAITING


def test_waiting_gate_allows_fresh_after_restore() -> None:
    session = MagicMock()
    from stock_platform.trading.upbit_execution_restore_epoch import (
        upbit_execution_restore_epoch,
    )

    restored_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    waiting_at = datetime.now(timezone.utc)
    with (
        patch(
            "stock_platform.operation.upbit_full_market.waiting_revalidation_gate._exit_monitor_running",
            return_value=(True, {"status": "RUNNING"}),
        ),
        patch(
            "stock_platform.operation.upbit_full_market.waiting_revalidation_gate._feed_real_fresh",
            return_value=(True, {"status": "REAL_FRESH"}),
        ),
        patch.object(
            upbit_execution_restore_epoch,
            "is_pre_or_during_outage_waiting",
            return_value=False,
        ),
        patch.object(
            upbit_execution_restore_epoch,
            "snapshot",
            return_value={"restored_at": restored_at.isoformat()},
        ),
    ):
        result = evaluate_waiting_buy_revalidation_gate(
            session,
            user_broker_account_id=1380,
            symbol="KRW-NEW",
            order_source="AUTO",
            broker_code="UPBIT",
            side="BUY",
            waiting_updated_at=waiting_at,
        )
    assert result["allowed"] is True


def test_waiting_gate_skips_sell() -> None:
    session = MagicMock()
    result = evaluate_waiting_buy_revalidation_gate(
        session,
        user_broker_account_id=1380,
        symbol="KRW-SUI",
        order_source="AUTO",
        broker_code="UPBIT",
        side="SELL",
        is_risk_reducing=True,
    )
    assert result["allowed"] is True


@pytest.mark.asyncio
async def test_stack_restore_idempotent_when_already_running() -> None:
    from stock_platform.trading.upbit_unattended_stack_restore import (
        restore_upbit_trading_stack,
    )

    session = MagicMock()
    with (
        patch(
            "stock_platform.trading.upbit_unattended_stack_restore.evaluate_stack_restore_gates",
            return_value={
                "ok": True,
                "blockers": [],
                "checks": {
                    "portfolio": {
                        "portfolio_enabled": True,
                        "strategy_id": 17483,
                    }
                },
            },
        ),
        patch(
            "stock_platform.order.live_outbox_worker_runtime.live_outbox_worker_runtime"
        ) as worker,
        patch(
            "stock_platform.strategy_deployment.runtime_manager.dynamic_strategy_runtime_manager"
        ) as mgr,
        patch(
            "stock_platform.trading.upbit_24x7_control.evaluate_runtime_start_gates",
            return_value={"ok": True, "blockers": []},
        ),
        patch(
            "stock_platform.trading.upbit_24x7_control.runtime_status_for_uba",
            return_value={"status": "RUNNING"},
        ),
        patch(
            "stock_platform.trading.upbit_24x7_control.exit_monitor_status",
            return_value={"status": "RUNNING"},
        ),
        patch(
            "stock_platform.operation.upbit_full_market.portfolio_runtime_sync.ensure_protective_quote_feed",
            return_value={"ok": True},
        ),
        patch(
            "stock_platform.realtime.upbit_quote_feed_restore.ensure_upbit_quote_feed_from_hub",
            return_value={
                "started": True,
                "already_running": True,
                "symbols": ["KRW-SUI"],
            },
        ),
        patch(
            "stock_platform.realtime.market_data_hub.get_realtime_market_data_hub"
        ) as hub_factory,
        patch(
            "stock_platform.realtime.runtime.realtime_execution_runner_manager"
        ) as runner_mgr,
        patch(
            "stock_platform.operation.upbit_full_market.portfolio_entry_signal.ensure_portfolio_entry_evaluator_for_uba",
            return_value={"ok": True},
        ),
    ):
        from stock_platform.strategy_deployment.runtime_scope import (
            RuntimeLifecycleStatus,
        )

        worker.status.return_value = {"enabled": True, "running": True}
        entry = MagicMock()
        entry.status = RuntimeLifecycleStatus.RUNNING
        entry.scope.broker_code = "UPBIT"
        entry.scope.scope_key = "k"
        mgr.list_entries.return_value = [entry]
        hub = MagicMock()
        hub.status.return_value = {"dispatch_running": True}
        hub_factory.return_value = hub
        runner = MagicMock()
        runner.status.return_value = {"running": True}
        runner_mgr.get.return_value = runner

        first = await restore_upbit_trading_stack(
            session, user_broker_account_id=1380, actor="TEST"
        )
        second = await restore_upbit_trading_stack(
            session, user_broker_account_id=1380, actor="TEST"
        )

    assert first.get("restored") is True
    assert second.get("restored") is True
    assert (first.get("detail") or {}).get("worker", {}).get(
        "idempotent"
    ) is True
    worker.start.assert_not_called()

def test_restore_epoch_equal_timestamp_not_stale_after_nudge() -> None:
    """mark_restored 와 동일 시각 updated_at 은 restore-boundary 로 통과."""

    epoch = UpbitExecutionRestoreEpoch()
    epoch.mark_restored(actor="TEST")
    restored = epoch._state.restored_at
    assert restored is not None
    assert epoch.is_pre_or_during_outage_waiting(restored) is False
    assert epoch.is_pre_or_during_outage_waiting(
        restored - timedelta(microseconds=1)
    ) is True
    assert epoch.is_pre_or_during_outage_waiting(
        restored + timedelta(microseconds=1)
    ) is False


def test_force_waiting_nudge_strictly_after_restored_at() -> None:
    """nudge updated_at 은 restored_at 보다 엄격히 이후여야 한다."""

    from stock_platform.operation.upbit_full_market.waiting_lifecycle import (
        force_waiting_revalidation_after_restore,
    )
    from stock_platform.trading.upbit_execution_restore_epoch import (
        upbit_execution_restore_epoch,
    )

    upbit_execution_restore_epoch.mark_restored(actor="TEST_NUDGE")
    restored = upbit_execution_restore_epoch._state.restored_at
    assert restored is not None

    slot = MagicMock()
    slot.status = "WAITING_SIGNAL"
    slot.clamp_reasons = {"capital_clamps": []}
    slot.updated_at = restored - timedelta(hours=1)

    session = MagicMock()
    session.scalars.return_value.all.return_value = [slot]

    # _now() 가 restored_at 과 동일해도 epsilon 으로 밀어냄
    with patch(
        "stock_platform.operation.upbit_full_market.waiting_lifecycle._now",
        return_value=restored,
    ):
        out = force_waiting_revalidation_after_restore(
            session,
            user_broker_account_id=1380,
            actor="TEST_NUDGE",
        )

    assert out["ok"] is True
    assert out["nudged_waiting_slots"] == 1
    assert slot.updated_at > restored
    assert upbit_execution_restore_epoch.is_pre_or_during_outage_waiting(
        slot.updated_at
    ) is False


def test_waiting_gate_allows_equal_restore_boundary(monkeypatch) -> None:
    """복구 boundary 동일 시각 WAITING 은 STALE_PRE_RESTORE 가 아님."""

    from stock_platform.operation.upbit_full_market import waiting_revalidation_gate as g
    from stock_platform.trading.upbit_execution_restore_epoch import (
        upbit_execution_restore_epoch,
    )

    monkeypatch.setattr(g, "_exit_monitor_running", lambda: (True, {"status": "RUNNING"}))
    monkeypatch.setattr(
        g, "_feed_real_fresh", lambda session, uba_id: (True, {"status": "REAL_FRESH"})
    )

    upbit_execution_restore_epoch.mark_restored(actor="TEST_EQ")
    restored = upbit_execution_restore_epoch._state.restored_at
    assert restored is not None

    result = evaluate_waiting_buy_revalidation_gate(
        MagicMock(),
        user_broker_account_id=1380,
        symbol="KRW-CHIP",
        order_source="AUTO",
        broker_code="UPBIT",
        side="BUY",
        waiting_updated_at=restored,
    )
    assert result["allowed"] is True
    assert result.get("reason") != REASON_STALE_PRE_RESTORE_WAITING


def test_waiting_gate_rejects_strict_pre_restore(monkeypatch) -> None:
    from stock_platform.operation.upbit_full_market import waiting_revalidation_gate as g
    from stock_platform.trading.upbit_execution_restore_epoch import (
        upbit_execution_restore_epoch,
    )

    monkeypatch.setattr(g, "_exit_monitor_running", lambda: (True, {"status": "RUNNING"}))
    monkeypatch.setattr(
        g, "_feed_real_fresh", lambda session, uba_id: (True, {"status": "REAL_FRESH"})
    )

    upbit_execution_restore_epoch.mark_restored(actor="TEST_PRE")
    restored = upbit_execution_restore_epoch._state.restored_at
    assert restored is not None
    pre = restored - timedelta(seconds=1)

    result = evaluate_waiting_buy_revalidation_gate(
        MagicMock(),
        user_broker_account_id=1380,
        symbol="KRW-XPL",
        order_source="AUTO",
        broker_code="UPBIT",
        side="BUY",
        waiting_updated_at=pre,
    )
    assert result["allowed"] is False
    assert result["reason"] == REASON_STALE_PRE_RESTORE_WAITING
