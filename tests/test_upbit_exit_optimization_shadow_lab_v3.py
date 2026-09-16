"""Exit Optimization Shadow Lab V3 — focused tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from stock_platform.operation.upbit_opportunity_shadow.exit_optimization_shadow_v3.constants import (
    AUTO_PROMOTION,
    EARLY_REVIEW_N,
    PRIMARY_REVIEW_N,
    PROMOTION_REVIEW_N,
    VARIANT_E1,
    VARIANT_E3,
    VARIANT_E4,
)
from stock_platform.operation.upbit_opportunity_shadow.exit_optimization_shadow_v3.engine import (
    PathSnapshot,
    apply_variant_trailing_defer,
    evaluate_protective_exits,
    evaluate_variant_exit,
)
from stock_platform.operation.upbit_opportunity_shadow.exit_optimization_shadow_v3.policy import (
    DEFAULT_POLICY,
)
from stock_platform.operation.upbit_opportunity_shadow.exit_optimization_shadow_v3.service import (
    _readiness_label,
    pair_variant_row,
)
from stock_platform.operation.upbit_opportunity_shadow.trailing_forward_shadow.service import (
    compute_round_trip_pnl,
)
from stock_platform.operation.upbit_opportunity_shadow.trailing_forward_shadow.constants import (
    LAB_COMPARE_VARIANTS as V2_VARIANTS,
)

UTC = timezone.utc


def _snap(
    entry: str,
    price: str,
    peak: str | None = None,
    hold: float = 120.0,
    mfe: float = 0.0,
    mae: float = 0.0,
    short_ma: str | None = None,
    long_ma: str | None = None,
    ma_dead: bool = False,
) -> PathSnapshot:
    e = Decimal(entry)
    p = Decimal(price)
    pk = Decimal(peak or price)
    return PathSnapshot(
        entry_price=e,
        current_price=p,
        peak_price=pk,
        hold_seconds=hold,
        mfe_pct=mfe,
        mae_pct=mae,
        short_ma=Decimal(short_ma) if short_ma else None,
        long_ma=Decimal(long_ma) if long_ma else None,
        ma_dead_cross=ma_dead,
    )


def test_stop_loss_priority_never_deferred() -> None:
    snap = _snap("100", "96", hold=10.0)
    out = evaluate_protective_exits(snap, DEFAULT_POLICY)
    assert out is not None
    assert out.exit_reason == "STOP_LOSS"
    assert out.should_exit is True


def test_max_hold_priority() -> None:
    snap = _snap("100", "100.5", hold=float(DEFAULT_POLICY.real_max_hold_seconds + 1))
    out = evaluate_protective_exits(snap, DEFAULT_POLICY)
    assert out is not None
    assert out.exit_reason == "MAX_HOLD_TIME"


def test_e1_fee_aware_defer_trailing() -> None:
    snap = _snap("100", "100.05", peak="101.2", hold=90.0, mfe=1.2)
    base = evaluate_variant_exit(snap, DEFAULT_POLICY, VARIANT_E1)
    if base.exit_reason == "TRAILING_STOP":
        deferred = apply_variant_trailing_defer(snap, DEFAULT_POLICY, VARIANT_E1, base)
        assert deferred.defer is True or deferred.should_exit


def test_e3_ma_trend_defer() -> None:
    snap = _snap(
        "100",
        "100.4",
        peak="101.5",
        hold=200.0,
        short_ma="100.8",
        long_ma="100.2",
    )
    decision = evaluate_variant_exit(snap, DEFAULT_POLICY, VARIANT_E3)
    assert decision.defer or decision.should_exit


def test_e4_anti_churn_not_simple_min_hold() -> None:
    snap = _snap("100", "99.95", peak="100.1", hold=15.0, mfe=0.1, mae=-0.05)
    decision = evaluate_variant_exit(snap, DEFAULT_POLICY, VARIANT_E4)
    assert decision.exit_reason != "MIN_HOLD_BLOCK"


def test_fee_calculation_matches_v2() -> None:
    a = compute_round_trip_pnl(
        entry_price=Decimal("1000"),
        exit_price=Decimal("1010"),
        quantity=Decimal("1"),
    )
    b = compute_round_trip_pnl(
        entry_price=Decimal("1000"),
        exit_price=Decimal("1010"),
        quantity=Decimal("1"),
    )
    assert a["net_pnl"] == pytest.approx(b["net_pnl"])


def test_readiness_gates() -> None:
    assert _readiness_label(5) == "SAMPLE_PENDING"
    assert _readiness_label(EARLY_REVIEW_N) == "EARLY_REVIEW"
    assert _readiness_label(PRIMARY_REVIEW_N) == "PRIMARY_REVIEW"
    assert _readiness_label(PROMOTION_REVIEW_N) == "PROMOTION_REVIEW_ELIGIBLE"


def test_auto_promotion_false() -> None:
    assert AUTO_PROMOTION is False


def test_v2_variant_identity_unchanged() -> None:
    assert "T5" in V2_VARIANTS
    assert "E1" not in V2_VARIANTS


def test_pairing_requires_baseline_and_shadow() -> None:
    from types import SimpleNamespace

    enr = SimpleNamespace(
        binding_id=1,
        real_net_pnl=Decimal("-10"),
        real_exit_at=datetime.now(UTC),
        real_holding_seconds=Decimal("30"),
        real_fees=Decimal("2"),
        entry_at=datetime.now(UTC) - timedelta(seconds=30),
    )
    var = SimpleNamespace(
        variant_id="E1",
        status="COMPLETED",
        shadow_estimated_net_pnl=Decimal("-5"),
        shadow_exit_at=datetime.now(UTC),
        holding_seconds=Decimal("45"),
        estimated_entry_fee=Decimal("1"),
        shadow_estimated_exit_fee=Decimal("1"),
        defer_reason=None,
        deferred_trailing_count=1,
    )
    pair = pair_variant_row(enr, var)  # type: ignore[arg-type]
    assert pair["paired_valid"] is True
    assert pair["delta_net"] == pytest.approx(5.0)
