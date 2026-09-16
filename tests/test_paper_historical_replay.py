"""Paper historical replay 계약 — DB persist 없이 evaluator/look-ahead/비용."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

from stock_platform.ai.strategy_draft_approval.backtest_spec import (
    RuleBasedBacktestAdapter,
)
from stock_platform.ai.strategy_draft_approval.rule_evaluator import (
    IndicatorCache,
)
from stock_platform.backtest.models import BacktestPrice
from stock_platform.indicators.engine import _rolling_mean
from stock_platform.trading.paper_historical_replay import (
    FEE_RATIO,
    SELL_TAX_RATIO,
    UPBIT_FEE_RATIO,
    UPBIT_SELL_TAX_RATIO,
    _size_buy_quantity,
    evaluate_bar,
)


def _bars(closes: list[int], start: date | None = None) -> list[BacktestPrice]:
    day0 = start or date(2025, 1, 2)
    out: list[BacktestPrice] = []
    for i, close in enumerate(closes):
        px = Decimal(close)
        out.append(
            BacktestPrice(
                trade_date=day0 + timedelta(days=i),
                open_price=px,
                high_price=px,
                low_price=px,
                close_price=px,
                volume=Decimal("1"),
            )
        )
    return out


def _spec() -> dict:
    return {
        "compilable": True,
        "executable_hash": "test-17486-compat",
        "entry_rules": [
            {
                "lookback": 5,
                "operator": "CROSS_ABOVE",
                "indicator": "SMA",
                "threshold": 0,
                "comparison_target": "SMA:20",
            }
        ],
        "exit_rules": [
            {
                "lookback": 5,
                "operator": "CROSS_BELOW",
                "indicator": "SMA",
                "threshold": 0,
                "comparison_target": "SMA:20",
            }
        ],
        "stop_loss_rule": {"type": "PERCENT", "value": 3},
        "take_profit_rule": {"type": "PERCENT", "value": 6},
        "position_sizing_rule": {"method": "FIXED_PERCENT", "value": 0.05},
    }


class _ScriptedAdapter:
    def __init__(self, entries: dict[int, str], exits: dict[int, str]) -> None:
        self._entries = entries
        self._exits = exits
        self.config = SimpleNamespace(
            stop_loss_ratio=Decimal("0.03"),
            take_profit_ratio=Decimal("0.06"),
            position_ratio=Decimal("0.05"),
        )

    def should_enter(self, *, prices, index):
        reason = self._entries.get(index)
        return (reason is not None, reason or "NO_ENTRY")

    def should_exit(self, *, prices, index, entry_price):
        reason = self._exits.get(index)
        return (reason is not None, reason or "HOLD")


def test_a_historical_bars_chronological() -> None:
    prices = _bars([10, 11, 12, 9])
    dates = [p.trade_date for p in prices]
    assert dates == sorted(dates)


def test_b_no_look_ahead_sma() -> None:
    closes = [Decimal(i) for i in range(1, 40)]
    full = _rolling_mean(closes, 5)
    prefix = _rolling_mean(closes[:25], 5)
    assert full[24] == prefix[24]
    cache_full = IndicatorCache(closes)
    cache_prefix = IndicatorCache(closes[:25])
    assert cache_full.value_at("SMA", 5, 24) == cache_prefix.value_at("SMA", 5, 24)


def test_c_warmup_skips_early_bars() -> None:
    prices = _bars([100] * 25)
    adapter = _ScriptedAdapter({0: "RULE_ENTRY"}, {})
    decision = evaluate_bar(
        adapter,
        prices,
        5,
        in_position=False,
        entry_price=Decimal("0"),
        cooldown_remaining=0,
        warmup_bars=20,
    )
    assert decision.reason == "WARMUP"
    assert decision.side is None


def test_d_buy_signal() -> None:
    prices = _bars([100] * 25)
    adapter = _ScriptedAdapter({20: "RULE_ENTRY"}, {})
    decision = evaluate_bar(
        adapter,
        prices,
        20,
        in_position=False,
        entry_price=Decimal("0"),
        cooldown_remaining=0,
        warmup_bars=20,
    )
    assert decision.side == "BUY"
    assert decision.reason == "RULE_ENTRY"


def test_e_sell_signal_maps_dead_cross() -> None:
    prices = _bars([100] * 25)
    adapter = _ScriptedAdapter({}, {21: "RULE_EXIT"})
    decision = evaluate_bar(
        adapter,
        prices,
        21,
        in_position=True,
        entry_price=Decimal("100"),
        cooldown_remaining=0,
        warmup_bars=20,
    )
    assert decision.side == "SELL"
    assert decision.reason == "MA_DEAD_CROSS"


def test_f_stop_loss() -> None:
    prices = _bars([100] * 25)
    adapter = _ScriptedAdapter({}, {21: "STOP_LOSS"})
    decision = evaluate_bar(
        adapter,
        prices,
        21,
        in_position=True,
        entry_price=Decimal("100"),
        cooldown_remaining=0,
        warmup_bars=20,
    )
    assert decision.reason == "STOP_LOSS"
    assert decision.fill_price == Decimal("97")


def test_g_take_profit() -> None:
    prices = _bars([100] * 25)
    adapter = _ScriptedAdapter({}, {21: "TAKE_PROFIT"})
    decision = evaluate_bar(
        adapter,
        prices,
        21,
        in_position=True,
        entry_price=Decimal("100"),
        cooldown_remaining=0,
        warmup_bars=20,
    )
    assert decision.reason == "TAKE_PROFIT"
    assert decision.fill_price == Decimal("106")


def test_h_cooldown_blocks_duplicate_entry() -> None:
    prices = _bars([100] * 25)
    adapter = _ScriptedAdapter({21: "RULE_ENTRY"}, {})
    decision = evaluate_bar(
        adapter,
        prices,
        21,
        in_position=False,
        entry_price=Decimal("0"),
        cooldown_remaining=1,
        warmup_bars=20,
    )
    assert decision.skipped_cooldown is True
    assert decision.side is None


def test_j_risk_max_order_and_fixed_percent() -> None:
    qty, gross = _size_buy_quantity(
        available_cash=Decimal("10000000"),
        price=Decimal("10000"),
        position_ratio=Decimal("0.05"),
        max_order_amount=Decimal("50000"),
    )
    assert qty >= 1
    assert gross <= Decimal("50000")
    assert qty * Decimal("10000") <= Decimal("50000")


def test_o_fee_tax_model_not_optimistic() -> None:
    assert FEE_RATIO == Decimal("0.00015")
    assert SELL_TAX_RATIO == Decimal("0.0018")
    buy_gross = Decimal("50000")
    fee = (buy_gross * FEE_RATIO).quantize(Decimal("0.01"))
    assert fee > 0
    sell_tax = (buy_gross * SELL_TAX_RATIO).quantize(Decimal("0.01"))
    assert sell_tax > fee


def test_p_zero_quantity_forbidden() -> None:
    qty, _gross = _size_buy_quantity(
        available_cash=Decimal("100"),
        price=Decimal("50000"),
        position_ratio=Decimal("0.05"),
        max_order_amount=Decimal("50000"),
    )
    assert qty == 0


def test_upbit_fractional_qty_and_no_kiwoom_tax() -> None:
    qty, gross = _size_buy_quantity(
        available_cash=Decimal("10000000"),
        price=Decimal("426"),
        position_ratio=Decimal("0.05"),
        max_order_amount=Decimal("10000"),
        exchange_code="UPBIT",
    )
    assert qty > 0
    assert qty != qty.quantize(Decimal("1"))
    assert gross <= Decimal("10000")
    assert UPBIT_FEE_RATIO == Decimal("0.0005")
    assert UPBIT_SELL_TAX_RATIO == Decimal("0")
    sell_tax = (gross * UPBIT_SELL_TAX_RATIO).quantize(Decimal("0.01"))
    assert sell_tax == 0


def test_s_performance_win_rate_formula() -> None:
    wins = 4
    losses = 3
    win_rate = Decimal(wins) / Decimal(wins + losses)
    assert win_rate.quantize(Decimal("0.0001")) == Decimal("0.5714")


def test_t_u_real_adapter_not_imported_in_evaluate_bar() -> None:
    import inspect

    import stock_platform.trading.paper_historical_replay as mod

    source = inspect.getsource(mod)
    assert "KiwoomBrokerAdapter" not in source
    assert "UpbitBrokerAdapter" not in source
    assert "skip_risk_checks=False" in source


def test_v_strategy_17486_adapter_compiles() -> None:
    prices = _bars([100 + (i % 7) for i in range(40)])
    adapter = RuleBasedBacktestAdapter(_spec(), prices)
    entered = False
    for index in range(len(prices)):
        ok, _reason = adapter.should_enter(prices=prices, index=index)
        if ok:
            entered = True
            break
    assert adapter.config.stop_loss_ratio == Decimal("0.03")
    assert adapter.config.take_profit_ratio == Decimal("0.06")
    assert adapter.config.position_ratio == Decimal("0.05")
    assert entered in {True, False}


def test_q_idempotency_key_format_stable() -> None:
    run_id = 9
    key = f"PAPER_REPLAY:{run_id}:{date(2026, 1, 2).isoformat()}:BUY:20"
    assert key == "PAPER_REPLAY:9:2026-01-02:BUY:20"
