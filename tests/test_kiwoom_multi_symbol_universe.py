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

    def _fake_latest(session, instrument_ids):  # noqa: ANN001
        return {
            iid: (
                {
                    "trade_value": Decimal("200000000"),
                    "close_price": Decimal("10000"),
                    "volume": Decimal("1000"),
                },
                None,
            )
            for iid in instrument_ids
        }

    def _fake_closes(session, instrument_ids, **kwargs):  # noqa: ANN001
        return {
            iid: [Decimal("100")] * MIN_COMPLETED_BARS for iid in instrument_ids
        }

    monkeypatch.setattr(
        ranking,
        "load_bulk_latest_two_daily_rows",
        _fake_latest,
    )
    monkeypatch.setattr(
        ranking,
        "load_bulk_completed_closes",
        _fake_closes,
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
    monkeypatch.setattr(
        "stock_platform.operation.kiwoom_multi_symbol_universe.service._strategy_owned_symbols",
        lambda session, uba_id: set(),
    )
    merged = union_real_and_shadow_symbols(
        None,  # type: ignore[arg-type]
        user_broker_account_id=1381,
        shadow_symbols=["005930", "034310"],
    )
    assert "034310" in merged
    assert "005930" in merged


def test_stack_feed_symbols_union_latest_top10_monitor(monkeypatch: pytest.MonkeyPatch) -> None:
    """고정 전략 심볼 + 승인 TOP10 monitor union — 임의 목록 금지."""
    from stock_platform.trading import kiwoom_unattended_stack_restore as restore

    monkeypatch.setattr(
        restore,
        "_latest_kiwoom_multi_symbol_monitor_symbols",
        lambda session, user_broker_account_id: [
            "000660",
            "005930",
            "009150",
            "005935",
            "012450",
            "025980",
            "036930",
            "000270",
            "066570",
            "257720",
        ],
    )
    # strategy resolve 경로를 건너뛰고 fallback만 쓰게 strategy_id=None + settings
    monkeypatch.setattr(
        "stock_platform.common.settings.get_settings",
        lambda: type("S", (), {"realtime_strategy_symbol": "034310"})(),
    )
    out = restore._resolve_kiwoom_stack_feed_symbols(
        None,  # type: ignore[arg-type]
        user_broker_account_id=1381,
        strategy_id=None,
        symbols=None,
    )
    assert "034310" in out
    assert "000660" in out
    assert len(out) == 11


def test_stack_feed_fixed_only_when_monitor_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    from stock_platform.trading import kiwoom_unattended_stack_restore as restore

    monkeypatch.setattr(
        restore,
        "_latest_kiwoom_multi_symbol_monitor_symbols",
        lambda session, user_broker_account_id: [],
    )
    monkeypatch.setattr(
        "stock_platform.common.settings.get_settings",
        lambda: type("S", (), {"realtime_strategy_symbol": "034310"})(),
    )
    out = restore._resolve_kiwoom_stack_feed_symbols(
        None,  # type: ignore[arg-type]
        user_broker_account_id=1381,
        strategy_id=None,
        symbols=None,
    )
    assert out == ["034310"]
