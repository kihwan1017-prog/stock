"""Historical replay + outcome metrics — LOOKAHEAD LEAKAGE 금지."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from stock_platform.broker.fee_policy import UpbitFeePolicy
from stock_platform.operation.upbit_full_market.portfolio_entry_signal import (
    SymbolEntrySnapshot,
)
from stock_platform.operation.upbit_opportunity_shadow.entry_signal_shadow.constants import (
    ALL_VARIANTS,
    FEE_RT_PCT,
    FEE_TAKER_RATE,
    OUTCOME_WINDOWS_MIN,
    SOURCE_REPLAY,
    VARIANT_E0,
)
from stock_platform.operation.upbit_opportunity_shadow.entry_signal_shadow.variants import (
    attribution_from_e0_block,
    evaluate_all_variants,
)


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _dec(v: Any) -> Decimal | None:
    if v is None:
        return None
    try:
        return Decimal(str(v))
    except Exception:  # noqa: BLE001
        return None


def load_selection_observations(
    session: Session,
    *,
    uba_id: int,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Load natural selections — decision uses only selection-time metrics."""

    rows = session.execute(
        text(
            """
            SELECT selection_id, symbol, selected_at, created_at,
                   technical_metrics, ai_recommendation, confidence, score
            FROM operation.upbit_live_candidate_selection
            WHERE user_broker_account_id = :uba
            ORDER BY selected_at ASC
            LIMIT :lim
            """
        ),
        {"uba": int(uba_id), "lim": int(limit)},
    ).mappings().all()

    out: list[dict[str, Any]] = []
    for r in rows:
        tm = r["technical_metrics"] or {}
        if not isinstance(tm, dict):
            tm = {}
        short = _dec(tm.get("ma5"))
        long_ = _dec(tm.get("ma20"))
        if short is None or long_ is None or long_ == 0:
            continue
        sel_at = _as_utc(r["selected_at"] or r["created_at"])
        if sel_at is None:
            continue
        rsi = tm.get("rsi14")
        surge = tm.get("volume_surge")
        snap = SymbolEntrySnapshot(
            symbol=str(r["symbol"] or "").upper(),
            selection_id=int(r["selection_id"]),
            selected_at=sel_at,
            ai_recommendation=str(r["ai_recommendation"] or "").upper() or None,
            ai_confidence=float(r["confidence"]) if r["confidence"] is not None else None,
            scanner_score=float(r["score"]) if r["score"] is not None else None,
            rsi14=float(rsi) if rsi is not None else None,
            volume_surge=float(surge) if surge is not None else None,
            technical_metrics=dict(tm),
            bound_to_waiting_slot=True,  # replay as WAITING-bound
        )
        decisions = evaluate_all_variants(
            short_ma=short,
            long_ma=long_,
            snap=snap,
            emit_suppressed=False,
            event_time=sel_at,
            now=sel_at,  # LOOKAHEAD 금지 — feed age를 관측 시점으로 고정
        )
        out.append(
            {
                "observation_id": f"sel:{r['selection_id']}",
                "market": "UPBIT",
                "symbol": snap.symbol,
                "observed_at": sel_at.isoformat(),
                "selection_id": int(r["selection_id"]),
                "short_ma": str(short),
                "long_ma": str(long_),
                "indicator_snapshot": {
                    "ma5": str(short),
                    "ma20": str(long_),
                    "rsi14": snap.rsi14,
                    "volume_surge": snap.volume_surge,
                    "ai_recommendation": snap.ai_recommendation,
                    "ma_gap_pct": float(
                        ((short - long_) / long_) * Decimal("100")
                    ),
                },
                "decisions": decisions,
                "e0_block": decisions[VARIANT_E0].get("block_reason"),
                "attribution": attribution_from_e0_block(
                    decisions[VARIANT_E0].get("block_reason")
                ),
            }
        )
    return out


