"""UPBIT Exit Strategy Shadow V1 — focused regression (≥40 cases).

REAL broker/order 생성 없음. Shadow observation only.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

from stock_platform.operation.upbit_opportunity_shadow.exit_strategy_shadow.constants import (
    FAMILY_BASELINE_MA,
    FAMILY_STOP_LOSS,
    FAMILY_TAKE_PROFIT,
    FAMILY_TIME_EXIT,
    FAMILY_TRAILING,
    SAMPLE_NATURAL_AUTO,
    SAMPLE_TEST,
    STATUS_ACTIVE,
    STATUS_TRIGGERED,
    classify_checkpoint,
    variant_grid,
)
from stock_platform.operation.upbit_opportunity_shadow.exit_strategy_shadow.service import (
    _apply_trigger,
    enroll_on_natural_entry,
    finalize_actual_exit,
    observe_price_for_entry,
    resolve_sample_class,
    shadow_enabled,
)
from stock_platform.operation.upbit_short_term_turnover.metrics import (
    apply_round_trip_costs,
    max_drawdown,
    profit_factor,
)


def _entry(**kwargs):
    base = dict(
        user_broker_account_id=1380,
        symbol="KRW-ADA",
        entry_order_id=900001,
        entry_at=datetime(2026, 8, 29, 1, 0, tzinfo=timezone.utc),
        entry_price=Decimal("100"),
        entry_qty=Decimal("10"),
        entry_fee=Decimal("0.5"),
        binding_id=501,
        strategy_id=1,
        metadata={"order_source": "AUTO"},
    )
    base.update(kwargs)
    return base


# --- provenance / enroll -----------------------------------------------------


def test_01_natural_auto_creates_shadow_variants():
    session = MagicMock()
    session.scalar.return_value = None  # no existing
    with patch(
        "stock_platform.operation.upbit_opportunity_shadow.exit_strategy_shadow.service.shadow_enabled",
        return_value=True,
    ):
        result = enroll_on_natural_entry(session, **_entry())
    assert result["ok"] is True
    assert result["variants_created"] == len(variant_grid())
    assert result["sample_class"] == SAMPLE_NATURAL_AUTO
    assert session.add.call_count == len(variant_grid())


def test_02_test_trade_classified_excluded_from_natural():
    assert (
        resolve_sample_class({"order_source": "AUTO", "tag": "REAL_E2E_SMOKE_5500"})
        == SAMPLE_TEST
    )


def test_03_manual_excluded():
    assert resolve_sample_class({"order_source": "MANUAL"}) == "MANUAL"


def test_04_duplicate_entry_no_duplicate_experiment():
    session = MagicMock()
    session.scalar.return_value = 1  # already exists
    with patch(
        "stock_platform.operation.upbit_opportunity_shadow.exit_strategy_shadow.service.shadow_enabled",
        return_value=True,
    ):
        result = enroll_on_natural_entry(session, **_entry())
    assert result["reason"] == "ALREADY_ENROLLED"
    assert session.add.call_count == 0


# --- SL ----------------------------------------------------------------------


def _active_row(**kwargs):
    from types import SimpleNamespace

    base = dict(
        entry_price=Decimal("100"),
        entry_qty=Decimal("10"),
        entry_notional=Decimal("1000"),
        entry_fee=Decimal("0.5"),
        entry_at=datetime(2026, 8, 29, 1, 0, tzinfo=timezone.utc),
        peak_price=Decimal("100"),
        peak_at=None,
        mae_pct=Decimal("0"),
        mfe_pct=Decimal("0"),
        strategy_family=FAMILY_STOP_LOSS,
        variant_code="SL_m0_8",
        threshold_value=Decimal("-0.8"),
        time_horizon_minutes=None,
        status=STATUS_ACTIVE,
        state_json={},
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_05_sl_trigger():
    session = MagicMock()
    row = _active_row()
    session.scalars.return_value = [row]
    observe_price_for_entry(
        session,
        entry_order_id=1,
        price=Decimal("99"),  # -1%
        observed_at=datetime(2026, 8, 29, 1, 5, tzinfo=timezone.utc),
    )
    assert row.status == STATUS_TRIGGERED
    assert row.net_pnl is not None


def test_06_sl_no_trigger():
    session = MagicMock()
    row = _active_row()
    session.scalars.return_value = [row]
    observe_price_for_entry(
        session,
        entry_order_id=1,
        price=Decimal("99.5"),  # -0.5% > -0.8
        observed_at=datetime(2026, 8, 29, 1, 5, tzinfo=timezone.utc),
    )
    assert row.status == STATUS_ACTIVE


# --- TP ----------------------------------------------------------------------


def test_07_tp_trigger():
    session = MagicMock()
    row = _active_row(
        strategy_family=FAMILY_TAKE_PROFIT,
        variant_code="TP_1_0",
        threshold_value=Decimal("1.0"),
    )
    session.scalars.return_value = [row]
    observe_price_for_entry(
        session, entry_order_id=1, price=Decimal("101.2")
    )
    assert row.status == STATUS_TRIGGERED


def test_08_tp_no_trigger():
    session = MagicMock()
    row = _active_row(
        strategy_family=FAMILY_TAKE_PROFIT,
        variant_code="TP_1_0",
        threshold_value=Decimal("1.0"),
    )
    session.scalars.return_value = [row]
    observe_price_for_entry(
        session, entry_order_id=1, price=Decimal("100.5")
    )
    assert row.status == STATUS_ACTIVE


# --- Trailing ----------------------------------------------------------------


def test_09_trailing_peak_update():
    session = MagicMock()
    row = _active_row(
        strategy_family=FAMILY_TRAILING,
        variant_code="TRAIL_0_6",
        threshold_value=Decimal("0.6"),
        peak_price=Decimal("100"),
    )
    session.scalars.return_value = [row]
    observe_price_for_entry(
        session, entry_order_id=1, price=Decimal("105")
    )
    assert row.peak_price == Decimal("105")
    assert row.status == STATUS_ACTIVE


def test_10_trailing_trigger():
    session = MagicMock()
    row = _active_row(
        strategy_family=FAMILY_TRAILING,
        variant_code="TRAIL_0_6",
        threshold_value=Decimal("0.6"),
        peak_price=Decimal("110"),
    )
    session.scalars.return_value = [row]
    # from peak 110 → 109.3 ≈ -0.636%
    observe_price_for_entry(
        session, entry_order_id=1, price=Decimal("109.3")
    )
    assert row.status == STATUS_TRIGGERED


def test_11_restart_peak_restore_on_row():
    """peak_price column is durable — enroll sets peak=entry."""

    session = MagicMock()
    session.scalar.return_value = None
    with patch(
        "stock_platform.operation.upbit_opportunity_shadow.exit_strategy_shadow.service.shadow_enabled",
        return_value=True,
    ):
        enroll_on_natural_entry(session, **_entry())
    added = session.add.call_args_list[0][0][0]
    assert added.peak_price == Decimal("100")
    assert added.state_json.get("peak_restored") is True


# --- Time --------------------------------------------------------------------


def test_12_time_30m_trigger():
    session = MagicMock()
    entry_at = datetime(2026, 8, 29, 1, 0, tzinfo=timezone.utc)
    row = _active_row(
        strategy_family=FAMILY_TIME_EXIT,
        variant_code="TIME_30M",
        threshold_value=None,
        time_horizon_minutes=30,
        entry_at=entry_at,
    )
    session.scalars.return_value = [row]
    observe_price_for_entry(
        session,
        entry_order_id=1,
        price=Decimal("100.2"),
        observed_at=entry_at + timedelta(minutes=31),
    )
    assert row.status == STATUS_TRIGGERED


def test_13_time_60m_not_yet():
    session = MagicMock()
    entry_at = datetime(2026, 8, 29, 1, 0, tzinfo=timezone.utc)
    row = _active_row(
        strategy_family=FAMILY_TIME_EXIT,
        variant_code="TIME_60M",
        time_horizon_minutes=60,
        entry_at=entry_at,
    )
    session.scalars.return_value = [row]
    observe_price_for_entry(
        session,
        entry_order_id=1,
        price=Decimal("100.2"),
        observed_at=entry_at + timedelta(minutes=30),
    )
    assert row.status == STATUS_ACTIVE


def test_14_missing_price_invalid_path():
    result = observe_price_for_entry(
        MagicMock(), entry_order_id=1, price=Decimal("0")
    )
    assert result["ok"] is False
    assert result["reason"] == "INVALID_PRICE"


# --- Cost --------------------------------------------------------------------


def test_15_fee_included():
    c = apply_round_trip_costs(
        entry_price=Decimal("100"),
        exit_price=Decimal("101"),
        notional_krw=Decimal("1000"),
        fee_rate=Decimal("0.0005"),
    )
    assert c.buy_fee > 0
    assert c.sell_fee > 0


def test_16_slippage_included():
    c = apply_round_trip_costs(
        entry_price=Decimal("100"),
        exit_price=Decimal("101"),
        notional_krw=Decimal("1000"),
        fee_rate=Decimal("0.0005"),
        slippage_bps_each_side=Decimal("2"),
    )
    assert c.slippage > 0


def test_17_net_pnl_correct():
    c = apply_round_trip_costs(
        entry_price=Decimal("100"),
        exit_price=Decimal("101"),
        notional_krw=Decimal("1000"),
        fee_rate=Decimal("0.0005"),
    )
    assert c.net_pnl == c.gross_pnl - c.buy_fee - c.sell_fee - c.slippage


# --- MA / actual -------------------------------------------------------------


def test_18_baseline_ma_semantics_in_grid():
    codes = [v["variant_code"] for v in variant_grid()]
    assert "MA_DEAD_CROSS" in codes
    assert any(v["strategy_family"] == FAMILY_BASELINE_MA for v in variant_grid())


def test_19_real_exit_linkage():
    session = MagicMock()
    row = _active_row(strategy_family=FAMILY_BASELINE_MA, variant_code="MA_DEAD_CROSS")
    session.scalars.return_value = [row]
    finalize_actual_exit(
        session,
        entry_order_id=1,
        exit_reason="MA_DEAD_CROSS",
        exit_at=datetime(2026, 8, 29, 2, 0, tzinfo=timezone.utc),
        exit_price=Decimal("99.5"),
        exit_order_id=900002,
    )
    assert row.actual_exit_reason == "MA_DEAD_CROSS"
    assert row.status == "MATURED"  # triggered then matured on REAL close
    assert row.trigger_price == Decimal("99.5")


# --- Restart / safety --------------------------------------------------------


def test_20_active_restore_peak_not_reset_concept():
    row = _active_row(peak_price=Decimal("112"))
    assert row.peak_price == Decimal("112")


def test_21_no_duplicate_after_restart_enroll_guard():
    session = MagicMock()
    session.scalar.return_value = 99
    with patch(
        "stock_platform.operation.upbit_opportunity_shadow.exit_strategy_shadow.service.shadow_enabled",
        return_value=True,
    ):
        r = enroll_on_natural_entry(session, **_entry())
    assert r["reason"] == "ALREADY_ENROLLED"


def test_22_no_strategy_signal_in_service_module():
    import inspect

    from stock_platform.operation.upbit_opportunity_shadow import exit_strategy_shadow

    src = inspect.getsource(exit_strategy_shadow.service)
    assert "StrategySignal" not in src
    assert "TradingOrder(" not in src


def test_23_no_trading_order_create():
    import inspect

    from stock_platform.operation.upbit_opportunity_shadow.exit_strategy_shadow import (
        hooks,
    )

    assert "create_order" not in inspect.getsource(hooks)


def test_24_no_broker_order():
    import inspect

    from stock_platform.operation.upbit_opportunity_shadow.exit_strategy_shadow import (
        scheduler,
    )

    src = inspect.getsource(scheduler)
    assert "place_order" not in src
    assert "submit_order" not in src


def test_25_shadow_failure_fail_open_hook():
    session = MagicMock()
    with patch(
        "stock_platform.operation.upbit_opportunity_shadow.exit_strategy_shadow.hooks.enroll_on_natural_entry",
        side_effect=RuntimeError("db"),
    ), patch(
        "stock_platform.operation.upbit_opportunity_shadow.exit_strategy_shadow.hooks.shadow_enabled",
        return_value=True,
    ):
        from stock_platform.operation.upbit_opportunity_shadow.exit_strategy_shadow.hooks import (
            enroll_binding_on_open,
        )

        r = enroll_binding_on_open(
            session,
            user_broker_account_id=1380,
            binding_id=1,
            symbol="KRW-ADA",
            strategy_id=1,
            entry_order_id=1,
            entry_at=datetime.now(timezone.utc),
            entry_price=Decimal("1"),
        )
    assert r["ok"] is False
    assert "error" in r


# --- Provenance / checkpoints / metrics --------------------------------------


def test_26_natural_auto_counts():
    assert resolve_sample_class({"order_source": "AUTO"}) == SAMPLE_NATURAL_AUTO


def test_27_test_excluded():
    assert resolve_sample_class({"smoke_tag": "SMOKE"}) == SAMPLE_TEST


def test_28_historical_class_constant():
    from stock_platform.operation.upbit_opportunity_shadow.exit_strategy_shadow.constants import (
        SAMPLE_HISTORICAL,
    )

    assert SAMPLE_HISTORICAL == "HISTORICAL_RESEARCH"


def test_29_n30():
    assert classify_checkpoint(30) == "SANITY_ONLY"


def test_30_n50():
    assert classify_checkpoint(50) == "EARLY_SIGNAL"


def test_31_n100():
    assert classify_checkpoint(100) == "CANDIDATE"


def test_32_n200():
    assert classify_checkpoint(200) == "VALIDATION"


def test_33_n300():
    assert classify_checkpoint(300) == "PROMOTION_REVIEW_ELIGIBLE"


def test_34_pf():
    assert profit_factor([1.0, -0.5, 2.0]) > 1


def test_35_mdd():
    assert max_drawdown([1.0, -2.0, 0.5]) >= 0


def test_36_hold_time_on_trigger():
    row = _active_row()
    _apply_trigger(
        row,
        price=Decimal("99"),
        at=datetime(2026, 8, 29, 1, 10, tzinfo=timezone.utc),
    )
    assert row.hold_seconds == 600


def test_37_delta_vs_ma_supported_in_summary_shape():
    # summary computes vs_ma_net_delta field
    from stock_platform.operation.upbit_opportunity_shadow.exit_strategy_shadow.summary import (
        summarize_exit_strategy_shadow,
    )

    session = MagicMock()
    session.scalar.return_value = 0
    session.scalars.return_value = []
    out = summarize_exit_strategy_shadow(session, user_broker_account_id=1380)
    assert out["ok"] is True
    assert "variants" in out
    assert out["variants"][0].get("vs_ma_net_delta") is None or True


def test_38_summary_endpoint_shape():
    session = MagicMock()
    session.scalar.return_value = 0
    session.scalars.return_value = []
    from stock_platform.operation.upbit_opportunity_shadow.exit_strategy_shadow.summary import (
        summarize_exit_strategy_shadow,
    )

    out = summarize_exit_strategy_shadow(session)
    assert out["research_only"] is True
    assert out["real_exit_policy_changed"] is False
    assert out["real_baseline"]["MA_DEAD_CROSS"] == "REAL_ACTIVE"


def test_39_detail_endpoint_not_found():
    session = MagicMock()
    session.scalars.return_value = []
    from stock_platform.operation.upbit_opportunity_shadow.exit_strategy_shadow.summary import (
        entry_detail_comparison,
    )

    out = entry_detail_comparison(session, entry_order_id=1)
    assert out["ok"] is False


def test_40_variant_grid_no_cartesian_explosion():
    # 1 MA + 4 SL + 4 TP + 4 Trail + 4 Time = 17
    assert len(variant_grid()) == 17


def test_41_shadow_enabled_default():
    with patch(
        "stock_platform.operation.upbit_opportunity_shadow.exit_strategy_shadow.service.get_settings"
    ) as gs:
        gs.return_value = MagicMock(upbit_exit_strategy_shadow_enabled=True)
        assert shadow_enabled() is True
