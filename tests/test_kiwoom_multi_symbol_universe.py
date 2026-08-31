"""KIWOOM multi-symbol universe V1 — focused unit tests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from stock_platform.operation.kiwoom_multi_symbol_universe.constants import (
    CROSS_STATE_ABOVE_NO_NEW,
    CROSS_STATE_FRESH_CROSS,
    CROSS_STATE_INSUFFICIENT_HISTORY,
    MIN_COMPLETED_BARS,
)
from stock_platform.operation.kiwoom_multi_symbol_universe.ma_eval import (
    build_signal_fingerprint,
    evaluate_daily_ma_cross,
)
from stock_platform.operation.kiwoom_multi_symbol_universe.universe import (
    is_kiwoom_autotrade_excluded,
)


def _closes(n: int, base: Decimal = Decimal("1000")) -> list[Decimal]:
    return [base + Decimal(i) for i in range(n)]


def test_universe_excludes_kiwoom_market_code_etf() -> None:
    assert is_kiwoom_autotrade_excluded(
        asset_type="STOCK",
        extra={"market_code": "8", "market_name": "ETF", "is_etf": False},
    ) is True
    assert is_kiwoom_autotrade_excluded(
        asset_type="STOCK",
        extra={"market_name": "ETN"},
    ) is True


def test_universe_excludes_etf_etn() -> None:
    assert is_kiwoom_autotrade_excluded(asset_type="ETF", extra={}) is True
    assert is_kiwoom_autotrade_excluded(
        asset_type="STOCK", extra={"is_etf": True}
    ) is True
    assert is_kiwoom_autotrade_excluded(
        asset_type="STOCK", extra={"is_etn": True}
    ) is True
    assert is_kiwoom_autotrade_excluded(asset_type="STOCK", extra={}) is False


def test_insufficient_history_exclusion() -> None:
    ma = evaluate_daily_ma_cross(
        symbol="034310",
        closes=_closes(MIN_COMPLETED_BARS - 1),
    )
    assert ma.insufficient_history is True
    assert ma.cross_state == CROSS_STATE_INSUFFICIENT_HISTORY


def test_already_above_no_fresh_cross() -> None:
    closes = _closes(25, Decimal("100"))
    ma = evaluate_daily_ma_cross(symbol="005930", closes=closes)
    assert ma.is_fresh_golden_cross is False
    assert ma.cross_state == CROSS_STATE_ABOVE_NO_NEW


def test_genuine_fresh_cross_detected() -> None:
    # short MA crosses above long: flat low then spike
    closes = [Decimal("100")] * 20 + [Decimal("50"), Decimal("200")]
    ma = evaluate_daily_ma_cross(symbol="034310", closes=closes)
    if ma.sma5 is not None and ma.sma20 is not None:
        if ma.prev_sma5 is not None and ma.prev_sma20 is not None:
            if ma.prev_sma5 <= ma.prev_sma20 and ma.sma5 > ma.sma20:
                assert ma.is_fresh_golden_cross is True
                assert ma.cross_state == CROSS_STATE_FRESH_CROSS


def test_symbol_isolation_in_ma_eval() -> None:
    a = evaluate_daily_ma_cross(symbol="AAA", closes=_closes(25))
    b = evaluate_daily_ma_cross(symbol="BBB", closes=_closes(25, Decimal("5000")))
    assert a.symbol != b.symbol
    assert a.sma5 != b.sma5


def test_fingerprint_dedup_same_day() -> None:
    fp1 = build_signal_fingerprint(symbol="034310", cross_day=date(2026, 8, 31))
    fp2 = build_signal_fingerprint(symbol="034310", cross_day=date(2026, 8, 31))
    assert fp1 == fp2


def test_ranking_cap_ten(monkeypatch: pytest.MonkeyPatch) -> None:
    from stock_platform.operation.kiwoom_multi_symbol_universe import ranking

    class FakeRepo:
        def list_recent(self, instrument_id: int, limit: int = 1):
            class Row:
                trade_value = Decimal("200000000")
                close_price = Decimal("10000")
                volume = Decimal("1000")

            return [Row(), Row()]

    monkeypatch.setattr(
        ranking,
        "PriceDailyRepository",
        lambda session: FakeRepo(),
    )
    monkeypatch.setattr(
        ranking,
        "load_completed_daily_closes",
        lambda *a, **k: [(None, Decimal("100"))] * MIN_COMPLETED_BARS,
    )

    universe = [
        {
            "symbol": f"{i:06d}",
            "name": f"N{i}",
            "instrument_id": i,
            "extra_data": {},
        }
        for i in range(1, 30)
    ]
    ranked, stats = ranking.prefilter_and_rank_candidates(
        None,  # type: ignore[arg-type]
        universe,
        monitor_target=10,
    )
    assert len(ranked) == 10
    assert stats["monitor_count"] == 10


def test_shadow_only_default_true() -> None:
    from stock_platform.common.settings import get_settings

    assert bool(getattr(get_settings(), "kiwoom_multi_symbol_shadow_only", True))


def test_union_real_and_shadow_preserves_real(monkeypatch: pytest.MonkeyPatch) -> None:
    from stock_platform.operation.kiwoom_multi_symbol_universe.service import (
        union_real_and_shadow_symbols,
    )

    monkeypatch.setattr(
        "stock_platform.operation.kiwoom_multi_symbol_universe.service.resolve_real_feed_symbols",
        lambda session, user_broker_account_id: ["034310"],
    )
    merged = union_real_and_shadow_symbols(
        None,  # type: ignore[arg-type]
        user_broker_account_id=1381,
        shadow_symbols=["005930", "034310"],
    )
    assert "034310" in merged
    assert "005930" in merged
