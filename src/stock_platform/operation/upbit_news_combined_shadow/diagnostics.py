"""STEP N7 — Experiment sample milestone & news availability diagnostics."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from stock_platform.news.news_ai_analysis_constants import STATUS_COMPLETED
from stock_platform.news.news_ai_analysis_models import NewsAIAnalysis
from stock_platform.news.news_signal_models import NewsSignal
from stock_platform.operation.upbit_news_combined_shadow.entities import (
    UpbitNewsCombinedShadowEntity,
)
from stock_platform.operation.upbit_news_combined_shadow.policy import (
    EVAL_COMPLETED,
    NEWS_STATUS_MATCHED,
    NEWS_STATUS_NO_NEWS,
)
from stock_platform.operation.upbit_opportunity_shadow.entities import (
    UpbitOpportunityShadowEntity,
)

# A/B review 가능 조건 (매매 정책 적용 조건 아님)
MATCHED_COMPLETED_TARGET = 20
NO_NEWS_COMPLETED_TARGET = 20

STATUS_ACCUMULATING = "NEWS_AB_SAMPLE_ACCUMULATING"
STATUS_REVIEW_READY = "NEWS_AB_REVIEW_READY"


def _avg(vals: list[float]) -> float | None:
    if not vals:
        return None
    return round(sum(vals) / len(vals), 6)


def _med(vals: list[float]) -> float | None:
    if not vals:
        return None
    return round(float(median(vals)), 6)


def _win_rate(vals: list[float]) -> float | None:
    if not vals:
        return None
    return round(sum(1 for v in vals if v > 0) / len(vals), 4)


def _bucket_stats(
    rows: list[UpbitNewsCombinedShadowEntity],
) -> dict[str, Any]:
    r60 = [float(r.return_60m_pct) for r in rows if r.return_60m_pct is not None]
    mfe = [float(r.mfe_pct) for r in rows if r.mfe_pct is not None]
    mae = [float(r.mae_pct) for r in rows if r.mae_pct is not None]
    return {
        "n": len(rows),
        "completed_with_r60": len(r60),
        "win60": _win_rate(r60),
        "avg60": _avg(r60),
        "median60": _med(r60),
        "avg_mfe": _avg(mfe),
        "avg_mae": _avg(mae),
    }


def compute_sample_milestone(session: Session) -> dict[str, Any]:
    matched = list(
        session.scalars(
            select(UpbitNewsCombinedShadowEntity).where(
                UpbitNewsCombinedShadowEntity.evaluation_status
                == EVAL_COMPLETED,
                UpbitNewsCombinedShadowEntity.news_context_status
                == NEWS_STATUS_MATCHED,
            )
        )
    )
    no_news = list(
        session.scalars(
            select(UpbitNewsCombinedShadowEntity).where(
                UpbitNewsCombinedShadowEntity.evaluation_status
                == EVAL_COMPLETED,
                UpbitNewsCombinedShadowEntity.news_context_status
                == NEWS_STATUS_NO_NEWS,
            )
        )
    )
    matched_n = len(matched)
    no_news_n = len(no_news)
    ready = (
        matched_n >= MATCHED_COMPLETED_TARGET
        and no_news_n >= NO_NEWS_COMPLETED_TARGET
    )
    return {
        "status": STATUS_REVIEW_READY if ready else STATUS_ACCUMULATING,
        "ready": ready,
        "matched_completed": matched_n,
        "matched_target": MATCHED_COMPLETED_TARGET,
        "matched_met": matched_n >= MATCHED_COMPLETED_TARGET,
        "no_news_completed": no_news_n,
        "no_news_target": NO_NEWS_COMPLETED_TARGET,
        "no_news_met": no_news_n >= NO_NEWS_COMPLETED_TARGET,
        "mismatch_count": 0,
        "control_mutation": False,
        "not_a_trading_policy_gate": True,
        "note": "A/B review readiness only — not Scanner/Gate apply condition",
    }


def compute_observation_stats(session: Session) -> dict[str, Any]:
    rows = list(session.scalars(select(UpbitNewsCombinedShadowEntity)))
    completed = [
        r for r in rows if r.evaluation_status == EVAL_COMPLETED
    ]
    matched = [
        r
        for r in completed
        if r.news_context_status == NEWS_STATUS_MATCHED
    ]
    no_news = [
        r for r in completed if r.news_context_status == NEWS_STATUS_NO_NEWS
    ]
    boost = [r for r in completed if r.experimental_decision == "BOOST"]
    deprior = [
        r for r in completed if r.experimental_decision == "DEPRIORITIZE"
    ]
    unchanged = [
        r for r in completed if r.experimental_decision == "UNCHANGED"
    ]

    deltas = [
        int(r.rank_delta)
        for r in rows
        if r.rank_delta is not None
    ]
    return {
        "total_experiment": len(rows),
        "completed": len(completed),
        "active": sum(1 for r in rows if r.evaluation_status == "ACTIVE"),
        "by_news_context": {
            "NEWS_MATCHED": sum(
                1 for r in rows if r.news_context_status == "NEWS_MATCHED"
            ),
            "NO_NEWS": sum(
                1 for r in rows if r.news_context_status == "NO_NEWS"
            ),
            "EXCLUDED_ONLY": sum(
                1 for r in rows if r.news_context_status == "EXCLUDED_ONLY"
            ),
        },
        "by_decision": {
            "BOOST": sum(1 for r in rows if r.experimental_decision == "BOOST"),
            "UNCHANGED": sum(
                1 for r in rows if r.experimental_decision == "UNCHANGED"
            ),
            "DEPRIORITIZE": sum(
                1 for r in rows if r.experimental_decision == "DEPRIORITIZE"
            ),
        },
        "matched": _bucket_stats(matched),
        "no_news": _bucket_stats(no_news),
        "boost": _bucket_stats(boost),
        "deprioritize": _bucket_stats(deprior),
        "unchanged": _bucket_stats(unchanged),
        "rank_delta": {
            "n": len(deltas),
            "avg": _avg([float(d) for d in deltas]),
            "positive": sum(1 for d in deltas if d > 0),
            "zero": sum(1 for d in deltas if d == 0),
            "negative": sum(1 for d in deltas if d < 0),
        },
        "interpretation_limit": (
            "experimental_rank improvement alone does not prove better symbols; "
            "await accumulated outcomes; no statistical certainty claimed"
        ),
    }


def list_matched_details(
    session: Session, *, limit: int = 20
) -> list[dict[str, Any]]:
    rows = list(
        session.scalars(
            select(UpbitNewsCombinedShadowEntity)
            .where(
                UpbitNewsCombinedShadowEntity.news_context_status
                == NEWS_STATUS_MATCHED
            )
            .order_by(UpbitNewsCombinedShadowEntity.created_at.desc())
            .limit(max(1, min(limit, 50)))
        )
    )
    out: list[dict[str, Any]] = []
    for r in rows:
        snap = r.news_snapshot if isinstance(r.news_snapshot, dict) else {}
        influence = snap.get("influence_signals") or []
        first = influence[0] if influence else {}
        out.append(
            {
                "experiment_id": r.experiment_id,
                "scanner_run_id": r.scanner_run_id,
                "symbol": r.symbol,
                "t0": (
                    r.candidate_detected_at.isoformat()
                    if r.candidate_detected_at
                    else None
                ),
                "scanner_score": r.control_scanner_score,
                "actual_rank": r.control_scanner_rank,
                "signal_ids": r.news_signal_ids,
                "direction": first.get("direction"),
                "strength": first.get("strength"),
                "reliability": first.get("reliability"),
                "age": first.get("published_at"),
                "contribution": first.get("contribution"),
                "news_component": r.news_component_normalized,
                "experimental_score": r.experimental_combined_score,
                "experimental_rank": r.counterfactual_rank,
                "rank_delta": r.rank_delta,
                "return_60m_pct": r.return_60m_pct,
                "mfe_pct": r.mfe_pct,
                "mae_pct": r.mae_pct,
                "evaluation_status": r.evaluation_status,
            }
        )
    return out


def diagnose_news_availability(session: Session) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=24)

    articles_24h = session.execute(
        text(
            """
            SELECT source_code, COUNT(*) AS c
            FROM news.news_article
            WHERE created_at >= :since
              AND source_code IN ('UPBIT_NOTICE', 'CRYPTO_NEWS')
            GROUP BY source_code
            """
        ),
        {"since": since},
    ).mappings().all()

    trusted_24h = session.execute(
        text(
            """
            SELECT COUNT(DISTINCT a.article_id) AS c
            FROM news.news_article a
            CROSS JOIN LATERAL jsonb_array_elements(
              COALESCE(a.raw_data->'symbol_mapping'->'mappings', '[]'::jsonb)
            ) m
            WHERE a.created_at >= :since
              AND m.value->>'quality_status' = 'TRUSTED'
            """
        ),
        {"since": since},
    ).scalar() or 0

    n4_completed = session.scalar(
        select(func.count()).select_from(NewsAIAnalysis).where(
            NewsAIAnalysis.status == STATUS_COMPLETED
        )
    ) or 0
    n4_completed_24h = session.scalar(
        select(func.count()).select_from(NewsAIAnalysis).where(
            NewsAIAnalysis.status == STATUS_COMPLETED,
            NewsAIAnalysis.created_at >= since,
        )
    ) or 0

    valid_signals = list(
        session.scalars(
            select(NewsSignal).where(NewsSignal.signal_status == "VALID")
        )
    )
    valid_syms = sorted({str(s.symbol).upper() for s in valid_signals})

    ages_h: list[float] = []
    for s in valid_signals:
        if s.published_at is None:
            continue
        ages_h.append(
            (now - s.published_at.astimezone(timezone.utc)).total_seconds()
            / 3600.0
        )

    scan_all = set(
        session.scalars(
            select(UpbitOpportunityShadowEntity.symbol).where(
                UpbitOpportunityShadowEntity.deleted_at.is_(None)
            )
        )
    )
    scan_24h = set(
        session.scalars(
            select(UpbitOpportunityShadowEntity.symbol).where(
                UpbitOpportunityShadowEntity.deleted_at.is_(None),
                UpbitOpportunityShadowEntity.detected_at >= since,
            )
        )
    )
    scan_all_u = {str(x).upper() for x in scan_all}
    scan_24h_u = {str(x).upper() for x in scan_24h}
    overlap_all = sorted(set(valid_syms) & scan_all_u)
    overlap_24h = sorted(set(valid_syms) & scan_24h_u)
    overlap_rate = (
        round(len(overlap_all) / max(1, len(scan_all_u)), 4)
        if scan_all_u
        else 0.0
    )

    # EXCLUDED reason peek
    excl_reasons: dict[str, int] = {}
    for row in session.scalars(
        select(UpbitNewsCombinedShadowEntity).where(
            UpbitNewsCombinedShadowEntity.news_context_status
            == "EXCLUDED_ONLY"
        )
    ):
        snap = row.news_snapshot if isinstance(row.news_snapshot, dict) else {}
        for item in snap.get("excluded_signals") or []:
            if isinstance(item, dict):
                key = str(item.get("exclude_reason") or "UNKNOWN")
                excl_reasons[key] = excl_reasons.get(key, 0) + 1

    matched_n = session.scalar(
        select(func.count()).select_from(UpbitNewsCombinedShadowEntity).where(
            UpbitNewsCombinedShadowEntity.news_context_status
            == NEWS_STATUS_MATCHED
        )
    ) or 0

    # root cause classification
    article_vol = sum(int(r["c"]) for r in articles_24h)
    causes: list[str] = []
    if article_vol < 5 or len(valid_signals) < 5:
        causes.append("NEWS_PIPELINE_VOLUME_LOW")
    if len(overlap_all) == 0:
        causes.append("SYMBOL_OVERLAP_LOW")
    if excl_reasons.get("LOOKBACK_EXCEEDED") or excl_reasons.get(
        "EXPIRED_AT_T0"
    ) or excl_reasons.get("FUTURE_SIGNAL_AT") or excl_reasons.get(
        "FUTURE_PUBLISHED_AT"
    ) or excl_reasons.get("FUTURE_COLLECTED_AT"):
        causes.append("TIMESTAMP_OVERLAP_LOW")
    if excl_reasons.get("STATUS_STALE") or "EXPIRED" in str(excl_reasons):
        causes.append("SIGNAL_STALE")
    # historical Top N not persisted
    causes.append("SOURCE_COVERAGE_LOW")
    causes.append("EXPERIMENT_SOURCE_TOO_NARROW")

    if matched_n == 0:
        if len(causes) >= 3:
            root = "MIXED"
        else:
            root = causes[0] if causes else "MIXED"
    else:
        root = "MIXED" if len(causes) > 1 else (causes[0] if causes else "OK")

    return {
        "window": "24h",
        "collected_articles": [dict(r) for r in articles_24h],
        "collected_articles_total": article_vol,
        "trusted_mapped_articles": int(trusted_24h),
        "completed_n4_analyses_total": int(n4_completed),
        "completed_n4_analyses_24h": int(n4_completed_24h),
        "valid_n5_signals": len(valid_signals),
        "unique_signal_symbols": valid_syms,
        "signal_age_hours": {
            "n": len(ages_h),
            "avg": _avg(ages_h),
            "median": _med(ages_h),
            "max": round(max(ages_h), 3) if ages_h else None,
        },
        "scanner_symbols_all": sorted(scan_all_u),
        "scanner_symbols_24h": sorted(scan_24h_u),
        "intersection_all": overlap_all,
        "intersection_24h": overlap_24h,
        "intersection_count_all": len(overlap_all),
        "overlap_rate_all": overlap_rate,
        "excluded_reason_counts": excl_reasons,
        "news_matched_rows": int(matched_n),
        "root_cause": root,
        "root_cause_factors": causes,
        "top_n_history_reusable": False,
        "top_n_history_note": (
            "SOURCE_COVERAGE_LIMITED: full Top N (incl HOLD) not persisted; "
            "only ALLOW/REDUCE shadows + optional in-memory last_result"
        ),
        "n4_n5_scheduler_auto_enable": False,
        "look_ahead_relaxed": False,
    }