def _future_prices(
    session: Session,
    *,
    symbol: str,
    observed_at: datetime,
) -> dict[str, Any]:
    """Outcome-only future candles — NEVER used for entry decision."""

    obs = _as_utc(observed_at)
    assert obs is not None
    # entry reference = last close at or before observed_at
    entry = session.scalar(
        text(
            """
            SELECT c.close_price
            FROM market.candle_minute c
            JOIN market.instrument i ON i.instrument_id = c.instrument_id
            WHERE i.symbol = :sym AND c.timeframe = 1
              AND c.candle_at <= :obs
            ORDER BY c.candle_at DESC
            LIMIT 1
            """
        ),
        {"sym": symbol, "obs": obs},
    )
    entry_px = _dec(entry)
    if entry_px is None or entry_px <= 0:
        return {"ok": False, "reason": "NO_ENTRY_PRICE"}

    futures: dict[str, Decimal | None] = {}
    highs: list[Decimal] = []
    lows: list[Decimal] = []
    for mins in OUTCOME_WINDOWS_MIN:
        target = obs + timedelta(minutes=mins)
        row = session.execute(
            text(
                """
                SELECT c.close_price, c.high_price, c.low_price, c.candle_at
                FROM market.candle_minute c
                JOIN market.instrument i ON i.instrument_id = c.instrument_id
                WHERE i.symbol = :sym AND c.timeframe = 1
                  AND c.candle_at >= :obs AND c.candle_at <= :tgt
                ORDER BY c.candle_at ASC
                """
            ),
            {"sym": symbol, "obs": obs, "tgt": target},
        ).mappings().all()
        if not row:
            futures[f"future_{mins}m"] = None
            continue
        last = row[-1]
        close = _dec(last["close_price"])
        if close is not None:
            futures[f"future_{mins}m"] = (
                (close - entry_px) / entry_px * Decimal("100")
            )
        for r in row:
            h = _dec(r["high_price"])
            lo = _dec(r["low_price"])
            if h is not None:
                highs.append(h)
            if lo is not None:
                lows.append(lo)

    mfe = None
    mae = None
    if highs:
        mfe = (max(highs) - entry_px) / entry_px * Decimal("100")
    if lows:
        mae = (min(lows) - entry_px) / entry_px * Decimal("100")

    fee_rt = Decimal(str(FEE_RT_PCT))
    # verify fee SoT
    taker = float(UpbitFeePolicy.DEFAULT_TAKER_RATE)
    assert abs(taker - FEE_TAKER_RATE) < 1e-12

    fut15 = futures.get("future_15m")
    net15 = None
    if fut15 is not None:
        net15 = fut15 - fee_rt

    return {
        "ok": True,
        "entry_reference_price": entry_px,
        "futures": {k: (float(v) if v is not None else None) for k, v in futures.items()},
        "mfe_pct": float(mfe) if mfe is not None else None,
        "mae_pct": float(mae) if mae is not None else None,
        "net_return_15m_pct": float(net15) if net15 is not None else None,
        "fee_rt_pct": float(fee_rt),
        "fee_assumption": f"UpbitFeePolicy.DEFAULT_TAKER_RATE={taker}",
        "slippage_assumption": "SLIPPAGE_NOT_MODELED",
    }


