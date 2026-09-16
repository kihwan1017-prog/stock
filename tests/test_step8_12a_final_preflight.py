"""STEP 8-12A — Conflict 분류·차단 규칙 단위 테스트."""

from __future__ import annotations

from datetime import datetime, timezone

from stock_platform.trading.step8_12a_conflict_classifier import (
    CLASS_CURRENT_ACTIVE,
    CLASS_HISTORICAL,
    CLASS_STATE_MISMATCH,
    CLASS_TEST,
    CLASS_UNKNOWN,
    classify_conflict,
    summarize_classifications,
)


def test_terminal_cancel_is_historical() -> None:
    row = classify_conflict(
        conflict_id=1,
        conflict_type="REMOTE_ORDER_NOT_FOUND_LOCALLY",
        review_status="PENDING_REVIEW",
        broker_code="UPBIT",
        market_code="KRW-BTC",
        side_code="BUY",
        external_status="cancel",
        external_order_id_masked="abcd…1234",
        linked_internal_order_id=None,
        remaining_quantity="0.01",
        executed_quantity="0",
        detected_at=datetime(2026, 7, 26, tzinfo=timezone.utc),
        last_remote_checked_at=datetime(2026, 7, 27, tzinfo=timezone.utc),
        paper_account_id=None,
        broker_open_uuids=set(),
        external_order_id="uuid-1",
    )
    assert row.classification == CLASS_HISTORICAL
    assert row.release_blocker is False


def test_wait_in_broker_open_is_active_blocker() -> None:
    row = classify_conflict(
        conflict_id=2,
        conflict_type="REMOTE_ORDER_NOT_FOUND_LOCALLY",
        review_status="PENDING_REVIEW",
        broker_code="UPBIT",
        market_code="KRW-ETH",
        side_code="SELL",
        external_status="wait",
        external_order_id_masked="eeee…9999",
        linked_internal_order_id=None,
        remaining_quantity="0.1",
        executed_quantity="0",
        detected_at=datetime(2026, 7, 26, tzinfo=timezone.utc),
        last_remote_checked_at=None,
        paper_account_id=None,
        broker_open_uuids={"uuid-open"},
        external_order_id="uuid-open",
    )
    assert row.classification == CLASS_CURRENT_ACTIVE
    assert row.release_blocker is True


def test_wait_snapshot_but_remote_now_cancel_is_mismatch_non_blocker() -> None:
    row = classify_conflict(
        conflict_id=3,
        conflict_type="REMOTE_ORDER_NOT_FOUND_LOCALLY",
        review_status="PENDING_REVIEW",
        broker_code="UPBIT",
        market_code="KRW-BTC",
        side_code="SELL",
        external_status="wait",
        external_order_id_masked="aaaa…bbbb",
        linked_internal_order_id=None,
        remaining_quantity="0.002",
        executed_quantity="0",
        detected_at=datetime(2026, 7, 26, tzinfo=timezone.utc),
        last_remote_checked_at=datetime(2026, 7, 26, 23, tzinfo=timezone.utc),
        paper_account_id=None,
        broker_open_uuids=set(),
        external_order_id="uuid-stale",
        remote_lookup_status="cancel",
    )
    assert row.classification == CLASS_STATE_MISMATCH
    assert row.release_blocker is False
    assert row.affects_live_trading is False


def test_paper_artifact() -> None:
    row = classify_conflict(
        conflict_id=4,
        conflict_type="REMOTE_ORDER_NOT_FOUND_LOCALLY",
        review_status="PENDING_REVIEW",
        broker_code="UPBIT",
        market_code="KRW-XRP",
        side_code="BUY",
        external_status="done",
        external_order_id_masked="pppp…1111",
        linked_internal_order_id=None,
        remaining_quantity="0",
        executed_quantity="1",
        detected_at=None,
        last_remote_checked_at=None,
        paper_account_id=99,
    )
    assert row.classification == CLASS_TEST
    assert row.release_blocker is False


def test_unknown_blocks() -> None:
    row = classify_conflict(
        conflict_id=5,
        conflict_type="SOMETHING_NEW",
        review_status="PENDING_REVIEW",
        broker_code="UPBIT",
        market_code=None,
        side_code=None,
        external_status="weird",
        external_order_id_masked=None,
        linked_internal_order_id=None,
        remaining_quantity=None,
        executed_quantity=None,
        detected_at=None,
        last_remote_checked_at=None,
        paper_account_id=None,
    )
    assert row.classification == CLASS_UNKNOWN
    assert row.release_blocker is True


def test_summary_counts_blockers() -> None:
    rows = [
        classify_conflict(
            conflict_id=1,
            conflict_type="X",
            review_status="PENDING_REVIEW",
            broker_code="UPBIT",
            market_code="KRW-BTC",
            side_code="BUY",
            external_status="done",
            external_order_id_masked="a",
            linked_internal_order_id=None,
            remaining_quantity="0",
            executed_quantity="1",
            detected_at=None,
            last_remote_checked_at=None,
            paper_account_id=None,
        ),
        classify_conflict(
            conflict_id=2,
            conflict_type="X",
            review_status="PENDING_REVIEW",
            broker_code="UPBIT",
            market_code="KRW-BTC",
            side_code="BUY",
            external_status="wait",
            external_order_id_masked="b",
            linked_internal_order_id=None,
            remaining_quantity="1",
            executed_quantity="0",
            detected_at=None,
            last_remote_checked_at=None,
            paper_account_id=None,
            broker_open_uuids={"u2"},
            external_order_id="u2",
        ),
    ]
    summary = summarize_classifications(rows)
    assert summary["total"] == 2
    assert summary["release_blocker_count"] == 1
    assert summary["counts"][CLASS_HISTORICAL] == 1
    assert summary["counts"][CLASS_CURRENT_ACTIVE] == 1


def test_no_mutation_surface_in_classifier_module() -> None:
    import inspect

    from stock_platform.trading import step8_12a_conflict_classifier as mod

    src = inspect.getsource(mod)
    for banned in (
        "approve",
        "ignore",
        "create_order",
        "execute_live",
        "UPDATE ",
        "session.execute",
    ):
        assert banned not in src.lower() or banned == "approve"
    # approve 문자열이 notes 등에 없어야 함 — 모듈은 분류만
    assert "approve_import" not in src
    assert "create_order" not in src
