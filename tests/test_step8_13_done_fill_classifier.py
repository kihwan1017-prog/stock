"""STEP 8-13 DONE fill classifier unit tests."""

from __future__ import annotations

from stock_platform.trading.step8_13_done_fill_classifier import (
    CLASS_A,
    CLASS_C,
    CLASS_D,
    CLASS_E,
    CLASS_F,
    REC_IMPORT,
    REC_MANUAL,
    REC_SAFE_IGNORE,
    classify_done_fill,
)


def test_fully_reconciled() -> None:
    v = classify_done_fill(
        conflict_id=5,
        executed_volume="1.5",
        trades_count=1,
        has_internal_order=True,
        has_internal_execution=True,
        execution_qty_matches_trades=True,
        broker_balance_known=True,
        internal_position_known=True,
        position_matches_broker=True,
        snapshot_synced_from_broker=True,
        remote_status="done",
    )
    assert v.classification == CLASS_A
    assert v.recommendation == REC_SAFE_IGNORE


def test_missing_execution() -> None:
    v = classify_done_fill(
        conflict_id=5,
        executed_volume="1",
        trades_count=1,
        has_internal_order=True,
        has_internal_execution=False,
        execution_qty_matches_trades=False,
        broker_balance_known=True,
        internal_position_known=True,
        position_matches_broker=True,
        snapshot_synced_from_broker=True,
        remote_status="done",
    )
    assert v.classification == CLASS_C
    assert v.recommendation == REC_IMPORT


def test_position_reconcilable_safe_ignore() -> None:
    v = classify_done_fill(
        conflict_id=5,
        executed_volume="10",
        trades_count=1,
        has_internal_order=False,
        has_internal_execution=False,
        execution_qty_matches_trades=False,
        broker_balance_known=True,
        internal_position_known=True,
        position_matches_broker=True,
        snapshot_synced_from_broker=True,
        remote_status="done",
    )
    assert v.classification == CLASS_D
    assert v.recommendation == REC_SAFE_IGNORE
    assert v.impact.report is True
    assert v.impact.tax is True
    assert v.impact.position is False


def test_import_required_on_mismatch() -> None:
    v = classify_done_fill(
        conflict_id=5,
        executed_volume="10",
        trades_count=1,
        has_internal_order=False,
        has_internal_execution=False,
        execution_qty_matches_trades=False,
        broker_balance_known=True,
        internal_position_known=True,
        position_matches_broker=False,
        snapshot_synced_from_broker=True,
        remote_status="done",
    )
    assert v.classification == CLASS_E
    assert v.recommendation == REC_IMPORT


def test_unsafe_unexpected_status() -> None:
    v = classify_done_fill(
        conflict_id=5,
        executed_volume="0",
        trades_count=0,
        has_internal_order=False,
        has_internal_execution=False,
        execution_qty_matches_trades=False,
        broker_balance_known=True,
        internal_position_known=True,
        position_matches_broker=True,
        snapshot_synced_from_broker=True,
        remote_status="wait",
    )
    assert v.classification == CLASS_F
    assert v.recommendation == REC_MANUAL
