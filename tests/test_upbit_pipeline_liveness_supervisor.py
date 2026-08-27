"""Pipeline liveness + ENTRY_PENDING zero-fill release + FIRST_ZERO."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from stock_platform.operation.upbit_full_market.constants import SLOT_EMPTY, SLOT_ENTRY_PENDING
from stock_platform.operation.upbit_full_market.portfolio_lifecycle_sync import (
    _is_terminal_zero_fill,
    _reconcile_one_slot,
)
from stock_platform.trading.autotrading_no_trade_classification import (
    classify_no_trade_status,
)
from stock_platform.trading.pipeline_liveness_service import (
    classify_with_entry_signal_context,
    _user_friendly_reason,
)


def test_terminal_zero_fill_detect() -> None:
    o = SimpleNamespace(status_code="CANCELLED", filled_quantity=0)
    assert _is_terminal_zero_fill(o) is True
    o2 = SimpleNamespace(status_code="FILLED", filled_quantity=1.0)
    assert _is_terminal_zero_fill(o2) is False


def test_entry_pending_zero_fill_releases_to_empty() -> None:
    session = MagicMock()
    slot = SimpleNamespace(
        slot_id=4,
        user_broker_account_id=1380,
        status=SLOT_ENTRY_PENDING,
        symbol="KRW-XRP",
        entry_order_id=1896,
        position_binding_id=None,
        candidate_selection_id=1,
        scanner_run_id="x",
        ai_analysis_id=None,
        reserved_amount_krw=1000.0,
        allocated_amount_krw=1000.0,
        opened_at=datetime.now(timezone.utc),
        closed_at=None,
        cooldown_until=None,
        version=1,
        updated_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
    )
    order = SimpleNamespace(
        order_id=1896,
        status_code="CANCELLED",
        filled_quantity=0,
        side_code="BUY",
        created_at=datetime.now(timezone.utc),
        metadata_payload={"order_source": "AUTO", "signal_reason": "PORTFOLIO_BULLISH_STATE_ENTRY"},
        order_source="AUTO",
    )
    fm = MagicMock()
    out = _reconcile_one_slot(
        session,
        slot=slot,
        assignment=MagicMock(),
        fm=fm,
        orders=[order],
        actor="test",
    )
    assert out is not None
    assert "ENTRY_PENDING_ZERO_FILL_RELEASED" in out["changes"]
    assert slot.status == SLOT_EMPTY
    assert slot.entry_order_id is None
    assert slot.symbol is None


def test_classify_entry_signal_wait_not_stall() -> None:
    base = dict(
        health_state="READY",
        partial_restore=False,
        stack_components_down=False,
        daily_blocking=False,
        free_slots=4,
        waiting_count=0,
        selection_count_window=0,
        candidate_count_window=10,
        order_count_window=0,
        feed_healthy=True,
        scanner_active=True,
        pipeline_stall_minutes=15,
        last_order_at=None,
        last_selection_at=None,
    )
    out = classify_with_entry_signal_context(
        base_kwargs=base,
        entry_eval_count=100,
        entry_pass_count=0,
        entry_pending_stuck=0,
        top_block_reason="SHORT_MA_NOT_ABOVE_LONG_MA",
    )
    assert out["classification"] == "NORMAL_NO_SIGNAL"
    assert out["detail"]["reason"] == "ENTRY_SIGNAL_WAIT"


def test_classify_entry_pending_stuck_is_pipeline_stall() -> None:
    base = dict(
        health_state="READY",
        partial_restore=False,
        stack_components_down=False,
        daily_blocking=False,
        free_slots=3,
        waiting_count=0,
        selection_count_window=0,
        candidate_count_window=10,
        order_count_window=0,
        feed_healthy=True,
        scanner_active=True,
        pipeline_stall_minutes=15,
        last_order_at=None,
        last_selection_at=None,
    )
    out = classify_with_entry_signal_context(
        base_kwargs=base,
        entry_eval_count=100,
        entry_pass_count=0,
        entry_pending_stuck=1,
        top_block_reason="SHORT_MA_NOT_ABOVE_LONG_MA",
    )
    assert out["classification"] == "PIPELINE_STALL"
    assert out["detail"]["reason"] == "ENTRY_PENDING_ZERO_FILL_STUCK"


def test_user_friendly_normal_no_signal() -> None:
    text = _user_friendly_reason(
        classification="NORMAL_NO_SIGNAL",
        first_zero="ENTRY_SIGNAL",
        first_zero_reason="SHORT_MA_NOT_ABOVE_LONG_MA",
        stages={"ENTRY_EVALUATION": 50, "WAITING": 0},
        health_state="READY",
    )
    assert "정상" in text
    assert "PASS" in text or "완화" in text


def test_healthy_no_signal_classification_baseline() -> None:
    out = classify_no_trade_status(
        health_state="READY",
        partial_restore=False,
        stack_components_down=False,
        daily_blocking=False,
        free_slots=2,
        waiting_count=0,
        selection_count_window=0,
        candidate_count_window=0,
        order_count_window=0,
        feed_healthy=True,
        scanner_active=True,
        pipeline_stall_minutes=15,
        last_order_at=None,
        last_selection_at=None,
    )
    assert out["classification"] == "NORMAL_NO_SIGNAL"
