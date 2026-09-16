"""Lab A — Candidate Selection V2 ranking (pure, no future leakage)."""

from __future__ import annotations

import math
from typing import Any


def _f(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v)
        if math.isnan(x) or math.isinf(x):
            return default
        return x
    except (TypeError, ValueError):
        return default


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def extract_features(row: dict[str, Any]) -> dict[str, float | str | None]:
    """실제 저장/전달 feature만 사용 — 미래 수익률 금지."""

    tech = dict(row.get("technical_metrics") or {})
    ma5 = _f(tech.get("ma5") or row.get("ma5"), 0.0)
    ma20 = _f(tech.get("ma20") or row.get("ma20"), 0.0)
    macd = _f(tech.get("macd") or row.get("macd"), 0.0)
    atr = _f(tech.get("atr14") or row.get("atr14"), 0.0)
    rsi = _f(tech.get("rsi14") or row.get("rsi14"), 50.0)
    surge = _f(tech.get("volume_surge") or row.get("volume_surge"), 1.0)
    vol = _f(tech.get("volatility") or row.get("volatility"), 0.0)
    mom = _f(tech.get("momentum") or row.get("momentum"), 0.0)
    liq = _f(row.get("liquidity") or row.get("trade_value_24h"), 0.0)
    score = _f(row.get("score") or row.get("scanner_score"), 0.0)
    trend = str(tech.get("trend") or row.get("trend") or "").upper() or None
    sep = ((ma5 - ma20) / ma20 * 100.0) if ma20 > 0 else 0.0
    atr_pct = (atr / ma5 * 100.0) if ma5 > 0 else vol
    return {
        "ma5": ma5,
        "ma20": ma20,
        "macd": macd,
        "atr14": atr,
        "rsi14": rsi,
        "volume_surge": surge,
        "volatility": vol,
        "momentum": mom,
        "liquidity": liq,
        "real_score": score,
        "trend": trend,
        "ma_separation_pct": sep,
        "atr_pct": atr_pct,
    }


def score_a0_real(feat: dict[str, Any]) -> float:
    return float(feat.get("real_score") or 0.0)


def score_a1_momentum_quality(feat: dict[str, Any]) -> float:
    """단순 급등 추격 회피 + momentum/volume/MA quality."""

    trend = str(feat.get("trend") or "")
    trend_bonus = 12.0 if trend == "UP" else (0.0 if trend == "DOWN" else 4.0)
    sep = _clip(float(feat.get("ma_separation_pct") or 0.0), -5.0, 8.0)
    macd = float(feat.get("macd") or 0.0)
    macd_n = _clip(macd * 50.0, -15.0, 15.0)  # scale-ish
    surge = _clip(float(feat.get("volume_surge") or 1.0), 0.0, 4.0)
    mom = _clip(float(feat.get("momentum") or 0.0), -5.0, 5.0)
    liq = float(feat.get("liquidity") or 0.0)
    liq_n = _clip(math.log10(liq + 1.0) - 8.0, -10.0, 10.0)  # ~1e8~1e10 KRW
    rsi = float(feat.get("rsi14") or 50.0)
    # overextension penalty
    over = 0.0
    if rsi >= 75:
        over += (rsi - 75) * 2.5
    if sep >= 4.0:
        over += (sep - 4.0) * 5.0
    if surge >= 3.0 and sep >= 2.5:
        over += 20.0  # chase spike
    raw = (
        40.0
        + trend_bonus
        + sep * 3.0
        + macd_n
        + (surge - 1.0) * 8.0
        + mom * 2.0
        + liq_n * 1.5
        - over
    )
    return round(raw, 4)


def score_a2_risk_adjusted(feat: dict[str, Any]) -> float:
    base = score_a1_momentum_quality(feat)
    risk = max(
        float(feat.get("atr_pct") or 0.0),
        float(feat.get("volatility") or 0.0),
        0.35,
    )
    return round(base / risk * 0.8, 4)


def score_a3_trend_confirmation(feat: dict[str, Any]) -> float:
    ma5 = float(feat.get("ma5") or 0.0)
    ma20 = float(feat.get("ma20") or 0.0)
    sep = float(feat.get("ma_separation_pct") or 0.0)
    surge = float(feat.get("volume_surge") or 1.0)
    rsi = float(feat.get("rsi14") or 50.0)
    macd = float(feat.get("macd") or 0.0)
    trend = str(feat.get("trend") or "")
    score = 30.0
    if ma5 > 0 and ma20 > 0 and ma5 > ma20:
        score += 18.0
    else:
        score -= 12.0
    if trend == "UP":
        score += 10.0
    if macd >= 0:
        score += 8.0
    else:
        score -= 6.0
    if 0.2 <= sep <= 3.0:
        score += 12.0  # healthy separation
    elif sep > 5.0:
        score -= 15.0  # overextended
    if surge >= 1.0:
        score += min((surge - 1.0) * 6.0, 12.0)
    # pullback depth proxy: rsi mid-range preferred
    if 45 <= rsi <= 65:
        score += 10.0
    elif rsi > 72:
        score -= 10.0
    return round(score, 4)


SCORERS = {
    "A0": score_a0_real,
    "A1": score_a1_momentum_quality,
    "A2": score_a2_risk_adjusted,
    "A3": score_a3_trend_confirmation,
}


def rank_universe(
    rows: list[dict[str, Any]],
    *,
    variant: str,
    top_n: int = 10,
) -> list[dict[str, Any]]:
    """Deterministic TOP-N. Future returns must not be present in rows."""

    scorer = SCORERS[variant]
    scored: list[dict[str, Any]] = []
    for row in rows:
        sym = str(row.get("symbol") or "").upper().strip()
        if not sym.startswith("KRW-"):
            continue
        # 미래 누수 가드
        for k in list(row.keys()):
            ku = str(k).upper()
            if "RETURN" in ku or ku.startswith("FUTURE") or "MFE" == ku or "MAE" == ku:
                raise ValueError(f"future_leakage_key={k}")
        feat = extract_features(row)
        scored.append(
            {
                "symbol": sym,
                "score": scorer(feat),
                "features": {
                    k: feat[k]
                    for k in (
                        "real_score",
                        "trend",
                        "ma_separation_pct",
                        "volume_surge",
                        "macd",
                        "rsi14",
                        "atr_pct",
                        "liquidity",
                    )
                },
                "real_rank": row.get("rank") or row.get("scanner_rank"),
                "real_score": feat.get("real_score"),
            }
        )
    scored.sort(key=lambda x: (-float(x["score"]), x["symbol"]))
    out = []
    for i, item in enumerate(scored[:top_n], start=1):
        out.append({**item, "shadow_rank": i})
    return out
