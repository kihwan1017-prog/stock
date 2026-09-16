"""KIWOOM outcome windows — market-close aware (no invented prices)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from stock_platform.operation.dual_llm.markets import MARKET_KIWOOM


WINDOWS_MIN = (5, 15, 30, 60)


def label_from_returns(
    *,
    return_5m: float | None,
    mfe: float | None,
    early_dump: bool,
    truncated: bool,
) -> str:
    if truncated and return_5m is None and mfe is None:
        return "INSUFFICIENT_DATA"
    if early_dump or (return_5m is not None and return_5m <= -0.5):
        return "EARLY_DUMP"
    if mfe is not None and mfe >= 0.5 and return_5m is not None and return_5m >= 0.2:
        return "GOOD_FOLLOW_THROUGH"
    if mfe is not None and mfe >= 0.5 and return_5m is not None and return_5m < mfe * 0.4:
        return "SPIKE_REVERSAL"
    if (mfe is None or abs(mfe) < 0.2) and (return_5m is None or abs(return_5m) < 0.25):
        return "FLAT_FEE_CHURN"
    return "MARKET_REVERSAL" if (return_5m is not None and return_5m < 0) else "FLAT_FEE_CHURN"


def build_pending_outcome(*, evaluated_at: datetime) -> dict[str, Any]:
    return {
        "market": MARKET_KIWOOM,
        "status": "PENDING",
        "windows_min": list(WINDOWS_MIN),
        "evaluated_at": evaluated_at.astimezone(timezone.utc).isoformat(),
        "return_5m": None,
        "return_15m": None,
        "return_30m": None,
        "return_60m": None,
        "mfe": None,
        "mae": None,
        "label": "INSUFFICIENT_DATA",
        "truncated": False,
        "note": "가격 채움 금지 — 관측 후 갱신",
    }


def mark_truncated_by_market_close(
    outcome: dict[str, Any],
    *,
    reason: str = "TRUNCATED_BY_MARKET_CLOSE",
) -> dict[str, Any]:
    out = dict(outcome)
    out["status"] = reason
    out["truncated"] = True
    if not out.get("label") or out.get("label") == "INSUFFICIENT_DATA":
        # 부분 window라도 있으면 label 재계산
        out["label"] = label_from_returns(
            return_5m=out.get("return_5m"),
            mfe=out.get("mfe"),
            early_dump=bool(out.get("early_dump")),
            truncated=True,
        )
    return out


def try_enrich_outcome_from_minute_bars(
    session: Session,
    *,
    symbol: str,
    entry_price: float,
    evaluated_at: datetime,
    bars: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """bars가 주어지면 window 계산. 없으면 PENDING (임의 채움 금지).

    bars item: {ts: datetime, close: float, high: float, low: float}
    """

    base = build_pending_outcome(evaluated_at=evaluated_at)
    if not bars:
        return base
    if entry_price <= 0:
        return mark_truncated_by_market_close(base)

    det = evaluated_at.astimezone(timezone.utc)
    returns: dict[str, float | None] = {}
    highs: list[float] = []
    lows: list[float] = []
    for w in WINDOWS_MIN:
        target = det + timedelta(minutes=w)
        # 해당 window 이전 마지막 bar
        candidates = [
            b
            for b in bars
            if isinstance(b.get("ts"), datetime) and as_utc_safe(b["ts"]) <= target
            and as_utc_safe(b["ts"]) >= det
        ]
        if not candidates:
            returns[f"return_{w}m"] = None
            continue
        last = candidates[-1]
        try:
            px = float(last.get("close"))
            returns[f"return_{w}m"] = round((px / entry_price - 1.0) * 100.0, 6)
        except (TypeError, ValueError, ZeroDivisionError):
            returns[f"return_{w}m"] = None
        for b in candidates:
            try:
                highs.append(float(b["high"]))
                lows.append(float(b["low"]))
            except (TypeError, ValueError, KeyError):
                pass

    mfe = round((max(highs) / entry_price - 1.0) * 100.0, 6) if highs else None
    mae = round((min(lows) / entry_price - 1.0) * 100.0, 6) if lows else None
    r5 = returns.get("return_5m")
    early = bool(r5 is not None and r5 <= -0.5)
    truncated = any(returns.get(f"return_{w}m") is None for w in WINDOWS_MIN)
    label = label_from_returns(
        return_5m=r5, mfe=mfe, early_dump=early, truncated=truncated
    )
    out = {
        **base,
        **returns,
        "mfe": mfe,
        "mae": mae,
        "early_dump": early,
        "label": label,
        "truncated": truncated,
        "status": "TRUNCATED_BY_MARKET_CLOSE" if truncated else "COMPLETE",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "market": MARKET_KIWOOM,
    }
    return out


def as_utc_safe(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)
