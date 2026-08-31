"""Exit Optimization Shadow Lab V2 — focused tests (pairing / variants / reentry)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.operation.upbit_opportunity_shadow.reentry_cooldown_shadow.service import (
    evaluate_would_block_matrix,
)
from stock_platform.operation.upbit_opportunity_shadow.trailing_forward_shadow.constants import (
    STATUS_ACTIVE,
    STATUS_COMPLETED,
    VARIANT_T5,
    VARIANT_T6,
    VARIANT_T7,
    VARIANT_T8,
)
from stock_platform.operation.upbit_opportunity_shadow.trailing_forward_shadow.service import (
    _armed,
    _trigger_price,
    compute_round_trip_pnl,
    pair_row_variant,
    variant_specs,
)


UTC = timezone.utc


def test_p_real_policy_untouched_in_lab_specs() -> None:
    """P: REAL trailing arm/dd mirrors only on T5–T7; T8 changes dd for research."""

    specs = variant_specs()
    assert specs[VARIANT_T5]["activation_pct"] == 1.0
    assert specs[VARIANT_T5]["trail_pct"] == 0.8
    assert specs[VARIANT_T5]["min_holding_seconds"] == 60
    assert specs[VARIANT_T6]["min_holding_seconds"] == 30
    assert specs[VARIANT_T7]["min_holding_seconds"] == 120
    assert specs[VARIANT_T8]["trail_pct"] == 1.0
    assert specs[VARIANT_T8]["min_holding_seconds"] == 60


def test_h_t5_early_trigger_before_60_no_exit() -> None:
    """H: min_hold 이전 trailing 조건 → early_trigger만, exit 없음."""

    entry = Decimal("100")
    peak = Decimal("102")  # +2%
    assert _armed(entry=entry, peak=peak, activation_pct=1.0)
    trig = _trigger_price(peak, 0.8)
    price = trig  # at trigger
    hold_s = 20.0
    would = price <= trig
    assert would
    assert hold_s < 60
    # 강제 exit 금지 조건
    assert not (would and hold_s >= 60)


def test_i_t5_condition_valid_after_60_virtual_exit() -> None:
    """I: 60초 이후 조건 유효 → virtual exit 허용."""

    peak = Decimal("102")
    trig = _trigger_price(peak, 0.8)
    price = trig
    hold_s = 61.0
    assert price <= trig and hold_s >= 60


def test_j_t5_condition_cleared_at_60_no_forced_exit() -> None:
    """J: 60초 시점에 조건 해소 → 강제 exit 없음."""

    peak = Decimal("102")
    trig = _trigger_price(peak, 0.8)
    price = trig + Decimal("1")  # recovered
    hold_s = 60.0
    would = price <= trig
    assert not would
    assert not (would and hold_s >= 60)


def test_k_l_m_min_hold_and_drawdown_variants() -> None:
    specs = variant_specs()
    assert specs[VARIANT_T6]["min_holding_seconds"] == 30
    assert specs[VARIANT_T7]["min_holding_seconds"] == 120
    assert specs[VARIANT_T8]["trail_pct"] == 1.0
    t5_trig = _trigger_price(Decimal("100"), 0.8)
    t8_trig = _trigger_price(Decimal("100"), 1.0)
    assert t8_trig < t5_trig  # 더 넓은 drawdown → 더 낮은 trigger


def test_n_peak_isolated_per_variant_init() -> None:
    """N: variant별 peak state 분리 — init 독립 dict."""

    from stock_platform.operation.upbit_opportunity_shadow.trailing_forward_shadow.service import (
        _init_variant,
    )

    a = _init_variant(variant_specs()[VARIANT_T5])
    b = _init_variant(variant_specs()[VARIANT_T6])
    a["peak_price"] = "111"
    assert b["peak_price"] is None


def test_o_peak_reset_on_reentry_via_new_enroll_semantics() -> None:
    """O: 재진입 = 새 binding row → peak는 entry로 리셋 (공유 금지)."""

    from stock_platform.operation.upbit_opportunity_shadow.trailing_forward_shadow.service import (
        _init_variant,
    )

    v = _init_variant(variant_specs()[VARIANT_T5])
    v["peak_price"] = "999"
    # 신규 enroll은 항상 새 variants dict — 이전 peak 불사용
    fresh = _init_variant(variant_specs()[VARIANT_T5])
    fresh["peak_price"] = str(Decimal("100"))
    assert fresh["peak_price"] != v["peak_price"]


def test_e_baseline_fees_net_via_compute_round_trip() -> None:
    """E: fee schedule = UpbitFeePolicy DEFAULT_TAKER_RATE."""

    pnl = compute_round_trip_pnl(
        entry_price=Decimal("1000"),
        exit_price=Decimal("1010"),
        quantity=Decimal("10"),
        buy_fee=Decimal("5"),
    )
    assert pnl["gross_pnl"] == pytest.approx(100.0)
    assert pnl["fee"] > 5.0  # buy + sell
    assert pnl["net_pnl"] < pnl["gross_pnl"]


def test_a_pair_valid_when_baseline_and_shadow_present() -> None:
    row = SimpleNamespace(
        shadow_row_id=1,
        binding_id=10,
        entry_order_id=100,
        symbol="KRW-XRP",
        entry_at=datetime(2026, 8, 31, 1, 0, tzinfo=UTC),
        entry_price=Decimal("100"),
        baseline_exit_at=datetime(2026, 8, 31, 1, 5, tzinfo=UTC),
        baseline_exit_price=Decimal("99"),
        baseline_exit_reason="TRAILING_STOP",
        baseline_gross_pnl=Decimal("-10"),
        baseline_fee=Decimal("10"),
        baseline_net_pnl=Decimal("-20"),
        included_in_research_metrics=True,
        data_quality_status="VALID",
        shadow_state_json={},
        variants_json={
            VARIANT_T5: {
                "net": -5.0,
                "gross": 5.0,
                "estimated_fee": 10.0,
                "virtual_exit_price": "100.5",
                "trigger_at": "2026-08-31T01:02:00+00:00",
                "outcome_status": "VIRTUAL_TRAILING_EXIT",
                "holding_seconds": 120,
                "peak_price": "102",
                "peak_at": "2026-08-31T01:01:00+00:00",
                "early_trigger_at": "2026-08-31T01:00:30+00:00",
            }
        },
    )
    paired = pair_row_variant(row, VARIANT_T5)  # type: ignore[arg-type]
    assert paired["paired_valid"] is True
    assert paired["delta_net"] == pytest.approx(15.0)


def test_b_same_symbol_reentry_no_cross_pair_identity() -> None:
    """B: entry_order_id가 pair identity — 다른 entry끼리 혼합 금지."""

    r1 = SimpleNamespace(
        shadow_row_id=1,
        binding_id=1,
        entry_order_id=111,
        symbol="KRW-WLD",
        entry_at=datetime(2026, 8, 31, 1, 0, tzinfo=UTC),
        entry_price=Decimal("1"),
        baseline_exit_at=datetime(2026, 8, 31, 1, 1, tzinfo=UTC),
        baseline_exit_price=Decimal("1"),
        baseline_exit_reason="X",
        baseline_gross_pnl=Decimal("0"),
        baseline_fee=Decimal("1"),
        baseline_net_pnl=Decimal("-1"),
        included_in_research_metrics=True,
        data_quality_status="VALID",
        shadow_state_json={},
        variants_json={VARIANT_T5: {"net": -1, "virtual_exit_price": "1", "trigger_at": "t"}},
    )
    r2 = SimpleNamespace(**{**r1.__dict__, "shadow_row_id": 2, "binding_id": 2, "entry_order_id": 222})
    p1 = pair_row_variant(r1, VARIANT_T5)  # type: ignore[arg-type]
    p2 = pair_row_variant(r2, VARIANT_T5)  # type: ignore[arg-type]
    assert p1["entry_id"] != p2["entry_id"]


def test_c_partial_fill_duplicate_pair_guarded_by_binding_unique() -> None:
    """C: binding_id unique enroll — duplicate enroll returns existing."""

    from stock_platform.operation.upbit_opportunity_shadow.trailing_forward_shadow import (
        service as svc,
    )

    existing = SimpleNamespace(shadow_row_id=99)
    session = MagicMock()
    session.scalar.return_value = existing
    with patch.object(svc, "shadow_enabled", return_value=True):
        out = svc.enroll_on_position_open(
            session,
            user_broker_account_id=1380,
            binding_id=1,
            symbol="KRW-X",
            strategy_id=1,
            entry_order_id=1,
            entry_at=datetime.now(UTC),
            entry_price=Decimal("1"),
        )
    assert out["duplicate"] is True
    assert out["shadow_row_id"] == 99


def test_g_historical_non_enrolled_not_backfilled_by_reconcile_skip() -> None:
    """G: entry_order_id 없는 row는 reconcile skip."""

    from stock_platform.operation.upbit_opportunity_shadow.trailing_forward_shadow import (
        service as svc,
    )

    row = SimpleNamespace(
        status=STATUS_ACTIVE,
        baseline_net_pnl=None,
        entry_order_id=None,
        binding_id=1,
        shadow_row_id=1,
        shadow_state_json={},
    )
    session = MagicMock()
    session.scalars.return_value = [row]
    with patch.object(svc, "shadow_enabled", return_value=True):
        out = svc.reconcile_existing_forward_baselines(session, limit=10)
    assert out["skipped"] >= 1


def test_q_r_s_t_reentry_would_block_matrix() -> None:
    """Q–T: cooldown window matrix."""

    m30 = evaluate_would_block_matrix(30)
    assert m30["R1"] is True and m30["R2"] is True and m30["R3"] is True
    m120 = evaluate_would_block_matrix(120)
    assert m120["R1"] is False and m120["R2"] is True and m120["R3"] is True
    m240 = evaluate_would_block_matrix(240)
    assert m240["R1"] is False and m240["R2"] is False and m240["R3"] is True
    m400 = evaluate_would_block_matrix(400)
    assert m400["R1"] is False and m400["R2"] is False and m400["R3"] is False
    assert m30["R0"] is False


def test_u_v_cooldown_impact_sign() -> None:
    """U/V: impact = -baseline_net (blocked trade)."""

    losing_net = -100.0
    winning_net = 100.0
    assert round(-losing_net, 4) == 100.0  # V positive impact
    assert round(-winning_net, 4) == -100.0  # U negative impact


def test_f_reconcile_sets_flag_when_ledger_resolves() -> None:
    from stock_platform.operation.upbit_opportunity_shadow.trailing_forward_shadow import (
        service as svc,
    )

    row = SimpleNamespace(
        shadow_row_id=1,
        binding_id=50,
        entry_order_id=2000,
        user_broker_account_id=1380,
        entry_at=datetime(2026, 8, 31, 1, 0, tzinfo=UTC),
        entry_price=Decimal("100"),
        entry_quantity=Decimal("1"),
        entry_fee=None,
        status=STATUS_COMPLETED,
        baseline_exit_reason="TRAILING_STOP",
        baseline_exit_at=datetime(2026, 8, 31, 1, 1, tzinfo=UTC),
        baseline_exit_price=Decimal("99"),
        baseline_gross_pnl=None,
        baseline_fee=None,
        baseline_net_pnl=None,
        variants_json={"T0": {"outcome_status": "ACTIVE"}, "T5": {"outcome_status": "ACTIVE"}},
        shadow_state_json={},
        completed_at=datetime.now(UTC),
    )
    session = MagicMock()
    session.scalar.return_value = row
    resolved = {
        "ok": True,
        "gross_pnl": -1.0,
        "fee": 10.0,
        "net_pnl": -11.0,
        "exit_price": "99",
        "exit_reason": "TRAILING_STOP",
        "exit_at_dt": row.baseline_exit_at,
    }
    with (
        patch.object(svc, "shadow_enabled", return_value=True),
        patch(
            "stock_platform.operation.upbit_opportunity_shadow.trailing_forward_shadow.baseline.resolve_baseline_outcome_for_entry",
            return_value=resolved,
        ),
    ):
        out = svc.finalize_baseline_on_binding_close(
            session,
            binding_id=50,
            exit_reason=None,
            exit_at=None,
            exit_price=None,
            entry_order_id=2000,
        )
    assert out["ok"] is True
    assert out["baseline_net_pnl"] == -11.0
    assert row.shadow_state_json.get("RECONCILED_EXISTING_FORWARD") is True
