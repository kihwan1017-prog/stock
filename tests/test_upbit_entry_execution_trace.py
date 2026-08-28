"""UPBIT entry execution trace — focused regression tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from stock_platform.operation.upbit_entry_execution_trace.constants import (
    STAGE_BEGIN_ENTRY_REJECTED,
    STAGE_EXECUTOR_REJECTED,
    STAGE_ORDER_PERSISTED,
    STAGE_SIGNAL_EMITTED,
    STAGE_SIGNAL_SUPPRESSED,
)
from stock_platform.operation.upbit_entry_execution_trace.context import (
    clear_current,
    set_current,
)
from stock_platform.operation.upbit_entry_execution_trace.hooks import (
    trace_begin_entry_result,
    trace_bullish_evaluation,
)
from stock_platform.operation.upbit_entry_execution_trace.service import (
    append_stage,
    append_stage_fail_open,
    build_idempotency_key,
    build_provenance,
    build_why_no_trade,
    new_execution_trace_id,
)
from stock_platform.operation.upbit_entry_execution_trace.user_reasons import (
    USER_REASON_MAP,
    friendly_reason,
    user_reason_coverage,
)
from stock_platform.realtime.scoped_signal_pipeline import strategy_signal_to_realtime
from stock_platform.realtime.strategy_models import RealtimeSignalAction
from stock_platform.realtime.strategy_signal import StrategySignal
from datetime import datetime, timezone
from decimal import Decimal


def _mock_session() -> MagicMock:
    session = MagicMock()
    session.scalar.return_value = None
    session.flush.return_value = None
    session.commit.return_value = None
    session.rollback.return_value = None
    return session


def test_idempotency_duplicate_skip() -> None:
    key = build_idempotency_key(
        execution_trace_id="abc",
        stage="X",
        decision="PASS",
        reason_code=None,
    )
    key2 = build_idempotency_key(
        execution_trace_id="abc",
        stage="X",
        decision="PASS",
        reason_code=None,
    )
    assert key == key2


def test_signal_provenance_to_realtime_signal() -> None:
    trace_id = new_execution_trace_id()
    sig = StrategySignal(
        signal_id="sig_test",
        fingerprint="fp1",
        scope_key="scope",
        user_id=1,
        account_kind="USER_BROKER",
        account_id=1380,
        strategy_id=17483,
        strategy_version="1",
        broker_code="UPBIT",
        market_type="SPOT",
        symbol="KRW-XPL",
        signal_type="BUY",
        generated_at=datetime.now(timezone.utc),
        event_time=datetime.now(timezone.utc),
        reference_price=Decimal("100"),
        metadata={
            "execution_trace_id": trace_id,
            "candidate_selection_id": 247,
            "waiting_id": 8,
            "lifecycle_kind": "INITIAL",
        },
    )
    rt = strategy_signal_to_realtime(sig)
    assert rt.execution_trace_id == trace_id
    assert rt.candidate_selection_id == 247
    assert rt.waiting_id == 8


def test_bullish_trace_signal_suppressed(session_mock: None = None) -> None:
    session = _mock_session()
    out = trace_bullish_evaluation(
        session,
        user_broker_account_id=1380,
        symbol="KRW-XPL",
        strategy_id=17483,
        selection_id=247,
        technical_ok=True,
        block_reason=None,
        signal_emitted=False,
    )
    assert out["provenance"]["execution_trace_id"]
    assert session.add.called


def test_bullish_trace_signal_emitted_no_duplicate_signal_id_kwarg() -> None:
    """SIGNAL_EMITTED 경로에서 signal_id 중복 kwargs TypeError가 나면 안 된다."""

    session = _mock_session()
    out = trace_bullish_evaluation(
        session,
        user_broker_account_id=1380,
        symbol="KRW-XPL",
        strategy_id=17483,
        selection_id=247,
        technical_ok=True,
        block_reason=None,
        signal_emitted=True,
        signal_id="sig_emitted_once",
        execution_trace_id=str(uuid4()),
    )
    assert out["provenance"]["execution_trace_id"]
    assert session.add.call_count >= 3
    # STAGE_SIGNAL_EMITTED 가 포함됐는지 entity stage 확인
    stages = [
        call.args[0].stage
        for call in session.add.call_args_list
        if hasattr(call.args[0], "stage")
    ]
    assert STAGE_SIGNAL_EMITTED in stages
    assert STAGE_SIGNAL_SUPPRESSED not in stages


def test_begin_entry_reject_trace() -> None:
    session = _mock_session()
    trace_id = str(uuid4())
    set_current(
        {
            "execution_trace_id": trace_id,
            "candidate_selection_id": 247,
            "waiting_id": 8,
            "strategy_id": 17483,
            "signal_id": "sig1",
            "lifecycle_kind": "INITIAL",
        }
    )
    trace_begin_entry_result(
        session,
        user_broker_account_id=1380,
        symbol="KRW-XPL",
        result={"ok": False, "reason": "PENDING_ENTRY_LIMIT"},
        waiting_id=8,
        selection_id=247,
    )
    clear_current()
    assert session.add.called


def test_append_stage_fail_open_no_raise_on_db_error() -> None:
    session = MagicMock()
    session.scalar.return_value = None
    session.add.side_effect = RuntimeError("db down")
    session.rollback.return_value = None
    out = append_stage_fail_open(
        session,
        execution_trace_id=str(uuid4()),
        user_broker_account_id=1380,
        symbol="KRW-XPL",
        stage=STAGE_EXECUTOR_REJECTED,
        decision="REJECT",
        reason_code="PENDING_ENTRY_LIMIT",
    )
    assert out["ok"] is False


def test_user_reason_coverage_100_percent() -> None:
    codes = set(USER_REASON_MAP.keys())
    cov = user_reason_coverage(observed_codes=codes)
    assert cov["USER_REASON_COVERAGE_PERCENT"] == 100.0
    assert cov["MISSING_USER_REASON_CODES"] == []


def test_friendly_reason_pending_entry() -> None:
    msg = friendly_reason("PENDING_ENTRY_LIMIT")
    assert msg is not None
    assert "다른 종목" in msg


def test_build_provenance_no_guess_without_selection() -> None:
    session = _mock_session()
    prov = build_provenance(
        session,
        user_broker_account_id=1380,
        symbol="KRW-XPL",
        strategy_id=17483,
        selection_id=None,
        execution_trace_id=str(uuid4()),
        lifecycle_kind="INITIAL",
    )
    assert "candidate_selection_id" not in prov


@patch(
    "stock_platform.operation.upbit_entry_execution_trace.service.append_stage",
    side_effect=RuntimeError("fail"),
)
def test_trace_failure_does_not_propagate(_mock_append: MagicMock) -> None:
    session = MagicMock()
    out = append_stage_fail_open(
        session,
        execution_trace_id=str(uuid4()),
        user_broker_account_id=1380,
        symbol="KRW-XPL",
        stage=STAGE_SIGNAL_EMITTED,
        decision="PASS",
    )
    assert out.get("ok") is False


def test_build_why_no_trade_empty_fallback() -> None:
    """TEST 8 — trace 없음 pipeline fallback."""
    session = MagicMock()
    session.scalar.side_effect = [None, None, None]
    session.scalars.return_value.all.return_value = []
    out = build_why_no_trade(
        session,
        user_broker_account_id=1380,
        selection_id=99999,
    )
    assert out["ok"] is True
    assert out["terminal_stage"] is None
    assert out["source"] == "ENTRY_EXECUTION_TRACE"
