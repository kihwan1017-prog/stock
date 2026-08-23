"""Paper Shadow aggregate 통계."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.operation.upbit_opportunity_shadow.exit_policy_ab import (
    summarize_exit_ab_from_shadows,
)
from stock_platform.operation.upbit_opportunity_shadow.entry_policy_ab import (
    summarize_entry_ab_from_shadows,
)
from stock_platform.operation.upbit_opportunity_shadow.constants import (
    SHADOW_STATUS_COMPLETED,
)
from stock_platform.operation.upbit_opportunity_shadow.entities import (
    UpbitOpportunityShadowEntity,
)

COHORT_SAMPLE_INSUFFICIENT = "SAMPLE_INSUFFICIENT"
COHORT_REVIEW_READY = "REVIEW_READY"
COHORT_REVIEW_THRESHOLD = 20


def compute_shadow_stats(session: Session) -> dict[str, Any]:
    rows = list(
        session.scalars(
            select(UpbitOpportunityShadowEntity).where(
                UpbitOpportunityShadowEntity.deleted_at.is_(None)
            )
        )
    )
    total = len(rows)
    allow_n = sum(1 for r in rows if r.recommendation == "ALLOW")
    reduce_n = sum(1 for r in rows if r.recommendation == "REDUCE")
    completed = [r for r in rows if r.status == SHADOW_STATUS_COMPLETED]
    completed_n = len(completed)

    def _pos_rate(attr: str) -> float | None:
        vals = [
            getattr(r, attr)
            for r in completed
            if getattr(r, attr) is not None
        ]
        if not vals:
            return None
        return round(sum(1 for v in vals if float(v) > 0) / len(vals) * 100, 2)

    def _avg(attr: str) -> float | None:
        vals = [
            float(getattr(r, attr))
            for r in completed
            if getattr(r, attr) is not None
        ]
        if not vals:
            return None
        return round(sum(vals) / len(vals), 4)

    rets_60 = [
        float(r.return_60m_pct)
        for r in completed
        if r.return_60m_pct is not None
    ]
    wins = [v for v in rets_60 if v > 0]
    mismatch_count = 0
    latest_completed = None
    for r in completed:
        watch = (r.evaluation_detail or {}).get("mismatch_watch") or {}
        if watch.get("code") == "SHADOW_EVALUATION_MISMATCH":
            mismatch_count += 1
        if r.completed_at is None:
            continue
        if latest_completed is None or (
            latest_completed.completed_at is None
            or r.completed_at > latest_completed.completed_at
        ):
            latest_completed = r

    cohort_status = (
        COHORT_REVIEW_READY
        if completed_n >= COHORT_REVIEW_THRESHOLD
        else COHORT_SAMPLE_INSUFFICIENT
    )

    return {
        "total_shadows": total,
        "allow_count": allow_n,
        "reduce_count": reduce_n,
        "completed_count": completed_n,
        "active_count": sum(1 for r in rows if r.status == "ACTIVE"),
        "cohort_n": completed_n,
        "cohort_status": cohort_status,
        "positive_5m_pct": _pos_rate("return_5m_pct"),
        "positive_15m_pct": _pos_rate("return_15m_pct"),
        "positive_30m_pct": _pos_rate("return_30m_pct"),
        "positive_60m_pct": _pos_rate("return_60m_pct"),
        "average_return_5m_pct": _avg("return_5m_pct"),
        "average_return_15m_pct": _avg("return_15m_pct"),
        "average_return_30m_pct": _avg("return_30m_pct"),
        "average_return_60m_pct": (
            round(sum(rets_60) / len(rets_60), 4) if rets_60 else None
        ),
        "win_rate_60m_pct": (
            round(len(wins) / len(rets_60) * 100, 2) if rets_60 else None
        ),
        "avg_mfe_pct": _avg("mfe_pct"),
        "avg_mae_pct": _avg("mae_pct"),
        "tp_hit_count": sum(1 for r in completed if r.tp_hit),
        "sl_hit_count": sum(1 for r in completed if r.sl_hit),
        "mismatch_count": mismatch_count,
        "latest_completed": (
            {
                "shadow_id": int(latest_completed.shadow_id),
                "symbol": latest_completed.symbol,
                "completed_at": (
                    latest_completed.completed_at.isoformat()
                    if latest_completed.completed_at
                    else None
                ),
                "return_60m_pct": latest_completed.return_60m_pct,
            }
            if latest_completed is not None
            else None
        ),
        "cohort_milestone": _cohort_milestone(session),
        "orders_created": 0,
        "paper_shadow": True,
        "shadow_only": True,
        "auto_threshold_tuning": False,
        "exit_policy_ab": summarize_exit_ab_from_shadows(completed),
        "entry_policy_ab": summarize_entry_ab_from_shadows(completed),
    }


def _cohort_milestone(session: Session) -> dict[str, Any]:
    try:
        from stock_platform.operation.upbit_opportunity_shadow.cohort_milestone import (
            compute_cohort_milestone_snapshot,
        )

        return compute_cohort_milestone_snapshot(session)
    except Exception:  # noqa: BLE001
        return {"status": "SAMPLE_ACCUMULATING", "error": "COMPUTE_FAILED"}
