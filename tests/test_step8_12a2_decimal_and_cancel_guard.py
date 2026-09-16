"""STEP 8-12A-2 Decimal JSON 직렬화·CANCEL allowlist 가드 테스트."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from uuid import uuid4

import pytest

from stock_platform.broker.recovery_adapter import AdapterRecoveryResult
from stock_platform.broker.upbit.order_reconcile_service import (
    sanitize_upbit_order_snapshot,
)
from stock_platform.common.json_safe import dumps_jsonable, to_jsonable
from stock_platform.trading.step8_12a2_cancel_guard import (
    STEP8_12A2_CANCEL_ALLOWLIST,
    STEP8_12A2_DONE_ALLOWLIST,
    STEP8_12A2_MISMATCH_IDS,
    assert_only_allowlisted_mutation,
    evaluate_safe_cancel_ignore,
)


def test_to_jsonable_preserves_decimal_as_string() -> None:
    payload = {
        "deposit_amount": Decimal("12345.67890123"),
        "nested": {"fee": Decimal("0.00000001")},
        "list": [Decimal("1.5"), Decimal("0")],
    }
    out = to_jsonable(payload)
    assert out["deposit_amount"] == "12345.67890123"
    assert out["nested"]["fee"] == "0.00000001"
    assert out["list"] == ["1.5", "0"]
    # 과학적 표기 없이 고정 소수점 문자열
    assert "E" not in out["nested"]["fee"].upper()
    dumps_jsonable(out)  # TypeError 없어야 함


def test_to_jsonable_datetime_uuid_enum() -> None:
    class Sample(Enum):
        A = "alpha"

    uid = uuid4()
    now = datetime(2026, 7, 27, 1, 2, 3, tzinfo=timezone.utc)
    out = to_jsonable({"t": now, "u": uid, "e": Sample.A})
    assert out["t"].startswith("2026-07-27")
    assert out["u"] == str(uid)
    assert out["e"] == "alpha"


def test_to_jsonable_fail_closed_on_unknown() -> None:
    class Weird:
        pass

    with pytest.raises(TypeError):
        to_jsonable({"x": Weird()})


def test_adapter_recovery_result_to_dict_decimal() -> None:
    result = AdapterRecoveryResult(
        status="MANUAL_REVIEW",
        broker_code="UPBIT",
        user_broker_account_id=58,
    )
    result.detail["account_sync"] = {
        "deposit_amount": Decimal("5000.12"),
    }
    payload = result.to_dict()
    assert payload["detail"]["account_sync"]["deposit_amount"] == "5000.12"
    dumps_jsonable(payload)


def test_sanitize_snapshot_decimal_jsonable() -> None:
    remote = {
        "uuid": "abcd-1234-efgh-5678",
        "market": "KRW-BTC",
        "state": "cancel",
        "executed_volume": Decimal("0"),
        "paid_fee": Decimal("0.0000"),
        "volume": Decimal("0.01"),
        "trades": [],
    }
    out = sanitize_upbit_order_snapshot(remote)
    assert out["executed_volume"] == "0"
    assert out["paid_fee"] == "0.0000"
    dumps_jsonable(out)


def test_cancel_allowlist_sizes() -> None:
    assert len(STEP8_12A2_CANCEL_ALLOWLIST) == 22
    assert STEP8_12A2_MISMATCH_IDS == frozenset({3, 4})
    assert len(STEP8_12A2_DONE_ALLOWLIST) == 20
    assert STEP8_12A2_CANCEL_ALLOWLIST.isdisjoint(STEP8_12A2_DONE_ALLOWLIST)
    assert STEP8_12A2_CANCEL_ALLOWLIST.isdisjoint(STEP8_12A2_MISMATCH_IDS)


def test_safe_cancel_ok() -> None:
    now = datetime.now(timezone.utc)
    verdict = evaluate_safe_cancel_ignore(
        conflict_id=25,
        allowlist=STEP8_12A2_CANCEL_ALLOWLIST,
        remote_status="cancel",
        executed_volume="0",
        remaining_volume="0.1",
        paid_fee="0",
        trades_count=0,
        broker_open=False,
        has_internal_execution=False,
        has_position_impact=False,
        last_remote_checked_at=now,
    )
    assert verdict.ok
    assert verdict.bucket == "SAFE_CANCEL_TO_IGNORE"


def test_block_non_allowlist() -> None:
    now = datetime.now(timezone.utc)
    verdict = evaluate_safe_cancel_ignore(
        conflict_id=999,
        allowlist=STEP8_12A2_CANCEL_ALLOWLIST,
        remote_status="cancel",
        executed_volume="0",
        remaining_volume="0",
        paid_fee="0",
        trades_count=0,
        broker_open=False,
        has_internal_execution=False,
        has_position_impact=False,
        last_remote_checked_at=now,
    )
    assert not verdict.ok
    assert verdict.bucket == "BLOCKED_NOT_ALLOWLISTED"
    with pytest.raises(ValueError):
        assert_only_allowlisted_mutation(
            999, allowlist=STEP8_12A2_CANCEL_ALLOWLIST
        )


def test_block_paid_fee_and_trades() -> None:
    now = datetime.now(timezone.utc)
    fee = evaluate_safe_cancel_ignore(
        conflict_id=25,
        allowlist=STEP8_12A2_CANCEL_ALLOWLIST,
        remote_status="cancel",
        executed_volume=0,
        remaining_volume=0,
        paid_fee="0.01",
        trades_count=0,
        broker_open=False,
        has_internal_execution=False,
        has_position_impact=False,
        last_remote_checked_at=now,
    )
    assert not fee.ok
    assert any("paid_fee" in r for r in fee.reasons)

    trades = evaluate_safe_cancel_ignore(
        conflict_id=25,
        allowlist=STEP8_12A2_CANCEL_ALLOWLIST,
        remote_status="cancel",
        executed_volume=0,
        remaining_volume=0,
        paid_fee=0,
        trades_count=2,
        broker_open=False,
        has_internal_execution=False,
        has_position_impact=False,
        last_remote_checked_at=now,
    )
    assert not trades.ok
    assert any("trades_count" in r for r in trades.reasons)


def test_block_fill_and_stale_and_execution() -> None:
    now = datetime.now(timezone.utc)
    fill = evaluate_safe_cancel_ignore(
        conflict_id=25,
        allowlist=STEP8_12A2_CANCEL_ALLOWLIST,
        remote_status="cancel",
        executed_volume="0.01",
        remaining_volume=0,
        paid_fee=0,
        trades_count=0,
        broker_open=False,
        has_internal_execution=False,
        has_position_impact=False,
        last_remote_checked_at=now,
    )
    assert not fill.ok

    stale = evaluate_safe_cancel_ignore(
        conflict_id=25,
        allowlist=STEP8_12A2_CANCEL_ALLOWLIST,
        remote_status="cancel",
        executed_volume=0,
        remaining_volume=0,
        paid_fee=0,
        trades_count=0,
        broker_open=False,
        has_internal_execution=False,
        has_position_impact=False,
        last_remote_checked_at=now - timedelta(hours=48),
        now=now,
    )
    assert not stale.ok
    assert "broker_state_stale" in stale.reasons

    exe = evaluate_safe_cancel_ignore(
        conflict_id=25,
        allowlist=STEP8_12A2_CANCEL_ALLOWLIST,
        remote_status="cancel",
        executed_volume=0,
        remaining_volume=0,
        paid_fee=0,
        trades_count=0,
        broker_open=False,
        has_internal_execution=True,
        has_position_impact=False,
        last_remote_checked_at=now,
    )
    assert not exe.ok
    assert "internal_execution_exists" in exe.reasons


def test_mismatch_ids_only_three_four() -> None:
    assert sorted(STEP8_12A2_MISMATCH_IDS) == [3, 4]
    # DONE/CANCEL allowlist와 겹치지 않음 — Refresh 대상은 mismatch만
    for cid in STEP8_12A2_MISMATCH_IDS:
        assert cid not in STEP8_12A2_CANCEL_ALLOWLIST
        assert cid not in STEP8_12A2_DONE_ALLOWLIST
