"""UPBIT WAITING slot lifecycle — starvation fix unit tests (REAL 주문 없음)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from stock_platform.operation.upbit_full_market.constants import (
    SLOT_EMPTY,
    SLOT_WAITING_SIGNAL,
)
from stock_platform.operation.upbit_full_market.slot_replacement import (
    REASON_SOFT_STALE_NO_SIGNAL,
    CandidateScoreView,
    ReplacementPolicy,
    SlotScoreView,
    evaluate_slot_replacement,
)
from stock_platform.operation.upbit_full_market.waiting_lifecycle import (
    assess_waiting_slot,
    detect_waiting_slot_starvation,
    ensure_waiting_started_at,
    record_waiting_revalidation,
    release_waiting_slot_to_empty,
    revalidate_waiting_slots,
    resolve_waiting_started_at,
    stamp_waiting_started_at,
    waiting_age_seconds,
)
from stock_platform.operation.upbit_full_market.waiting_lifecycle_policy import (
    REASON_HARD_EXPIRE_NO_SIGNAL,
    WaitingLifecyclePolicy,
    classify_waiting_block_reason,
)
from stock_platform.trading.autotrading_no_trade_classification import (
    classify_no_trade_status,
)


def _now() -> datetime:
    return datetime(2026, 8, 27, 0, 0, tzinfo=timezone.utc)


POLICY = WaitingLifecyclePolicy(
    revalidation_interval_seconds=300.0,
    soft_stale_seconds=1800.0,
    hard_expire_no_signal_seconds=5400.0,
    consecutive_no_signal_threshold=3,
    starvation_degraded_seconds=900.0,
    starvation_broken_seconds=3600.0,
    hold_seconds=1800.0,
)

REPL = ReplacementPolicy(
    hold_seconds=1800,
    max_wait_seconds=10800,
    switch_min_score_delta=8.0,
    candidate_max_age_seconds=1800,
    soft_stale_seconds=1800,
)


def _slot_entity(
    *,
    slot_id: int = 1,
    symbol: str = "KRW-BLEND",
    age_sec: float = 2000,
    entry_order_id: int | None = None,
    binding_id: int | None = None,
    meta: dict | None = None,
) -> SimpleNamespace:
    now = _now()
    started = now - timedelta(seconds=age_sec)
    clamp: dict = {}
    wl_meta = dict(meta or {})
    if "waiting_started_at" not in wl_meta:
        wl_meta["waiting_started_at"] = started.isoformat()
    clamp["waiting_lifecycle_v1"] = wl_meta
    return SimpleNamespace(
        slot_id=slot_id,
        slot_no=1,
        symbol=symbol,
        status=SLOT_WAITING_SIGNAL,
        updated_at=now - timedelta(seconds=60),
        created_at=started,
        clamp_reasons=clamp,
        entry_order_id=entry_order_id,
        position_binding_id=binding_id,
        candidate_selection_id=10,
        scanner_run_id="run-1",
        ai_analysis_id=None,
        reserved_amount_krw=None,
        allocated_amount_krw=None,
        opened_at=None,
        closed_at=None,
        cooldown_until=None,
        version=1,
    )


def test_valid_entry_signal_not_release_eligible() -> None:
    slot = _slot_entity(age_sec=500)
    a = assess_waiting_slot(
        slot=slot,
        policy=POLICY,
        telemetry={"last_decision": "BUY", "last_block_reason": None},
        now=_now(),
    )
    assert a.release_eligible is False
    assert a.soft_stale is False
    assert a.consecutive_no_signal == 0


def test_temporary_block_once_keeps_waiting() -> None:
    slot = _slot_entity(age_sec=600, meta={"consecutive_no_signal": 0})
    a = assess_waiting_slot(
        slot=slot,
        policy=POLICY,
        telemetry={
            "last_decision": "BLOCK",
            "last_block_reason": "RSI_TOO_HIGH",
            "last_evaluated_at": _now().isoformat(),
        },
        now=_now(),
    )
    assert a.release_eligible is False
    assert a.consecutive_no_signal == 1
    assert classify_waiting_block_reason("RSI_TOO_HIGH") == "TEMPORARY"


def test_consecutive_blocks_below_threshold_keeps_waiting() -> None:
    slot = _slot_entity(age_sec=1200, meta={"consecutive_no_signal": 1})
    a = assess_waiting_slot(
        slot=slot,
        policy=POLICY,
        telemetry={
            "last_decision": "NONE",
            "last_block_reason": "MA_SEPARATION_TOO_SMALL",
            "last_evaluated_at": _now().isoformat(),
        },
        now=_now(),
    )
    assert a.consecutive_no_signal == 2
    assert a.release_eligible is False


def test_soft_stale_after_threshold() -> None:
    slot = _slot_entity(age_sec=2000, meta={"consecutive_no_signal": 2})
    a = assess_waiting_slot(
        slot=slot,
        policy=POLICY,
        telemetry={
            "last_decision": "NONE",
            "last_block_reason": "SHORT_MA_NOT_ABOVE_LONG_MA",
            "last_evaluated_at": _now().isoformat(),
        },
        now=_now(),
    )
    assert a.consecutive_no_signal == 3
    assert a.soft_stale is True
    assert a.replacement_eligible is True
    assert a.release_eligible is False


def test_hard_expire_releases() -> None:
    slot = _slot_entity(age_sec=6000, meta={"consecutive_no_signal": 2})
    a = assess_waiting_slot(
        slot=slot,
        policy=POLICY,
        telemetry={
            "last_decision": "NONE",
            "last_block_reason": "RSI_TOO_HIGH",
            "last_evaluated_at": _now().isoformat(),
        },
        now=_now(),
    )
    assert a.hard_expired is True
    assert a.release_eligible is True
    assert a.release_reason == REASON_HARD_EXPIRE_NO_SIGNAL


def test_release_does_not_create_order() -> None:
    slot = _slot_entity()
    session = MagicMock()
    tr = release_waiting_slot_to_empty(
        session,
        slot,
        reason=REASON_HARD_EXPIRE_NO_SIGNAL,
        actor="test",
    )
    assert tr is not None
    assert slot.status == SLOT_EMPTY
    assert slot.symbol is None
    assert slot.entry_order_id is None
    session.add.assert_not_called()


def test_release_blocked_with_entry_order() -> None:
    slot = _slot_entity(entry_order_id=99)
    tr = release_waiting_slot_to_empty(
        MagicMock(),
        slot,
        reason=REASON_HARD_EXPIRE_NO_SIGNAL,
        actor="test",
    )
    assert tr is None
    assert slot.status == SLOT_WAITING_SIGNAL


def test_soft_stale_replacement_path() -> None:
    cand = CandidateScoreView(
        symbol="KRW-NEW", score=85.0, recommendation="ALLOW"
    )
    d = evaluate_slot_replacement(
        slot=SlotScoreView(
            slot_id=1,
            slot_no=1,
            status=SLOT_WAITING_SIGNAL,
            symbol="KRW-OLD",
            score=70.0,
            updated_at=_now() - timedelta(seconds=2000),
            selected_at=_now() - timedelta(seconds=2000),
            reserved_amount_krw=None,
            entry_order_id=None,
            position_binding_id=None,
            soft_stale_eligible=True,
            last_decision="NONE",
        ),
        candidate=cand,
        policy=REPL,
        now=_now(),
    )
    assert d.replace is True
    assert d.reason == REASON_SOFT_STALE_NO_SIGNAL


def test_starvation_detected() -> None:
    out = detect_waiting_slot_starvation(
        waiting_count=5,
        empty_count=0,
        max_positions=5,
        quota_remaining=20,
        stack_ready=True,
        oldest_waiting_age_seconds=1200.0,
        order_count_window=0,
        candidate_or_selection_active=True,
        policy=POLICY,
    )
    assert out["waiting_slot_starvation"] is True
    assert out["escalation"] == "DEGRADED"


def test_starvation_broken_escalation() -> None:
    out = detect_waiting_slot_starvation(
        waiting_count=5,
        empty_count=0,
        max_positions=5,
        quota_remaining=20,
        stack_ready=True,
        oldest_waiting_age_seconds=4000.0,
        order_count_window=0,
        candidate_or_selection_active=True,
        policy=POLICY,
    )
    assert out["escalation"] == "BROKEN"


def test_no_trade_waiting_slot_starvation_not_policy_block() -> None:
    out = classify_no_trade_status(
        health_state="READY",
        partial_restore=False,
        stack_components_down=False,
        daily_blocking=False,
        free_slots=0,
        waiting_count=5,
        selection_count_window=5,
        candidate_count_window=5,
        order_count_window=0,
        admission_count_window=0,
        feed_healthy=True,
        scanner_active=True,
        pipeline_stall_minutes=30,
        last_order_at=None,
        last_selection_at=_now() - timedelta(hours=2),
        waiting_slot_starvation=True,
        starvation_escalation="DEGRADED",
        oldest_waiting_age_seconds=7320.0,
    )
    assert out["classification"] == "WAITING_SLOT_STARVATION"


def test_no_trade_broken_becomes_pipeline_stall() -> None:
    out = classify_no_trade_status(
        health_state="BROKEN",
        partial_restore=False,
        stack_components_down=False,
        daily_blocking=False,
        free_slots=0,
        waiting_count=5,
        selection_count_window=5,
        candidate_count_window=5,
        order_count_window=0,
        admission_count_window=0,
        feed_healthy=True,
        scanner_active=True,
        pipeline_stall_minutes=30,
        last_order_at=None,
        last_selection_at=_now() - timedelta(hours=2),
        waiting_slot_starvation=True,
        starvation_escalation="BROKEN",
        oldest_waiting_age_seconds=7320.0,
    )
    assert out["classification"] == "PIPELINE_STALL"
    assert out["detail"]["first_stalled_transition"] == "WAITING_TO_ADMISSION"


def test_revalidate_respects_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "stock_platform.operation.upbit_full_market.waiting_lifecycle._now",
        _now,
    )
    session = MagicMock()
    slot = _slot_entity(
        age_sec=3600,
        meta={"last_revalidated_at": _now().isoformat(), "consecutive_no_signal": 2},
    )
    session.scalars.return_value.all.return_value = [slot]
    session.scalar.return_value = SimpleNamespace(risk_group_policy_json={})
    session.get.return_value = SimpleNamespace(selected_at=_now() - timedelta(hours=2))

    out = revalidate_waiting_slots(
        session,
        user_broker_account_id=1380,
        telemetry_by_symbol={"KRW-BLEND": {"last_decision": "NONE"}},
    )
    assert out["revalidated"] == 1
    assert out["released"] == 0
    skipped = out["assessments"][0]
    assert skipped.get("skipped") == "REVALIDATION_INTERVAL"
    assert skipped.get("age_seconds", 0) >= 3500


def test_revalidation_updates_updated_at_but_preserves_waiting_age(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A: revalidation → updated_at 갱신, waiting age 유지."""

    monkeypatch.setattr(
        "stock_platform.operation.upbit_full_market.waiting_lifecycle._now",
        _now,
    )
    slot = _slot_entity(age_sec=3600, meta={"consecutive_no_signal": 1})
    before_age = waiting_age_seconds(slot)
    a = assess_waiting_slot(
        slot=slot,
        policy=POLICY,
        telemetry={
            "last_decision": "BLOCK",
            "last_block_reason": "RSI_TOO_HIGH",
            "last_evaluated_at": _now().isoformat(),
        },
    )
    record_waiting_revalidation(slot, a)
    after_age = waiting_age_seconds(slot)
    assert abs(after_age - before_age) < 2.0
    assert slot.updated_at == _now()


