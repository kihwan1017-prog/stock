"""Trading LLM SHADOW prediction → CLEAN outcome feedback scoring.

단순 손익만이 아니라 diagnostic classification을 저장한다.
threshold는 research config — 이번 STEP에서 최적화하지 않음.
"""

from __future__ import annotations

from typing import Any

from stock_platform.operation.upbit_opportunity_shadow.entry_quality_early_dump_experiment import (
    FEE_RT_PCT_THRESHOLD,
    outcome_label,
)

# Research thresholds (고정 — 최적화 금지)
WINNER_MFE_PCT = 0.5
WINNER_R60_PCT = 0.4
LOSER_R5_PCT = -0.5
MISSED_WINNER_MFE_PCT = 1.0


def _f(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def classify_prediction_correctness(
    *,
    recommendation: str | None,
    label: str | None,
    early_dump: bool,
    return_5m: float | None,
    return_60m: float | None,
    mfe: float | None,
    mae: float | None,
) -> str:
    """ALLOW/HOLD/REDUCE × actual path → diagnostic verdict."""

    rec = str(recommendation or "").upper()
    lab = str(label or "").upper()
    r5 = _f(return_5m)
    r60 = _f(return_60m)
    mfe_v = _f(mfe)

    is_early = bool(early_dump) or lab.startswith("EARLY_DUMP") or (
        r5 is not None and r5 <= LOSER_R5_PCT
    )
    is_fee_churn = lab in {"FLAT", "FLAT_FEE_CHURN"} or (
        mfe_v is not None
        and abs(mfe_v) < FEE_RT_PCT_THRESHOLD
        and r5 is not None
        and abs(r5) < FEE_RT_PCT_THRESHOLD
    )
    is_winner = (mfe_v is not None and mfe_v >= WINNER_MFE_PCT) or (
        r60 is not None and r60 >= WINNER_R60_PCT
    )
    is_big_winner = (mfe_v is not None and mfe_v >= MISSED_WINNER_MFE_PCT) or (
        r60 is not None and r60 >= MISSED_WINNER_MFE_PCT
    )
    is_loser = is_early or (r60 is not None and r60 <= LOSER_R5_PCT)

    if rec == "ALLOW":
        if is_early:
            return "ALLOW_EARLY_DUMP"
        if is_fee_churn:
            return "ALLOW_FLAT_FEE_CHURN"
        if is_winner:
            return "ALLOW_SUCCESS"
        return "ALLOW_NEUTRAL"

    if rec == "HOLD":
        if is_loser or is_early:
            return "HOLD_AVOIDED_LOSS"
        if is_big_winner:
            return "HOLD_MISSED_WINNER"
        return "HOLD_NEUTRAL"

    if rec == "REDUCE":
        if is_loser or is_early:
            return "REDUCE_AVOIDED_LOSS"
        if is_big_winner:
            return "REDUCE_MISSED_WINNER"
        return "REDUCE_NEUTRAL"

    return "UNKNOWN"


def score_analysis_feedback(
    *,
    analysis: dict[str, Any] | None,
    label: str | None,
    early_dump: bool,
) -> dict[str, Any]:
    """분석 품질 후보 플래그 — 가격예측 모델로 평가하지 않음."""

    ana = analysis or {}
    risks = [str(x).upper() for x in (ana.get("risk_factors") or [])]
    tone = str(ana.get("tone") or "").upper()
    lab = str(label or "").upper()
    flags: list[str] = []

    risk_high = any(
        x in risks
        for x in ("RISK_HIGH", "MARKET_WEAK", "NEWS_NEGATIVE", "ASSET_WEAK")
    ) or tone in {"BEARISH", "CAUTION"}
    risk_low = (
        not risk_high
        and tone in {"BULLISH", "NEUTRAL"}
        and not any("HIGH" in x for x in risks)
    )

    if risk_low and (early_dump or lab.startswith("EARLY_DUMP")):
        flags.append("analysis_error_candidate")
    if risk_high and lab == "GOOD_FOLLOW_THROUGH":
        flags.append("potential_overfilter")

    return {
        "analysis_error_candidate": "analysis_error_candidate" in flags,
        "potential_overfilter": "potential_overfilter" in flags,
        "flags": flags,
        "tone": tone or None,
        "risk_factors": risks[:10],
        "note": "분석은 가격예측이 아님 — risk/context consistency 진단",
    }


def build_feedback_payload(
    *,
    trading_prediction: dict[str, Any] | None,
    heuristic: dict[str, Any] | None,
    analysis: dict[str, Any] | None,
    obs: Any,
    row: Any,
) -> dict[str, Any]:
    """CLEAN outcome 완료 시 feedback 블록 생성."""

    trading = trading_prediction or {}
    heur = heuristic or {}
    label = outcome_label(obs) if obs is not None else "INSUFFICIENT_DATA"
    early = bool(getattr(obs, "early_dump", False)) if obs is not None else False
    r5 = getattr(row, "return_5m_pct", None)
    r15 = getattr(row, "return_15m_pct", None)
    r30 = getattr(row, "return_30m_pct", None)
    r60 = getattr(row, "return_60m_pct", None)
    mfe = getattr(obs, "mfe_pct", None) if obs is not None else getattr(row, "mfe_pct", None)
    mae = getattr(obs, "mae_pct", None) if obs is not None else getattr(row, "mae_pct", None)

    llm_rec = trading.get("recommendation") if trading.get("ok") else None
    heur_rec = heur.get("recommendation")

    llm_verdict = classify_prediction_correctness(
        recommendation=llm_rec,
        label=label,
        early_dump=early,
        return_5m=r5,
        return_60m=r60,
        mfe=mfe,
        mae=mae,
    )
    heur_verdict = classify_prediction_correctness(
        recommendation=heur_rec,
        label=label,
        early_dump=early,
        return_5m=r5,
        return_60m=r60,
        mfe=mfe,
        mae=mae,
    )

    return {
        "schema": "dual_llm_feedback_v1",
        "actual_outcome": {
            "return_5m": r5,
            "return_15m": r15,
            "return_30m": r30,
            "return_60m": r60,
            "mfe": mfe,
            "mae": mae,
            "early_dump": early,
            "label": label,
        },
        "trading_prediction": {
            "recommendation": llm_rec,
            "confidence": trading.get("confidence"),
            "early_dump_risk": trading.get("early_dump_risk"),
            "fee_churn_risk": trading.get("fee_churn_risk"),
            "ok": bool(trading.get("ok")),
        },
        "heuristic_prediction": {
            "recommendation": heur_rec,
        },
        "prediction_verdict": llm_verdict,
        "heuristic_verdict": heur_verdict,
        "analysis_feedback": score_analysis_feedback(
            analysis=analysis, label=label, early_dump=early
        ),
        "thresholds": {
            "winner_mfe_pct": WINNER_MFE_PCT,
            "winner_r60_pct": WINNER_R60_PCT,
            "loser_r5_pct": LOSER_R5_PCT,
            "missed_winner_mfe_pct": MISSED_WINNER_MFE_PCT,
            "fee_rt_pct": FEE_RT_PCT_THRESHOLD,
            "optimized": False,
        },
    }


def aggregate_feedback_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """동일 CLEAN cohort feedback row 집계."""

    total = len(rows)
    allow = hold = reduce = 0
    allow_success = allow_dump = 0
    hold_avoid = hold_miss = 0
    reduce_avoid = reduce_miss = 0
    fee_avoid = 0
    avoided_loser_value = 0.0
    missed_winner_value = 0.0
    mfe_vals: list[float] = []
    mae_vals: list[float] = []
    dump_pred_hit = 0
    dump_pred_total = 0

    for r in rows:
        fb = r.get("feedback") or {}
        tp = fb.get("trading_prediction") or {}
        rec = str(tp.get("recommendation") or "").upper()
        verd = str(fb.get("prediction_verdict") or "")
        out = fb.get("actual_outcome") or {}
        if rec == "ALLOW":
            allow += 1
        elif rec == "HOLD":
            hold += 1
        elif rec == "REDUCE":
            reduce += 1
        if verd == "ALLOW_SUCCESS":
            allow_success += 1
        if verd == "ALLOW_EARLY_DUMP":
            allow_dump += 1
        if verd == "HOLD_AVOIDED_LOSS":
            hold_avoid += 1
            avoided_loser_value += abs(_f(out.get("return_60m")) or 0.0)
        if verd == "HOLD_MISSED_WINNER":
            hold_miss += 1
            missed_winner_value += abs(_f(out.get("mfe")) or 0.0)
        if verd == "REDUCE_AVOIDED_LOSS":
            reduce_avoid += 1
            avoided_loser_value += abs(_f(out.get("return_60m")) or 0.0)
        if verd == "REDUCE_MISSED_WINNER":
            reduce_miss += 1
            missed_winner_value += abs(_f(out.get("mfe")) or 0.0)
        if verd in {"HOLD_AVOIDED_LOSS", "REDUCE_AVOIDED_LOSS"} and (
            str(out.get("label") or "").upper() in {"FLAT", "FLAT_FEE_CHURN"}
            or abs(_f(out.get("return_5m")) or 0) < FEE_RT_PCT_THRESHOLD
        ):
            fee_avoid += 1
        if out.get("mfe") is not None:
            mfe_vals.append(float(out["mfe"]))
        if out.get("mae") is not None:
            mae_vals.append(float(out["mae"]))
        # early dump detection: predicted HIGH/MEDIUM when actual dump
        if out.get("early_dump"):
            dump_pred_total += 1
            risk = str(tp.get("early_dump_risk") or "").upper()
            if risk in {"HIGH", "MEDIUM"}:
                dump_pred_hit += 1

    allow_n = max(allow, 1)
    net_benefit = avoided_loser_value - missed_winner_value
    return {
        "total_predictions": total,
        "ALLOW": allow,
        "HOLD": hold,
        "REDUCE": reduce,
        "ALLOW_SUCCESS": allow_success,
        "ALLOW_EARLY_DUMP": allow_dump,
        "HOLD_AVOIDED_LOSS": hold_avoid,
        "HOLD_MISSED_WINNER": hold_miss,
        "REDUCE_AVOIDED_LOSS": reduce_avoid,
        "REDUCE_MISSED_WINNER": reduce_miss,
        "allow_success_rate": round(allow_success / allow_n, 4) if allow else None,
        "EARLY_DUMP_DETECTION_RATE": (
            round(dump_pred_hit / dump_pred_total, 4) if dump_pred_total else None
        ),
        "FEE_CHURN_AVOIDANCE": fee_avoid,
        "avoided_losers": hold_avoid + reduce_avoid,
        "avoided_loser_value": round(avoided_loser_value, 6),
        "missed_winners": hold_miss + reduce_miss,
        "missed_winner_value": round(missed_winner_value, 6),
        "NET_FILTER_BENEFIT": round(net_benefit, 6),
        "avg_mfe": round(sum(mfe_vals) / len(mfe_vals), 6) if mfe_vals else None,
        "avg_mae": round(sum(mae_vals) / len(mae_vals), 6) if mae_vals else None,
    }
