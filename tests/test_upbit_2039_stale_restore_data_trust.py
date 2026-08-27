"""Regression: STALE_PRE_RESTORE must not block ENTRY_PENDING persist."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from stock_platform.operation.upbit_full_market.waiting_revalidation_gate import (
    REASON_STALE_PRE_RESTORE_WAITING,
    evaluate_waiting_buy_revalidation_gate,
)
from stock_platform.trading.autotrading_data_trust import (
    QUALITY_DEGRADED,
    QUALITY_INVALID,
    QUALITY_VALID,
    evaluate_data_trust_from_health,
)
from stock_platform.trading.upbit_execution_restore_epoch import (
    UpbitExecutionRestoreEpoch,
)


def test_restore_epoch_none_waiting_not_stale_after_restore() -> None:
    ep = UpbitExecutionRestoreEpoch()
    ep.mark_restored(actor="test")
    assert ep.is_pre_or_during_outage_waiting(None) is False


def test_restore_epoch_outage_blocks_none_waiting() -> None:
    ep = UpbitExecutionRestoreEpoch()
    ep.mark_outage("TEST_OUTAGE")
    assert ep.is_pre_or_during_outage_waiting(None) is True


def test_waiting_gate_skips_restore_when_not_waiting(monkeypatch) -> None:
    from stock_platform.operation.upbit_full_market import waiting_revalidation_gate as g

    monkeypatch.setattr(g, "_exit_monitor_running", lambda: (True, {"status": "RUNNING"}))
    monkeypatch.setattr(
        g, "_feed_real_fresh", lambda session, uba_id: (True, {"status": "REAL_FRESH"})
    )
    monkeypatch.setattr(g, "load_waiting_slot_updated_at", lambda *a, **k: None)

    ep = UpbitExecutionRestoreEpoch()
    ep.mark_restored(actor="test")
    monkeypatch.setattr(
        "stock_platform.trading.upbit_execution_restore_epoch.upbit_execution_restore_epoch",
        ep,
    )

    out = evaluate_waiting_buy_revalidation_gate(
        MagicMock(),
        user_broker_account_id=1380,
        symbol="KRW-WLD",
        order_source="AUTO",
        broker_code="UPBIT",
        side="BUY",
        waiting_updated_at=None,
        skip_if_not_waiting=True,
    )
    assert out["allowed"] is True
    assert out.get("detail", {}).get("restore_epoch_skipped") == "NOT_WAITING_SLOT"
    assert out.get("reason") != REASON_STALE_PRE_RESTORE_WAITING


def test_waiting_gate_still_blocks_pre_restore_waiting(monkeypatch) -> None:
    from stock_platform.operation.upbit_full_market import waiting_revalidation_gate as g

    monkeypatch.setattr(g, "_exit_monitor_running", lambda: (True, {"status": "RUNNING"}))
    monkeypatch.setattr(
        g, "_feed_real_fresh", lambda session, uba_id: (True, {"status": "REAL_FRESH"})
    )

    ep = UpbitExecutionRestoreEpoch()
    ep.mark_restored(actor="test")
    old = datetime.now(timezone.utc) - timedelta(minutes=5)
    monkeypatch.setattr(
        "stock_platform.trading.upbit_execution_restore_epoch.upbit_execution_restore_epoch",
        ep,
    )

    out = evaluate_waiting_buy_revalidation_gate(
        MagicMock(),
        user_broker_account_id=1380,
        symbol="KRW-WLD",
        order_source="AUTO",
        broker_code="UPBIT",
        side="BUY",
        waiting_updated_at=old,
        skip_if_not_waiting=True,
    )
    assert out["allowed"] is False
    assert out["reason"] == REASON_STALE_PRE_RESTORE_WAITING


def test_data_trust_valid_on_normal_no_signal() -> None:
    ev = evaluate_data_trust_from_health(
        {
            "components": {
                "runtime": "RUNNING",
                "runner": "RUNNING",
                "worker": "RUNNING",
                "exit_monitor": "RUNNING",
                "scanner": "RUNNING",
                "feed": "REAL_FRESH",
            },
            "health_state": "READY",
            "no_trade_classification": "NORMAL_NO_SIGNAL",
            "open_count": 0,
            "invariants": {},
            "watchdog": {"running": True},
        }
    )
    assert ev["quality_status"] == QUALITY_VALID


def test_data_trust_invalid_on_feed_down() -> None:
    ev = evaluate_data_trust_from_health(
        {
            "components": {
                "runtime": "RUNNING",
                "runner": "RUNNING",
                "worker": "RUNNING",
                "exit_monitor": "RUNNING",
                "scanner": "RUNNING",
                "feed": "DISCONNECTED",
            },
            "health_state": "BROKEN",
            "open_count": 0,
            "invariants": {},
        }
    )
    assert ev["quality_status"] == QUALITY_INVALID
    assert ev["reason_code"] == "FEED_DOWN"


def test_data_trust_invalid_exit_down_with_open() -> None:
    ev = evaluate_data_trust_from_health(
        {
            "components": {
                "runtime": "RUNNING",
                "runner": "RUNNING",
                "worker": "RUNNING",
                "exit_monitor": "STOPPED",
                "scanner": "RUNNING",
                "feed": "REAL_FRESH",
            },
            "health_state": "BROKEN",
            "open_count": 2,
            "invariants": {},
        }
    )
    assert ev["quality_status"] == QUALITY_INVALID
    assert ev["reason_code"] == "EXIT_DOWN_WITH_OPEN"


def test_data_trust_degraded_waiting_starvation() -> None:
    ev = evaluate_data_trust_from_health(
        {
            "components": {
                "runtime": "RUNNING",
                "runner": "RUNNING",
                "worker": "RUNNING",
                "exit_monitor": "RUNNING",
                "scanner": "RUNNING",
                "feed": "REAL_FRESH",
            },
            "health_state": "DEGRADED",
            "no_trade_classification": "WAITING_SLOT_STARVATION",
            "open_count": 0,
            "invariants": {},
        }
    )
    assert ev["quality_status"] == QUALITY_DEGRADED


def test_data_trust_worker_down_invalid() -> None:
    ev = evaluate_data_trust_from_health(
        {
            "components": {
                "runtime": "RUNNING",
                "runner": "RUNNING",
                "worker": "STOPPED",
                "exit_monitor": "RUNNING",
                "scanner": "RUNNING",
                "feed": "REAL_FRESH",
            },
            "health_state": "BROKEN",
            "open_count": 0,
            "invariants": {},
        }
    )
    assert ev["quality_status"] == QUALITY_INVALID
    assert ev["reason_code"] == "STACK_DOWN"


def test_waiting_rotation_healthy_not_invalid() -> None:
    """WAITING starvation → DEGRADED, never INVALID (거래 없음 ≠ 장애)."""

    ev = evaluate_data_trust_from_health(
        {
            "components": {
                "runtime": "RUNNING",
                "runner": "RUNNING",
                "worker": "RUNNING",
                "exit_monitor": "RUNNING",
                "scanner": "RUNNING",
                "feed": "REAL_FRESH",
            },
            "health_state": "DEGRADED",
            "no_trade_classification": "WAITING_SLOT_STARVATION",
            "open_count": 0,
            "invariants": {},
        }
    )
    assert ev["quality_status"] != QUALITY_INVALID
    assert ev["quality_status"] == QUALITY_DEGRADED


def test_broker_divergence_invalid() -> None:
    ev = evaluate_data_trust_from_health(
        {
            "components": {
                "runtime": "RUNNING",
                "runner": "RUNNING",
                "worker": "RUNNING",
                "exit_monitor": "RUNNING",
                "scanner": "RUNNING",
                "feed": "REAL_FRESH",
            },
            "health_state": "BROKEN",
            "open_count": 0,
            "invariants": {"local_remote_divergence": 1},
        }
    )
    assert ev["quality_status"] == QUALITY_INVALID
    assert ev["reason_code"] == "CRITICAL_INVARIANT"


def test_incident_recurrence_increments(monkeypatch) -> None:
    """동일 signature 재발 → recurrence_count 증가."""

    from stock_platform.trading import autotrading_data_trust as dt

    class _FakeResult:
        def __init__(self, mapping=None, scalar=None):
            self._mapping = mapping
            self._scalar = scalar

        def mappings(self):
            return self

        def first(self):
            return self._mapping

        def scalar(self):
            return self._scalar

    calls: list[str] = []

    class _FakeSession:
        def execute(self, stmt, params=None):
            sql = str(stmt)
            if "SELECT incident_id" in sql and "recovered_at IS NULL" in sql:
                if not calls:
                    calls.append("select_empty")
                    return _FakeResult(mapping=None)
                calls.append("select_open")
                return _FakeResult(
                    mapping={"incident_id": 7, "recurrence_count": 1}
                )
            if "INSERT INTO operation.autotrading_incident_ledger" in sql:
                calls.append("insert")
                return _FakeResult(scalar=7)
            if "UPDATE operation.autotrading_incident_ledger" in sql:
                calls.append("update")
                return _FakeResult()
            return _FakeResult()

    sess = _FakeSession()
    first = dt.record_incident(
        sess,
        market="UPBIT",
        uba_id=1380,
        signature="STALE_PRE_RESTORE_WAITING",
        classification="SYSTEM_FAILURE",
        first_zero_stage="ORDER",
        root_cause="ENTRY_PENDING_FALSE_STALE",
        data_quality_impact="INVALID",
    )
    assert first["action"] == "OPENED"
    assert first["recurrence_count"] == 1

    second = dt.record_incident(
        sess,
        market="UPBIT",
        uba_id=1380,
        signature="STALE_PRE_RESTORE_WAITING",
        classification="SYSTEM_FAILURE",
        first_zero_stage="ORDER",
        root_cause="ENTRY_PENDING_FALSE_STALE",
        data_quality_impact="INVALID",
    )
    assert second["action"] == "RECURRENCE"
    assert second["recurrence_count"] == 2


def test_quarantined_excluded_from_promotion_filter() -> None:
    """INVALID/quarantine 표본은 VALID_SAMPLES 에서 제외."""

    from stock_platform.trading.autotrading_data_trust import shadow_quality_counts

    class _FakeResult:
        def mappings(self):
            return self

        def first(self):
            return {"total": 5, "valid_samples": 3, "quarantined": 2}

    class _FakeSession:
        def execute(self, *a, **k):
            return _FakeResult()

    out = shadow_quality_counts(
        _FakeSession(), uba_id=1380, table="upbit_trailing_forward_shadow"
    )
    assert out["TOTAL"] == 5
    assert out["VALID_SAMPLES"] == 3
    assert out["QUARANTINED"] == 2
    assert out["raw_data_deleted"] is False