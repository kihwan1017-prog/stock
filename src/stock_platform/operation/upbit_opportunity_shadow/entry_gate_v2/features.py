"""Decision-time features for Entry Gate V2 — lookahead 금지."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Sequence


@dataclass(frozen=True, slots=True)
class V2Features:
    ma_gap_pct: float | None
    ma_slope: float | None
    gc_age_min: float | None
    pre1: float | None
    pre3: float | None
    pre5: float | None
    pre15: float | None
    range_pos15: float | None
    dist_high15: float | None
    cand_score: float | None
    cand_rank: float | None
    rsi14: float | None
    volume_surge: float | None
    regime: str
    vol15: float | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ma_gap_pct": self.ma_gap_pct,
            "ma_slope": self.ma_slope,
            "gc_age_min": self.gc_age_min,
            "pre1": self.pre1,
            "pre3": self.pre3,
            "pre5": self.pre5,
            "pre15": self.pre15,
            "range_pos15": self.range_pos15,
            "dist_high15": self.dist_high15,
            "cand_score": self.cand_score,
            "cand_rank": self.cand_rank,
            "rsi14": self.rsi14,
            "volume_surge": self.volume_surge,
            "regime": self.regime,
            "vol15": self.vol15,
            "lookahead_forbidden": True,
        }


def _f(x: Any) -> float | None:
    if x is None:
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _ma(closes: Sequence[float], n: int, end: int) -> float | None:
    if end + 1 < n or end < 0:
        return None
    chunk = closes[end + 1 - n : end + 1]
    if len(chunk) < n:
        return None
    return sum(chunk) / n


def build_features_from_closes(
    *,
    closes: Sequence[float],
    highs: Sequence[float] | None = None,
    lows: Sequence[float] | None = None,
    short_ma: Decimal | float | None = None,
    long_ma: Decimal | float | None = None,
    rsi14: float | None = None,
    volume_surge: float | None = None,
    cand_score: float | None = None,
    cand_rank: float | None = None,
) -> V2Features:
    """closes/highs/lows는 decision 시점 이전(포함) 값만 — 호출자가 보장."""

    closes_f = [float(c) for c in closes if c is not None]
    n = len(closes_f)
    px = closes_f[-1] if n else None

    ma_gap = None
    if short_ma is not None and long_ma is not None and float(long_ma) != 0:
        ma_gap = (float(short_ma) - float(long_ma)) / float(long_ma) * 100.0
    elif n >= 20:
        s = _ma(closes_f, 5, n - 1)
        lg = _ma(closes_f, 20, n - 1)
        if s is not None and lg not in (None, 0):
            ma_gap = (s - lg) / lg * 100.0

    ma_slope = None
    if n >= 6:
        s0 = _ma(closes_f, 5, n - 1)
        s1 = _ma(closes_f, 5, n - 2)
        if s0 is not None and s1 is not None:
            ma_slope = s0 - s1

    def ret(mins: int) -> float | None:
        if px is None or n <= mins or closes_f[-(mins + 1)] <= 0:
            return None
        return (px / closes_f[-(mins + 1)] - 1.0) * 100.0

    range_pos = None
    dist_high = None
    if px is not None and highs and lows and len(highs) >= 15 and len(lows) >= 15:
        hi = max(float(x) for x in highs[-15:])
        lo = min(float(x) for x in lows[-15:])
        span = hi - lo
        range_pos = ((px - lo) / span) if span > 0 else 0.5
        dist_high = ((px - hi) / hi * 100.0) if hi > 0 else None
    elif px is not None and n >= 15:
        # close-only proxy range
        hi = max(closes_f[-15:])
        lo = min(closes_f[-15:])
        span = hi - lo
        range_pos = ((px - lo) / span) if span > 0 else 0.5
        dist_high = ((px - hi) / hi * 100.0) if hi > 0 else None

    gc_age = None
    if n >= 25 and ma_gap is not None and ma_gap > 0:
        age = 0
        for back in range(0, min(180, n - 20)):
            end = n - 1 - back
            s = _ma(closes_f, 5, end)
            lg = _ma(closes_f, 20, end)
            if s is None or lg is None:
                break
            if s <= lg:
                break
            age = back
        gc_age = float(age)

    vol15 = None
    if n >= 16:
        rets = []
        for k in range(n - 15, n):
            if closes_f[k - 1] > 0:
                rets.append((closes_f[k] / closes_f[k - 1] - 1.0) * 100.0)
        if len(rets) >= 2:
            mean = sum(rets) / len(rets)
            vol15 = (sum((x - mean) ** 2 for x in rets) / len(rets)) ** 0.5

    if ma_gap is not None and ma_slope is not None:
        if ma_gap > 0.05 and ma_slope >= 0:
            regime = "BULLISH"
        elif ma_gap < -0.05 and ma_slope <= 0:
            regime = "BEARISH"
        else:
            regime = "SIDEWAYS"
    elif ma_gap is not None:
        if ma_gap > 0.05:
            regime = "BULLISH"
        elif ma_gap < -0.05:
            regime = "BEARISH"
        else:
            regime = "SIDEWAYS"
    else:
        regime = "UNKNOWN"

    return V2Features(
        ma_gap_pct=ma_gap,
        ma_slope=ma_slope,
        gc_age_min=gc_age,
        pre1=ret(1),
        pre3=ret(3),
        pre5=ret(5),
        pre15=ret(15),
        range_pos15=range_pos,
        dist_high15=dist_high,
        cand_score=_f(cand_score),
        cand_rank=_f(cand_rank),
        rsi14=_f(rsi14),
        volume_surge=_f(volume_surge),
        regime=regime,
        vol15=vol15,
    )


def quality_score(feat: V2Features) -> float:
    score = 0.0
    if feat.ma_gap_pct is not None and feat.ma_gap_pct > 0:
        score += 0.20
        score += min(0.15, max(0.0, feat.ma_gap_pct) / 0.5 * 0.15)
    if feat.gc_age_min is not None and feat.ma_gap_pct is not None and feat.ma_gap_pct > 0:
        if feat.gc_age_min <= 15:
            score += 0.15
        elif feat.gc_age_min <= 45:
            score += 0.08
        elif feat.gc_age_min <= 90:
            score += 0.03
    if feat.pre5 is not None and feat.pre5 <= 0.08:
        score += 0.12
    elif feat.pre5 is not None and feat.pre5 <= 0.15:
        score += 0.05
    if feat.range_pos15 is not None and feat.range_pos15 <= 0.55:
        score += 0.12
    elif feat.range_pos15 is not None and feat.range_pos15 <= 0.65:
        score += 0.05
    if feat.cand_score is not None:
        score += min(0.12, max(0.0, (feat.cand_score - 60.0) / 40.0) * 0.12)
    if feat.cand_rank is not None and feat.cand_rank <= 2:
        score += 0.06
    if feat.rsi14 is not None:
        if 45 <= feat.rsi14 <= 68:
            score += 0.08
        elif feat.rsi14 > 75:
            score -= 0.08
    if feat.volume_surge is not None:
        if feat.volume_surge >= 0.8:
            score += 0.06
        elif feat.volume_surge >= 0.5:
            score += 0.03
    if feat.regime == "BULLISH":
        score += 0.08
    elif feat.regime == "BEARISH":
        score -= 0.12
    return max(0.0, min(1.0, score))
