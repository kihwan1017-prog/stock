"""WRK-017 Momentum validation unit tests."""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

from stock_platform.operation.upbit_momentum_validation.constants import (
    FROZEN_MOMENTUM,
)
from stock_platform.operation.upbit_momentum_validation.momentum_rule import (
    momentum_hit,
)
from stock_platform.operation.upbit_momentum_validation.research_candle_store import (
    connect,
    load_symbol_bars,
    upsert_rows,
)
from stock_platform.operation.upbit_positive_edge_entry.regime import MarketRegime


def test_frozen_thresholds_unchanged() -> None:
    assert FROZEN_MOMENTUM["ret15_min_pct"] == 0.25
    assert FROZEN_MOMENTUM["ret60_min_pct"] == 0.40
    assert FROZEN_MOMENTUM["volume_surge_min"] == 1.0
    assert FROZEN_MOMENTUM["ret15_max_pct"] == 3.0


def test_momentum_hit_matches_frozen_gate() -> None:
    feat = {
        "ma5": 101.0,
        "ma20": 100.0,
        "ma_sep_pct": 1.0,
        "volume_surge": 1.5,
        "rsi14": 55.0,
        "ret_5m_pct": 0.4,
        "ret_15m_pct": 0.5,
        "ret_60m_pct": 0.8,
        "ma5_slope_pct": 0.2,
        "breakout_20m": False,
        "close": 101.0,
    }
    ok, score = momentum_hit(feat, regime=MarketRegime.BULL_TREND)
    assert ok is True
    assert score > 0


def test_momentum_rejects_below_frozen_ret60() -> None:
    feat = {
        "ma5": 101.0,
        "ma20": 100.0,
        "ma_sep_pct": 1.0,
        "volume_surge": 1.5,
        "rsi14": 55.0,
        "ret_5m_pct": 0.4,
        "ret_15m_pct": 0.5,
        "ret_60m_pct": 0.3,  # < 0.40
        "ma5_slope_pct": 0.2,
        "breakout_20m": False,
        "close": 101.0,
    }
    ok, _ = momentum_hit(feat, regime=MarketRegime.SIDEWAYS)
    assert ok is False


def test_research_sqlite_no_prod_path() -> None:
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "t.sqlite"
        conn = connect(db)
        upsert_rows(
            conn,
            symbol="KRW-BTC",
            rows=[
                {
                    "candle_at": datetime(2026, 6, 1, tzinfo=timezone.utc),
                    "open_price": 1,
                    "high_price": 2,
                    "low_price": 1,
                    "close_price": 1.5,
                    "volume": 10,
                    "trade_value": 100,
                }
            ],
            source="test",
        )
        bars = load_symbol_bars(conn, "KRW-BTC")
        conn.close()
        assert len(bars) == 1
        assert "market.candle_minute" not in str(db)
