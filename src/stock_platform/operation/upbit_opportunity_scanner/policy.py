"""Scanner 임계값·점수 가중치 — 한 곳에서만 관리."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from stock_platform.common.settings import get_settings


@dataclass(frozen=True, slots=True)
class ScannerPolicy:
    """Alert-only Opportunity Scanner 정책 스냅샷."""

    enabled: bool
    interval_seconds: float
    min_24h_trade_value_krw: float
    top_n: int
    cooldown_seconds: float
    max_spike_pct: float
    technical_candidate_limit: int
    min_candles: int
    candle_unit: int
    ai_enabled: bool
    notify_hold: bool
    # ranking weights (합=1.0 권장, 강제하지 않음)
    weight_liquidity: float = 0.20
    weight_volume_surge: float = 0.20
    weight_ma_spread: float = 0.15
    weight_momentum: float = 0.15
    weight_macd: float = 0.10
    weight_rsi: float = 0.10
    weight_volatility_penalty: float = 0.10
    rsi_ideal_low: float = 45.0
    rsi_ideal_high: float = 70.0
    rsi_overbought: float = 78.0
    ticker_batch_size: int = 100


def load_scanner_policy(settings: Any | None = None) -> ScannerPolicy:
    settings = settings if settings is not None else get_settings()
    top_n = int(getattr(settings, "upbit_scanner_top_n", 5) or 5)
    top_n = max(1, min(10, top_n))
    tech_limit = int(
        getattr(settings, "upbit_scanner_technical_candidate_limit", 30) or 30
    )
    tech_limit = max(top_n, min(100, tech_limit))
    unit = int(getattr(settings, "upbit_scanner_candle_unit", 1) or 1)
    if unit not in (1, 3, 5, 15):
        unit = 1
    return ScannerPolicy(
        enabled=bool(
            getattr(settings, "upbit_opportunity_scanner_enabled", False)
        ),
        interval_seconds=float(
            getattr(
                settings,
                "upbit_opportunity_scanner_interval_seconds",
                900.0,
            )
            or 900.0
        ),
        min_24h_trade_value_krw=float(
            getattr(
                settings,
                "upbit_scanner_min_24h_trade_value_krw",
                5_000_000_000.0,
            )
            or 5_000_000_000.0
        ),
        top_n=top_n,
        cooldown_seconds=float(
            getattr(settings, "upbit_scanner_symbol_cooldown_seconds", 1800.0)
            or 1800.0
        ),
        max_spike_pct=float(
            getattr(settings, "upbit_scanner_max_spike_pct", 15.0) or 15.0
        ),
        technical_candidate_limit=tech_limit,
        min_candles=int(
            getattr(settings, "upbit_scanner_min_candles", 30) or 30
        ),
        candle_unit=unit,
        ai_enabled=bool(getattr(settings, "upbit_scanner_ai_enabled", True)),
        notify_hold=bool(
            getattr(settings, "upbit_scanner_notify_hold", False)
        ),
    )


def score_candidate(
    *,
    policy: ScannerPolicy,
    trade_value_24h: float,
    volume_surge: float | None,
    ma_spread_pct: float | None,
    momentum_5m_pct: float | None,
    macd_histogram: float | None,
    rsi14: float | None,
    volatility_20m_pct: float | None,
) -> tuple[float, dict[str, float]]:
    """0~100 deterministic score + 요소별 기여."""

    parts: dict[str, float] = {}

    # liquidity: log-ish vs min threshold
    min_tv = max(policy.min_24h_trade_value_krw, 1.0)
    liq_ratio = trade_value_24h / min_tv
    parts["liquidity"] = max(0.0, min(100.0, 40.0 + 30.0 * min(liq_ratio, 3.0)))

    surge = float(volume_surge or 0.0)
    parts["volume_surge"] = max(0.0, min(100.0, surge * 35.0))

    spread = float(ma_spread_pct or 0.0)
    parts["ma_spread"] = max(0.0, min(100.0, 50.0 + spread * 80.0))

    mom = float(momentum_5m_pct or 0.0)
    parts["momentum"] = max(0.0, min(100.0, 50.0 + mom * 40.0))

    hist = float(macd_histogram or 0.0)
    parts["macd"] = max(0.0, min(100.0, 50.0 + hist * 80.0))

    rsi = float(rsi14) if rsi14 is not None else 50.0
    if policy.rsi_ideal_low <= rsi <= policy.rsi_ideal_high:
        parts["rsi"] = 90.0
    elif rsi > policy.rsi_overbought:
        parts["rsi"] = 15.0
    elif rsi < 30.0:
        parts["rsi"] = 25.0
    else:
        parts["rsi"] = 55.0

    vol = float(volatility_20m_pct or 0.0)
    # 낮은 변동성 선호, 과도하면 감점
    if vol <= 0.08:
        parts["volatility"] = 85.0
    elif vol <= 0.2:
        parts["volatility"] = 60.0
    else:
        parts["volatility"] = max(0.0, 40.0 - (vol - 0.2) * 80.0)

    total = (
        parts["liquidity"] * policy.weight_liquidity
        + parts["volume_surge"] * policy.weight_volume_surge
        + parts["ma_spread"] * policy.weight_ma_spread
        + parts["momentum"] * policy.weight_momentum
        + parts["macd"] * policy.weight_macd
        + parts["rsi"] * policy.weight_rsi
        + parts["volatility"] * policy.weight_volatility_penalty
    )
    return round(float(total), 2), parts
