"""Transparent multi-family entry rules — not E1~E4 threshold relaxation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from stock_platform.operation.upbit_positive_edge_entry.regime import MarketRegime

FAMILY_KEYS = (
    "M0_CURRENT",
    "MOMENTUM",
    "BREAKOUT",
    "VOLUME_SURGE",
    "PULLBACK",
    "MEAN_REVERSION",
)


@dataclass(frozen=True, slots=True)
class FamilyHit:
    family: str
    score: float
    reason: str


def _f(x: Any, default: float = 0.0) -> float:
    try:
        if x is None:
            return default
        return float(x)
    except (TypeError, ValueError):
        return default


def evaluate_families(
    feat: dict[str, Any],
    *,
    regime: MarketRegime | str,
) -> list[FamilyHit]:
    """시점 t feature dict → family hits. future labels 사용 금지."""

    reg = (
        regime
        if isinstance(regime, MarketRegime)
        else MarketRegime(str(regime))
    )
    hits: list[FamilyHit] = []

    ma_s = feat.get("ma5")
    ma_l = feat.get("ma20")
    sep = feat.get("ma_sep_pct")
    surge = _f(feat.get("volume_surge"))
    rsi = feat.get("rsi14")
    ret5 = _f(feat.get("ret_5m_pct"))
    ret15 = _f(feat.get("ret_15m_pct"))
    ret60 = _f(feat.get("ret_60m_pct"))
    ma_slope = _f(feat.get("ma5_slope_pct"))
    broke = bool(feat.get("breakout_20m"))
    close = _f(feat.get("close"))
    ma5v = _f(ma_s) if ma_s is not None else None

    # M0 — production-like MA entry (research replica, AI gate 생략)
    if (
        ma_s is not None
        and ma_l is not None
        and float(ma_s) > float(ma_l)
        and sep is not None
        and float(sep) >= 0.05
        and surge >= 0.8
        and rsi is not None
        and float(rsi) < 70.0
        and ma5v is not None
        and close >= ma5v
    ):
        hits.append(
            FamilyHit(
                "M0_CURRENT",
                score=float(sep) + surge * 0.1,
                reason="MA_BULL_SEP_VOL_RSI",
            )
        )

    # A — Momentum (추세 지속) — E1~E4 완화와 무관
    if (
        ret15 >= 0.25
        and ret60 >= 0.40
        and ma_slope > 0
        and surge >= 1.0
        and ret15 < 3.0
        and ma_s is not None
        and ma_l is not None
        and float(ma_s) > float(ma_l)
    ):
        hits.append(
            FamilyHit(
                "MOMENTUM",
                score=ret60 + ret15 * 0.5 + surge * 0.2,
                reason="TREND_CONTINUATION",
            )
        )

    # B — Breakout
    if broke and surge >= 1.2 and ret5 > 0:
        hits.append(
            FamilyHit(
                "BREAKOUT",
                score=ret5 * 2 + surge,
                reason="PRIOR_HIGH_BREAK_VOL",
            )
        )

    # C — Volume surge + price confirmation
    if surge >= 2.0 and ret5 >= 0.15:
        hits.append(
            FamilyHit(
                "VOLUME_SURGE",
                score=surge + ret5,
                reason="REL_VOL_PLUS_PRICE",
            )
        )

    # D — Pullback in uptrend
    if (
        ma_s is not None
        and ma_l is not None
        and float(ma_s) > float(ma_l)
        and ret60 >= 0.30
        and ret15 <= -0.20
        and ret5 >= 0.05
    ):
        hits.append(
            FamilyHit(
                "PULLBACK",
                score=ret60 - abs(ret15) + ret5,
                reason="HT_UP_ST_DIP_RECOVER",
            )
        )

    # E — Mean reversion (BEAR에서는 비활성 variant)
    if reg != MarketRegime.BEAR_TREND and rsi is not None and float(rsi) <= 30.0:
        if ret15 <= -0.80:
            hits.append(
                FamilyHit(
                    "MEAN_REVERSION",
                    score=(30.0 - float(rsi)) + abs(ret15) * 0.5,
                    reason="RSI_OVERSOLD_BOUNCE",
                )
            )

    return hits


def dedupe_signals(
    signals: list[tuple[str, str, object]],
) -> list[tuple[str, str, object]]:
    """(ts_key, symbol, family) — 동일 ts+symbol은 score 최고 family 1개만.

    입력은 이미 family별로 걸러진 행; 여기서는 symbol-ts 중복 제거용.
    signals: list of (ts_iso, symbol, payload) where payload has .score or score key.
    """

    best: dict[tuple[str, str], tuple[str, str, object]] = {}
    scores: dict[tuple[str, str], float] = {}
    for ts, sym, payload in signals:
        key = (ts, sym)
        sc = 0.0
        if hasattr(payload, "score"):
            sc = float(getattr(payload, "score") or 0)
        elif isinstance(payload, dict):
            sc = float(payload.get("score") or 0)
        if key not in best or sc > scores[key]:
            best[key] = (ts, sym, payload)
            scores[key] = sc
    return list(best.values())