def test_no_count_without_fresh_evaluation() -> None:
    slot = _slot_entity(age_sec=600, meta={"consecutive_no_signal": 2})
    a = assess_waiting_slot(
        slot=slot,
        policy=POLICY,
        telemetry={},
    )
    assert a.consecutive_no_signal == 2


def test_restart_preserves_block_count_and_waiting_started_at(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "stock_platform.operation.upbit_full_market.waiting_lifecycle._now",
        _now,
    )
    started = (_now() - timedelta(hours=2)).isoformat()
    meta = {"waiting_started_at": started, "consecutive_no_signal": 3}
    slot = _slot_entity(age_sec=7200, meta=meta)
    a = assess_waiting_slot(
        slot=slot,
        policy=POLICY,
        telemetry={
            "last_decision": "BLOCK",
            "last_block_reason": "RSI_TOO_HIGH",
            "last_evaluated_at": _now().isoformat(),
        },
    )
    assert a.consecutive_no_signal == 4
    assert a.age_seconds >= 7100
    assert _slot_meta_safe(slot).get("waiting_started_at") == started


def _slot_meta_safe(slot: SimpleNamespace) -> dict:
    raw = slot.clamp_reasons
    return dict(raw.get("waiting_lifecycle_v1") or {})


def test_stamp_waiting_started_at_on_replacement_resets_epoch() -> None:
    slot = _slot_entity(age_sec=5000)
    old_started = _slot_meta_safe(slot)["waiting_started_at"]
    stamp_waiting_started_at(slot, started_at=_now(), reset=True)
    new_meta = _slot_meta_safe(slot)
    assert new_meta["waiting_started_at"] != old_started
    assert new_meta["consecutive_no_signal"] == 0
