"""STEP 8-15 preserve-history allowlist/guard tests."""

from __future__ import annotations

import pytest

from stock_platform.trading.step8_15_preserve_guard import (
    PRESERVE_REASON,
    STEP8_15_PRESERVE_ALLOWLIST,
    assert_only_allowlisted_preserve,
    evaluate_preserve_history,
)


def test_allowlist_size_and_ids() -> None:
    assert len(STEP8_15_PRESERVE_ALLOWLIST) == 20
    assert sorted(STEP8_15_PRESERVE_ALLOWLIST) == list(range(5, 25))
    assert "NO_IMPORT" in PRESERVE_REASON


def test_block_non_allowlist() -> None:
    v = evaluate_preserve_history(
        conflict_id=99,
        allowlist=STEP8_15_PRESERVE_ALLOWLIST,
        review_status="PENDING_REVIEW",
        remote_status="done",
        classification="POSITION_RECONCILABLE",
        broker_open=False,
        db_open=False,
        position_impact=False,
        balance_impact=False,
    )
    assert not v.ok
    assert v.bucket == "BLOCKED_NOT_ALLOWLISTED"
    with pytest.raises(ValueError):
        assert_only_allowlisted_preserve(
            99, allowlist=STEP8_15_PRESERVE_ALLOWLIST
        )


def test_pending_and_done_required() -> None:
    bad_status = evaluate_preserve_history(
        conflict_id=5,
        allowlist=STEP8_15_PRESERVE_ALLOWLIST,
        review_status="ON_HOLD",
        remote_status="done",
        classification="POSITION_RECONCILABLE",
        broker_open=False,
        db_open=False,
        position_impact=False,
        balance_impact=False,
    )
    assert not bad_status.ok

    bad_remote = evaluate_preserve_history(
        conflict_id=5,
        allowlist=STEP8_15_PRESERVE_ALLOWLIST,
        review_status="PENDING_REVIEW",
        remote_status="cancel",
        classification="POSITION_RECONCILABLE",
        broker_open=False,
        db_open=False,
        position_impact=False,
        balance_impact=False,
    )
    assert not bad_remote.ok


def test_block_open_and_impact_and_import() -> None:
    for kwargs, needle in (
        ({"broker_open": True}, "broker_open"),
        ({"db_open": True}, "db_open"),
        ({"position_impact": True}, "position_impact"),
        ({"balance_impact": True}, "balance_impact"),
        (
            {"classification": "IMPORT_REQUIRED"},
            "classification_blocked",
        ),
        ({"classification": "UNSAFE"}, "classification_blocked"),
    ):
        base = dict(
            conflict_id=5,
            allowlist=STEP8_15_PRESERVE_ALLOWLIST,
            review_status="PENDING_REVIEW",
            remote_status="done",
            classification="POSITION_RECONCILABLE",
            broker_open=False,
            db_open=False,
            position_impact=False,
            balance_impact=False,
        )
        base.update(kwargs)
        v = evaluate_preserve_history(**base)
        assert not v.ok
        assert any(needle in r for r in v.reasons)


def test_safe_to_preserve() -> None:
    v = evaluate_preserve_history(
        conflict_id=5,
        allowlist=STEP8_15_PRESERVE_ALLOWLIST,
        review_status="PENDING_REVIEW",
        remote_status="done",
        classification="POSITION_RECONCILABLE",
        broker_open=False,
        db_open=False,
        position_impact=False,
        balance_impact=False,
    )
    assert v.ok
    assert v.bucket == "SAFE_TO_PRESERVE"


def test_already_preserved_idempotent_bucket() -> None:
    v = evaluate_preserve_history(
        conflict_id=5,
        allowlist=STEP8_15_PRESERVE_ALLOWLIST,
        review_status="HISTORICAL_PRESERVED",
        remote_status="done",
        classification="POSITION_RECONCILABLE",
        broker_open=False,
        db_open=False,
        position_impact=False,
        balance_impact=False,
    )
    assert not v.ok
    assert v.bucket == "ALREADY_PRESERVED"