def attach_outcomes(
    session: Session, observations: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for obs in observations:
        fut = _future_prices(
            session,
            symbol=str(obs["symbol"]),
            observed_at=datetime.fromisoformat(obs["observed_at"]),
        )
        enriched.append({**obs, "outcome": fut})
    return enriched


def summarize_replay(observations: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate E0–E4 metrics from replay observations."""

    attr = Counter()
    for o in observations:
        attr[o.get("attribution") or "UNKNOWN"] += 1

    variants: dict[str, Any] = {}
    for code in ALL_VARIANTS:
        entries = [
            o
            for o in observations
            if (o.get("decisions") or {}).get(code, {}).get("pass")
        ]
        n = len(observations)
        e = len(entries)
        wins = 0
        losses = 0
        nets: list[float] = []
        mfes: list[float] = []
        maes: list[float] = []
        fee_churn = 0
        for o in entries:
            out = o.get("outcome") or {}
            net = out.get("net_return_15m_pct")
            mfe = out.get("mfe_pct")
            mae = out.get("mae_pct")
            if mfe is not None:
                mfes.append(float(mfe))
            if mae is not None:
                maes.append(float(mae))
            if net is None:
                continue
            nets.append(float(net))
            if float(net) > 0:
                wins += 1
            else:
                losses += 1
            # fee churn: gross < fee RT but trade still "entered"
            fut15 = (out.get("futures") or {}).get("future_15m")
            if fut15 is not None and abs(float(fut15)) < float(FEE_RT_PCT):
                fee_churn += 1

        decided = wins + losses
        avg_net = sum(nets) / len(nets) if nets else None
        gross_pos = sum(x for x in nets if x > 0)
        gross_neg = abs(sum(x for x in nets if x < 0))
        pf = (gross_pos / gross_neg) if gross_neg > 0 else (None if not nets else float("inf"))
        variants[code] = {
            "SAMPLES": n,
            "ENTRIES": e,
            "ENTRY_RATE": round(e / n, 4) if n else 0.0,
            "WIN": wins,
            "LOSS": losses,
            "WIN_RATE": round(wins / decided, 4) if decided else None,
            "NET_AVG_15M": round(avg_net, 4) if avg_net is not None else None,
            "PROFIT_FACTOR": (
                "INSUFFICIENT_SAMPLE"
                if decided < 10
                else (round(pf, 4) if isinstance(pf, float) else pf)
            ),
            "EXPECTANCY": (
                "INSUFFICIENT_SAMPLE"
                if decided < 10
                else (round(avg_net, 4) if avg_net is not None else None)
            ),
            "AVG_MFE": round(sum(mfes) / len(mfes), 4) if mfes else None,
            "AVG_MAE": round(sum(maes) / len(maes), 4) if maes else None,
            "FEE_CHURN_COUNT": fee_churn,
            "OUTCOME_DECIDED": decided,
            "INSUFFICIENT_SAMPLE": decided < 10,
        }

    e0 = variants[VARIANT_E0]
    deltas: dict[str, Any] = {}
    for code in ALL_VARIANTS:
        if code == VARIANT_E0:
            continue
        v = variants[code]
        deltas[code] = {
            "DELTA_ENTRY_COUNT": v["ENTRIES"] - e0["ENTRIES"],
            "DELTA_WIN_RATE": (
                None
                if v["WIN_RATE"] is None or e0["WIN_RATE"] is None
                else round(v["WIN_RATE"] - e0["WIN_RATE"], 4)
            ),
            "DELTA_NET": (
                None
                if v["NET_AVG_15M"] is None or e0["NET_AVG_15M"] is None
                else round(v["NET_AVG_15M"] - e0["NET_AVG_15M"], 4)
            ),
            "DELTA_MFE": (
                None
                if v["AVG_MFE"] is None or e0["AVG_MFE"] is None
                else round(v["AVG_MFE"] - e0["AVG_MFE"], 4)
            ),
            "DELTA_MAE": (
                None
                if v["AVG_MAE"] is None or e0["AVG_MAE"] is None
                else round(v["AVG_MAE"] - e0["AVG_MAE"], 4)
            ),
        }

    # opportunity cost for RSI blocks
    rsi_blocked = [
        o for o in observations if o.get("attribution") == "BLOCKED_BY_RSI"
    ]
    protective = 0
    missed_pos = 0
    for o in rsi_blocked:
        net = (o.get("outcome") or {}).get("net_return_15m_pct")
        if net is None:
            continue
        if float(net) < 0:
            protective += 1
        else:
            missed_pos += 1

    return {
        "source": SOURCE_REPLAY,
        "observations": len(observations),
        "attribution": dict(attr),
        "variants": variants,
        "delta_vs_e0": deltas,
        "opportunity_cost": {
            "BLOCKED_BY_RSI": {
                "count": len(rsi_blocked),
                "PROTECTIVE_BLOCK": protective,
                "MISSED_POSITIVE_15M": missed_pos,
            }
        },
        "FEE_ASSUMPTION": f"taker={FEE_TAKER_RATE} rt_pct={FEE_RT_PCT}",
        "SLIPPAGE_ASSUMPTION": "SLIPPAGE_NOT_MODELED",
    }


def run_historical_replay(
    session: Session,
    *,
    uba_id: int = 1380,
    limit: int = 500,
) -> dict[str, Any]:
    obs = load_selection_observations(session, uba_id=uba_id, limit=limit)
    if not obs:
        return {
            "ok": False,
            "reason": "NO_OBSERVATIONS",
            "DATA_QUALITY": "EMPTY",
        }
    enriched = attach_outcomes(session, obs)
    summary = summarize_replay(enriched)
    dates = [o["observed_at"] for o in enriched]
    return {
        "ok": True,
        "REPLAY_START": min(dates),
        "REPLAY_END": max(dates),
        "DATA_QUALITY": "SELECTION_TECHNICAL_METRICS+CANDLE_OUTCOME",
        "LOOKAHEAD_LEAKAGE": False,
        **summary,
        "sample_observations": enriched[:5],
    }
