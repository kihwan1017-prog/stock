"""Paper Shadow aggregate 통계."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.operation.upbit_opportunity_shadow.constants import (
    SHADOW_STATUS_COMPLETED,
)
from stock_platform.operation.upbit_opportunity_shadow.entities import (
    UpbitOpportunityShadowEntity,
)


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

    def _pos_rate(attr: str) -> float | None:
        vals = [
            getattr(r, attr)
            for r in completed
            if getattr(r, attr) is not None
        ]
        if not vals:
            return None
        return round(sum(1 for v in vals if float(v) > 0) / len(vals) * 100, 2)

    rets_60 = [
        float(r.return_60m_pct)
        for r in completed
        if r.return_60m_pct is not None
    ]
    mfes = [float(r.mfe_pct) for r in completed if r.mfe_pct is not None]
    maes = [float(r.mae_pct) for r in completed if r.mae_pct is not None]
    wins = [v for v in rets_60 if v > 0]

    return {
        "total_shadows": total,
        "allow_count": allow_n,
        "reduce_count": reduce_n,
        "completed_count": len(completed),
        "active_count": sum(1 for r in rows if r.status == "ACTIVE"),
        "positive_15m_pct": _pos_rate("return_15m_pct"),
        "positive_30m_pct": _pos_rate("return_30m_pct"),
        "positive_60m_pct": _pos_rate("return_60m_pct"),
        "average_return_60m_pct": (
            round(sum(rets_60) / len(rets_60), 4) if rets_60 else None
        ),
        "win_rate_60m_pct": (
            round(len(wins) / len(rets_60) * 100, 2) if rets_60 else None
        ),
        "avg_mfe_pct": round(sum(mfes) / len(mfes), 4) if mfes else None,
        "avg_mae_pct": round(sum(maes) / len(maes), 4) if maes else None,
        "orders_created": 0,
        "paper_shadow": True,
    }
