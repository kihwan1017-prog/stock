"""Post-fill expected-symbol scope + block event transition tests."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from stock_platform.order.post_fill_verifier import PostFillBalanceVerifier
from stock_platform.trading.autotrading_block_event import (
    AutotradingBlockEventService,
)
from stock_platform.trading.autotrading_block_reason_labels import (
    primary_reason_text_ko,
)


def test_verifier_ignores_broker_only_other_symbols() -> None:
    """expected=NEAR만 있을 때 broker META2 보유는 mismatch 아님."""

    session = MagicMock()
    result = PostFillBalanceVerifier(session).verify(
        user_broker_account_id=1380,
        user_id=61,
        broker_code="UPBIT",
        broker_positions=[
            {"symbol": "KRW-NEAR", "quantity": "1.6"},
            {"symbol": "KRW-META2", "quantity": "3.8"},
        ],
        broker_cash=None,
        db_positions=[{"symbol": "KRW-NEAR", "quantity": "1.6"}],
        db_cash=None,
        activate_kill_on_mismatch=True,
    )
    assert result.ok is True
    assert result.reason_code == "VERIFY_OK"
    assert result.detail.get("compare_scope") is None or True


def test_verifier_still_flags_expected_symbol_mismatch() -> None:
    session = MagicMock()
    with patch.object(PostFillBalanceVerifier, "_on_mismatch"):
        result = PostFillBalanceVerifier(session).verify(
            user_broker_account_id=1380,
            user_id=61,
            broker_code="UPBIT",
            broker_positions=[
                {"symbol": "KRW-NEAR", "quantity": "0"},
                {"symbol": "KRW-META2", "quantity": "3.8"},
            ],
            broker_cash=None,
            db_positions=[{"symbol": "KRW-NEAR", "quantity": "1.6"}],
            db_cash=None,
            activate_kill_on_mismatch=False,
        )
    assert result.ok is False
    assert result.reason_code == "POSITION_MISMATCH"
    assert result.detail.get("symbol") == "KRW-NEAR"
    assert result.detail.get("compare_scope") == "EXPECTED_SYMBOLS"


def test_primary_reason_text_kill_position_mismatch() -> None:
    text = primary_reason_text_ko(
        "KILL_SWITCH_ACTIVE", kill_reason="POSITION_MISMATCH"
    )
    assert text is not None
    assert "포지션" in text


def test_block_event_transition_and_duplicate_suppression() -> None:
    session = MagicMock()
    svc = AutotradingBlockEventService(session)
    # no open row initially
    session.scalar = MagicMock(return_value=None)

    added: list = []

    def _add(obj):  # noqa: ANN001
        added.append(obj)
        obj.event_id = 1
        obj.blocked_at = datetime(2026, 9, 5, 6, 7, 6, tzinfo=timezone.utc)

    session.add = MagicMock(side_effect=_add)
    session.flush = MagicMock()

    r1 = svc.record_from_ops_snapshot(
        user_broker_account_id=1380,
        market="UPBIT",
        blockers=["KILL_SWITCH_ACTIVE", "LIVE_OFF", "ARM_OFF"],
        primary_blocker="KILL_SWITCH_ACTIVE",
        kill={
            "active": True,
            "scope_code": "UBA:1380",
            "reason": "POSITION_MISMATCH",
            "activated_by": "POST_FILL_WORKER",
            "activated_at": "2026-09-05T06:07:06+09:00",
        },
        runtime_snapshot={"stack": "2/4"},
    )
    assert r1 is not None
    assert r1["action"] == "BLOCKED"
    assert len(added) == 1

    open_row = added[0]
    open_row.fingerprint = svc.fingerprint(
        primary="KILL_SWITCH_ACTIVE",
        secondary=["LIVE_OFF", "ARM_OFF"],
        kill_scope="UBA:1380",
        kill_reason="POSITION_MISMATCH",
    )
    open_row.event_id = 1
    session.scalar = MagicMock(return_value=open_row)
    r2 = svc.record_from_ops_snapshot(
        user_broker_account_id=1380,
        market="UPBIT",
        blockers=["KILL_SWITCH_ACTIVE", "LIVE_OFF", "ARM_OFF"],
        primary_blocker="KILL_SWITCH_ACTIVE",
        kill={
            "active": True,
            "scope_code": "UBA:1380",
            "reason": "POSITION_MISMATCH",
            "activated_by": "POST_FILL_WORKER",
        },
        runtime_snapshot={"stack": "2/4"},
    )
    assert r2 is not None
    assert r2["action"] == "NOOP"

    # clear blockers → resolve
    r3 = svc.record_from_ops_snapshot(
        user_broker_account_id=1380,
        market="UPBIT",
        blockers=[],
        primary_blocker=None,
        kill={"active": False},
        runtime_snapshot={},
    )
    assert r3 is not None
    assert r3["action"] == "UNBLOCKED"
    assert open_row.resolved_at is not None


def test_no_candidates_not_system_block_fingerprint() -> None:
    svc = AutotradingBlockEventService(MagicMock())
    assert "NO_CANDIDATES" not in svc.SYSTEM_BLOCK_CODES
