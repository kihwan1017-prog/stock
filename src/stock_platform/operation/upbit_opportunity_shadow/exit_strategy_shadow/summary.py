"""Exit strategy shadow research summary — bounded queries."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stock_platform.operation.upbit_opportunity_shadow.exit_strategy_shadow.constants import (
    CHECKPOINT_N,
    FAMILY_BASELINE_MA,
    SAMPLE_NATURAL_AUTO,
    STATUS_ACTIVE,
    STATUS_MATURED,
    STATUS_TRIGGERED,
    classify_checkpoint,
    variant_grid,
)
from stock_platform.operation.upbit_opportunity_shadow.exit_strategy_shadow.entities import (
    UpbitExitStrategyShadowEntity,
)
from stock_platform.operation.upbit_opportunity_shadow.exit_strategy_shadow.scheduler import (
    scheduler_status,
)
from stock_platform.operation.upbit_short_term_turnover.metrics import (
    max_drawdown,
    profit_factor,
)


def _f(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def summarize_exit_strategy_shadow(
    session: Session,
    *,
    user_broker_account_id: int | None = None,
) -> dict[str, Any]:
    """Variant 비교 요약 — NATURAL_AUTO matured/triggered only for valid N."""

    base = select(UpbitExitStrategyShadowEntity)
    if user_broker_account_id is not None:
        base = base.where(
            UpbitExitStrategyShadowEntity.user_broker_account_id
            == int(user_broker_account_id)
        )

    active = int(
        session.scalar(
            select(func.count()).select_from(UpbitExitStrategyShadowEntity).where(
                UpbitExitStrategyShadowEntity.status == STATUS_ACTIVE,
                *(
                    [
                        UpbitExitStrategyShadowEntity.user_broker_account_id
                        == int(user_broker_account_id)
                    ]
                    if user_broker_account_id is not None
                    else []
                ),
            )
        )
        or 0
    )

    rows = list(
        session.scalars(
            base.where(
                UpbitExitStrategyShadowEntity.sample_class == SAMPLE_NATURAL_AUTO,
                UpbitExitStrategyShadowEntity.status.in_(
                    [STATUS_TRIGGERED, STATUS_MATURED]
                ),
            )
        )
    )

    by_variant: dict[tuple[str, str], list[UpbitExitStrategyShadowEntity]] = (
        defaultdict(list)
    )
    for r in rows:
        by_variant[(r.strategy_family, r.variant_code)].append(r)

    ma_nets = [
        _f(r.net_pnl)
        for r in by_variant.get((FAMILY_BASELINE_MA, "MA_DEAD_CROSS"), [])
        if _f(r.net_pnl) is not None
    ]
    ma_net_sum = sum(ma_nets) if ma_nets else 0.0

    variants_out: list[dict[str, Any]] = []
    for spec in variant_grid():
        key = (spec["strategy_family"], spec["variant_code"])
        group = by_variant.get(key, [])
        nets = [_f(r.net_pnl) for r in group if _f(r.net_pnl) is not None]
        nets_f = [float(n) for n in nets if n is not None]
        n = len(nets_f)
        wins = [x for x in nets_f if x > 0]
        losses = [x for x in nets_f if x <= 0]
        holds = [
            int(r.hold_seconds)
            for r in group
            if r.hold_seconds is not None
        ]
        holds_sorted = sorted(holds)
        median_hold = (
            holds_sorted[len(holds_sorted) // 2] / 60.0 if holds_sorted else None
        )
        avg_hold = (sum(holds) / len(holds) / 60.0) if holds else None
        net_sum = sum(nets_f)
        pf = profit_factor(nets_f) if nets_f else None
        mdd = max_drawdown(nets_f) if nets_f else None
        vs_ma = net_sum - ma_net_sum if ma_nets else None
        variants_out.append(
            {
                "strategy_family": spec["strategy_family"],
                "variant_code": spec["variant_code"],
                "threshold_value": (
                    float(spec["threshold_value"])
                    if spec["threshold_value"] is not None
                    else None
                ),
                "time_horizon_minutes": spec["time_horizon_minutes"],
                "n": n,
                "checkpoint": classify_checkpoint(n),
                "checkpoint_target": 300,
                "win_rate": (len(wins) / n) if n else None,
                "net_pnl": round(net_sum, 4) if n else None,
                "profit_factor": round(pf, 4) if pf is not None else None,
                "max_drawdown": round(mdd, 4) if mdd is not None else None,
                "avg_hold_min": round(avg_hold, 2) if avg_hold is not None else None,
                "median_hold_min": (
                    round(median_hold, 2) if median_hold is not None else None
                ),
                "vs_ma_net_delta": (
                    round(vs_ma, 4) if vs_ma is not None else None
                ),
                "readiness": (
                    "READY_FOR_REVIEW"
                    if (
                        n >= 300
                        and net_sum > 0
                        and pf is not None
                        and pf >= 1.10
                    )
                    else "NOT_READY"
                ),
                "auto_promote": False,
            }
        )

    best_net = max(
        (v for v in variants_out if v["net_pnl"] is not None),
        key=lambda x: x["net_pnl"],
        default=None,
    )
    best_pf = max(
        (v for v in variants_out if v["profit_factor"] is not None),
        key=lambda x: x["profit_factor"],
        default=None,
    )

    natural_entries = int(
        session.scalar(
            select(func.count(func.distinct(
                UpbitExitStrategyShadowEntity.entry_order_id
            ))).where(
                UpbitExitStrategyShadowEntity.sample_class == SAMPLE_NATURAL_AUTO,
                *(
                    [
                        UpbitExitStrategyShadowEntity.user_broker_account_id
                        == int(user_broker_account_id)
                    ]
                    if user_broker_account_id is not None
                    else []
                ),
            )
        )
        or 0
    )

    return {
        "ok": True,
        "research_only": True,
        "real_exit_policy_changed": False,
        "real_baseline": {
            "MA_DEAD_CROSS": "REAL_ACTIVE",
            "STOP_LOSS": "NOT_CONFIGURED",
            "TAKE_PROFIT": "NOT_CONFIGURED",
            "TRAILING": "SHADOW",
            "TIME_EXIT": "RESEARCH",
        },
        "scheduler": scheduler_status(),
        "natural_entries": natural_entries,
        "active_experiments": active,
        "matured_or_triggered": len(rows),
        "forward_valid_n_note": "per-variant n below; HISTORICAL excluded",
        "checkpoints_supported": list(CHECKPOINT_N),
        "best_net_variant": best_net,
        "best_pf_variant": best_pf,
        "variants": variants_out,
    }


def entry_detail_comparison(
    session: Session,
    *,
    entry_order_id: int,
) -> dict[str, Any]:
    rows = list(
        session.scalars(
            select(UpbitExitStrategyShadowEntity).where(
                UpbitExitStrategyShadowEntity.entry_order_id
                == int(entry_order_id)
            )
        )
    )
    if not rows:
        return {"ok": False, "reason": "NOT_FOUND"}
    head = rows[0]
    by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_family[r.strategy_family].append(
            {
                "variant_code": r.variant_code,
                "status": r.status,
                "trigger_at": r.trigger_at.isoformat() if r.trigger_at else None,
                "trigger_price": _f(r.trigger_price),
                "net_pnl": _f(r.net_pnl),
                "gross_pnl": _f(r.gross_pnl),
                "hold_seconds": r.hold_seconds,
                "peak_price": _f(r.peak_price),
            }
        )
    return {
        "ok": True,
        "entry": {
            "entry_order_id": int(head.entry_order_id),
            "symbol": head.symbol,
            "entry_at": head.entry_at.isoformat() if head.entry_at else None,
            "entry_price": _f(head.entry_price),
            "sample_class": head.sample_class,
            "actual_exit_reason": head.actual_exit_reason,
            "actual_exit_at": (
                head.actual_exit_at.isoformat() if head.actual_exit_at else None
            ),
            "actual_exit_price": _f(head.actual_exit_price),
            "actual_net_pnl": _f(head.actual_net_pnl),
        },
        "families": dict(by_family),
    }
