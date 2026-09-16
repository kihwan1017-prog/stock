"""MA exit forward shadow — unit tests (no broker / REAL mutation)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from stock_platform.operation.upbit_opportunity_shadow.ma_exit_forward_shadow.constants import (
    CONFIRM_EVALUATIONS,
    STATUS_ACTIVE,
    STATUS_COMPLETED,
    STATUS_SHADOW_TRACKING,
)
from stock_platform.operation.upbit_opportunity_shadow.ma_exit_forward_shadow.service import (
    _apply_confirm2_evaluation,
    _check_protective_exit,
    compute_round_trip_pnl,
    deployment_epoch,
    enroll_on_position_open,
    observe_tick,
    shadow_enabled,
)
from stock_platform.operation.upbit_opportunity_shadow.ma_exit_forward_shadow.summary import (
    sample_stage,
)
from stock_platform.realtime.ma_exit_policy import MaExitThresholds


def _th() -> MaExitThresholds:
    return MaExitThresholds(
        exit_min_ma_separation_pct=0.03,
        ma_exit_min_holding_seconds=0,
    )


def _mock_row(**kwargs):
    base = dict(
        entry_at=datetime(2026, 8, 26, 1, 0, tzinfo=timezone.utc),
        entry_price=Decimal("1000"),
        entry_quantity=Decimal("1"),
        entry_fee=None,
        shadow_first_dead_cross_at=None,
        shadow_confirmation_count=0,
        shadow_exit_at=None,
        baseline_exit_at=None,
        baseline_exit_reason=None,
        baseline_net_pnl=None,
        shadow_net_pnl=None,
        status=STATUS_ACTIVE,
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_first_dead_cross_does_not_shadow_exit() -> None:
    row = _mock_row()
    t = row.entry_at + timedelta(minutes=5)
    state: dict = {"confirm_streak": 0}
    exited = _apply_confirm2_evaluation(
        row=row,
        state=state,
        event_time=t,
        short_ma=Decimal("97"),
        long_ma=Decimal("100"),
        prev_short=Decimal("101"),
        prev_long=Decimal("100"),
        thresholds=_th(),
    )
    assert exited is False
    assert state["confirm_streak"] == 1
    assert CONFIRM_EVALUATIONS == 2


def test_second_consecutive_dead_cross_exits_shadow() -> None:
    row = _mock_row()
    t = row.entry_at + timedelta(minutes=5)
    state: dict = {"confirm_streak": 1}
    row.shadow_first_dead_cross_at = t - timedelta(minutes=1)
    exited = _apply_confirm2_evaluation(
        row=row,
        state=state,
        event_time=t,
        short_ma=Decimal("97"),
        long_ma=Decimal("100"),
        prev_short=Decimal("98"),
        prev_long=Decimal("100"),
        thresholds=_th(),
    )
    assert exited is True
    assert state["confirm_streak"] == 2


def test_dead_cross_reset_on_bullish_recovery() -> None:
    row = _mock_row()
    state = {"confirm_streak": 1}
    row.shadow_confirmation_count = 1
    t = row.entry_at + timedelta(minutes=6)
    exited = _apply_confirm2_evaluation(
        row=row,
        state=state,
        event_time=t,
        short_ma=Decimal("101"),
        long_ma=Decimal("100"),
        prev_short=Decimal("99"),
        prev_long=Decimal("100"),
        thresholds=_th(),
    )
    assert exited is False
    assert state["confirm_streak"] == 0
    assert row.shadow_confirmation_count == 0


def test_stop_loss_immediate_in_shadow() -> None:
    row = _mock_row()
    state: dict = {"confirm_streak": 0, "high_water": str(row.entry_price)}
    reason = _check_protective_exit(
        row=row,
        price=Decimal("940"),
        event_time=row.entry_at + timedelta(minutes=1),
        stop_loss_ratio=Decimal("0.05"),
        take_profit_ratio=Decimal("0.10"),
        trail_distance_ratio=Decimal("0.03"),
        state=state,
    )
    assert reason == "STOP_LOSS"


def test_kill_switch_is_protective_reason() -> None:
    from stock_platform.realtime.ma_exit_policy import is_protective_exit_reason

    assert is_protective_exit_reason("KILL_SWITCH")
    assert is_protective_exit_reason("RISK_EXIT")


def test_fee_calculation() -> None:
    pnl = compute_round_trip_pnl(
        entry_price=Decimal("1000"),
        exit_price=Decimal("1010"),
        quantity=Decimal("1"),
    )
    assert pnl["net_pnl"] < pnl["gross_pnl"]


def test_sample_stage_gates() -> None:
    assert sample_stage(10) == "COLLECTION_ONLY"
    assert sample_stage(50) == "EARLY_DIAGNOSTIC"
    assert sample_stage(200) == "PRIMARY_REVIEW"
    assert sample_stage(600) == "PROMOTION_REVIEW"


def test_shadow_enabled_default() -> None:
    assert shadow_enabled() is True


def test_deployment_epoch_from_settings(monkeypatch) -> None:
    class _S:
        upbit_ma_exit_forward_shadow_deployed_at = "2026-08-26T12:00:00+00:00"

    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_shadow.ma_exit_forward_shadow.service.get_settings",
        lambda: _S(),
    )
    ep = deployment_epoch(_S())
    assert ep.year == 2026
    assert ep.hour == 12


class _FakeSession:
    def __init__(self) -> None:
        self.rows: list[SimpleNamespace] = []
        self._id = 0

    def scalar(self, _stmt):
        for r in self.rows:
            if getattr(r, "status", None) in (STATUS_ACTIVE, STATUS_SHADOW_TRACKING):
                return r
        return None

    def flush(self) -> None:
        return None

    def commit(self) -> None:
        return None

    def add(self, row) -> None:
        self._id += 1
        row.shadow_row_id = self._id
        self.rows.append(row)


def test_observe_tick_real_ma_continues_shadow(monkeypatch) -> None:
    fake = _FakeSession()
    t0 = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
    row = SimpleNamespace(
        shadow_row_id=1,
        user_broker_account_id=1380,
        symbol="KRW-SUI",
        binding_id=1,
        entry_at=t0,
        entry_price=Decimal("1000"),
        entry_quantity=Decimal("1"),
        entry_fee=None,
        status=STATUS_ACTIVE,
        shadow_first_dead_cross_at=None,
        shadow_confirmation_count=0,
        shadow_exit_at=None,
        shadow_exit_reason=None,
        shadow_net_pnl=None,
        shadow_gross_pnl=None,
        shadow_fee=None,
        baseline_exit_at=None,
        baseline_exit_reason=None,
        baseline_net_pnl=None,
        baseline_exit_price=None,
        baseline_gross_pnl=None,
        baseline_fee=None,
        difference_net=None,
        completed_at=None,
        secondary_shadow_json={},
        shadow_state_json={"confirm_streak": 0, "high_water": "1000"},
    )
    fake.rows.append(row)

    observe_tick(
        fake,
        user_broker_account_id=1380,
        symbol="KRW-SUI",
        event_time=t0 + timedelta(minutes=5),
        price=Decimal("990"),
        short_ma=Decimal("97"),
        long_ma=Decimal("100"),
        prev_short_ma=Decimal("101"),
        prev_long_ma=Decimal("100"),
        thresholds=_th(),
        stop_loss_ratio=Decimal("0.05"),
        take_profit_ratio=Decimal("0.10"),
        trail_distance_ratio=Decimal("0.03"),
        real_signal_reason="MA_DEAD_CROSS",
        real_signal_price=Decimal("990"),
    )
    assert row.baseline_exit_reason == "MA_DEAD_CROSS"
    assert row.status == STATUS_SHADOW_TRACKING
    assert row.shadow_exit_at is None


def test_preexisting_enrollment_status(monkeypatch) -> None:
    class _S:
        upbit_ma_exit_forward_shadow_enabled = True
        upbit_ma_exit_forward_shadow_deployed_at = "2026-08-26T12:00:00+00:00"

    fake = _FakeSession()
    past = datetime(2026, 8, 26, 10, 0, tzinfo=timezone.utc)
    res = enroll_on_position_open(
        fake,
        user_broker_account_id=1380,
        binding_id=99,
        symbol="KRW-GRVT",
        strategy_id=1,
        entry_order_id=1,
        entry_at=past,
        entry_price=Decimal("500"),
        settings=_S(),
    )
    assert res["pre_existing"] is True
    assert fake.rows[0].status == "PRE_EXISTING_POSITION_EXCLUDED"


def test_duplicate_enrollment(monkeypatch) -> None:
    class _FakeSession2(_FakeSession):
        def scalar(self, _stmt):
            return self.rows[0] if self.rows else None

    fake = _FakeSession2()
    fake.rows.append(SimpleNamespace(binding_id=42, shadow_row_id=1))
    again = enroll_on_position_open(
        fake,
        user_broker_account_id=1380,
        binding_id=42,
        symbol="KRW-SUI",
        strategy_id=1,
        entry_order_id=1,
        entry_at=datetime.now(timezone.utc),
        entry_price=Decimal("1000"),
    )
    assert again.get("duplicate") is True


def test_confirm2_two_ticks_complete_via_observe(monkeypatch) -> None:
    fake = _FakeSession()
    t0 = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
    row = SimpleNamespace(
        shadow_row_id=1,
        user_broker_account_id=1380,
        symbol="KRW-SUI",
        binding_id=2,
        entry_at=t0,
        entry_price=Decimal("1000"),
        entry_quantity=Decimal("1"),
        entry_fee=None,
        status=STATUS_ACTIVE,
        shadow_first_dead_cross_at=None,
        shadow_confirmation_count=0,
        shadow_exit_at=None,
        shadow_exit_reason=None,
        shadow_net_pnl=None,
        shadow_gross_pnl=None,
        shadow_fee=None,
        baseline_exit_at=None,
        baseline_exit_reason=None,
        baseline_net_pnl=None,
        baseline_exit_price=None,
        baseline_gross_pnl=None,
        baseline_fee=None,
        difference_net=None,
        completed_at=None,
        secondary_shadow_json={},
        shadow_state_json={"confirm_streak": 0, "high_water": "1000"},
    )
    fake.rows.append(row)
    kwargs = dict(
        user_broker_account_id=1380,
        symbol="KRW-SUI",
        thresholds=_th(),
        stop_loss_ratio=Decimal("0.05"),
        take_profit_ratio=Decimal("0.10"),
        trail_distance_ratio=Decimal("0.03"),
    )
    observe_tick(
        fake,
        event_time=t0 + timedelta(minutes=4),
        price=Decimal("995"),
        short_ma=Decimal("97"),
        long_ma=Decimal("100"),
        prev_short_ma=Decimal("101"),
        prev_long_ma=Decimal("100"),
        **kwargs,
    )
    observe_tick(
        fake,
        event_time=t0 + timedelta(minutes=5),
        price=Decimal("992"),
        short_ma=Decimal("96"),
        long_ma=Decimal("100"),
        prev_short_ma=Decimal("97"),
        prev_long_ma=Decimal("100"),
        **kwargs,
    )
    assert row.shadow_exit_reason == "MA_DEAD_CROSS"
    assert row.status == STATUS_COMPLETED
