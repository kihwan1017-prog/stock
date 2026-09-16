"""Forward shadow aggregate metrics — READ ONLY."""

from __future__ import annotations

import statistics
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stock_platform.operation.upbit_opportunity_shadow.ma_exit_forward_shadow.constants import (
    CONFIRM_EVALUATIONS,
    PRIMARY_SHADOW_RULE,
    RULE_VERSION,
    SAMPLE_STAGE_COLLECTION,
    SAMPLE_STAGE_EARLY,
    SAMPLE_STAGE_PRIMARY,
    SAMPLE_STAGE_PROMOTION,
    STATUS_COMPLETED,
    STATUS_PRE_EXISTING_EXCLUDED,
)
from stock_platform.operation.upbit_opportunity_shadow.ma_exit_forward_shadow.entities import (
    UpbitMaExitForwardShadowEntity,
)
from stock_platform.operation.upbit_opportunity_shadow.ma_exit_forward_shadow.service import (
    is_early_dump,
)


def sample_stage(n: int) -> str:
    if n < 30:
        return SAMPLE_STAGE_COLLECTION
    if n < 100:
        return SAMPLE_STAGE_EARLY
    if n < 500:
        return SAMPLE_STAGE_PRIMARY
    return SAMPLE_STAGE_PROMOTION


def _pf(net_list: list[float]) -> float | None:
    wins = sum(x for x in net_list if x > 0)
    losses = abs(sum(x for x in net_list if x < 0))
    if losses <= 0:
        return None if wins <= 0 else float("inf")
    return round(wins / losses, 4)


def _arm_kpis(nets: list[float]) -> dict[str, Any]:
    n = len(nets)
    if n == 0:
        return {
            "sample_count": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": None,
            "net_pnl": 0.0,
            "profit_factor": None,
            "expectancy": None,
        }
    wins = sum(1 for x in nets if x > 0)
    losses = n - wins
    return {
        "sample_count": n,
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / n, 4),
        "net_pnl": round(sum(nets), 4),
        "profit_factor": _pf(nets),
        "expectancy": round(sum(nets) / n, 4),
    }


def summarize_forward_shadow(
    session: Session,
    *,
    user_broker_account_id: int | None = None,
) -> dict[str, Any]:
    q = select(UpbitMaExitForwardShadowEntity).where(
        UpbitMaExitForwardShadowEntity.status != STATUS_PRE_EXISTING_EXCLUDED
    )
    if user_broker_account_id is not None:
        q = q.where(
            UpbitMaExitForwardShadowEntity.user_broker_account_id
            == int(user_broker_account_id)
        )
    rows = list(session.scalars(q))
    completed = [r for r in rows if r.status == STATUS_COMPLETED]
    baseline_nets = [float(r.baseline_net_pnl) for r in completed if r.baseline_net_pnl is not None]
    shadow_nets = [float(r.shadow_net_pnl) for r in completed if r.shadow_net_pnl is not None]

    shadow_better = baseline_better = tie = 0
    extra_loss_delay = 0
    stop_loss_delayed = kill_delayed = risk_delayed = 0
    early_baseline = early_shadow = 0
    holds_b: list[float] = []
    holds_s: list[float] = []

    for r in completed:
        if r.baseline_net_pnl is None or r.shadow_net_pnl is None:
            continue
        b = float(r.baseline_net_pnl)
        s = float(r.shadow_net_pnl)
        if s > b + 1e-9:
            shadow_better += 1
        elif b > s + 1e-9:
            baseline_better += 1
        else:
            tie += 1
        st = dict(r.shadow_state_json or {})
        if st.get("extra_loss_from_delay"):
            extra_loss_delay += 1
        if st.get("stop_loss_delayed"):
            stop_loss_delayed += 1
        if st.get("kill_delayed"):
            kill_delayed += 1
        if st.get("risk_delayed"):
            risk_delayed += 1
        if is_early_dump(r.baseline_exit_at, r.entry_at) and (
            r.baseline_exit_reason or ""
        ).upper().startswith("MA_DEAD"):
            early_baseline += 1
        if is_early_dump(r.shadow_exit_at, r.entry_at) and (
            r.shadow_exit_reason or ""
        ).upper().startswith("MA_DEAD"):
            early_shadow += 1
        if r.baseline_exit_at and r.entry_at:
            holds_b.append(
                (r.baseline_exit_at - r.entry_at).total_seconds()
            )
        if r.shadow_exit_at and r.entry_at:
            holds_s.append((r.shadow_exit_at - r.entry_at).total_seconds())

    by_symbol: dict[str, dict[str, Any]] = {}
    for r in completed:
        sym = r.symbol
        bucket = by_symbol.setdefault(
            sym,
            {"symbol": sym, "sample": 0, "baseline_net": 0.0, "confirm2_net": 0.0},
        )
        bucket["sample"] += 1
        if r.baseline_net_pnl is not None:
            bucket["baseline_net"] += float(r.baseline_net_pnl)
        if r.shadow_net_pnl is not None:
            bucket["confirm2_net"] += float(r.shadow_net_pnl)
    for sym, b in by_symbol.items():
        b["benefit"] = round(b["confirm2_net"] - b["baseline_net"], 4)
        b["baseline_net"] = round(b["baseline_net"], 4)
        b["confirm2_net"] = round(b["confirm2_net"], 4)
        b["fragility_hint"] = b["sample"] < 3

    daily: dict[str, dict[str, float]] = {}
    for r in completed:
        if r.baseline_exit_at is None:
            continue
        day = r.baseline_exit_at.astimezone(timezone.utc).date().isoformat()
        d = daily.setdefault(day, {"baseline_net": 0.0, "shadow_net": 0.0})
        if r.baseline_net_pnl is not None:
            d["baseline_net"] += float(r.baseline_net_pnl)
        if r.shadow_net_pnl is not None:
            d["shadow_net"] += float(r.shadow_net_pnl)
    daily_rows = [
        {
            "date": k,
            "baseline_net": round(v["baseline_net"], 4),
            "shadow_net": round(v["shadow_net"], 4),
            "difference": round(v["shadow_net"] - v["baseline_net"], 4),
        }
        for k, v in sorted(daily.items())
    ]

    n_closed = len(completed)
    return {
        "schema": "upbit_ma_exit_forward_shadow_v1",
        "research_only": True,
        "real_policy_changed": False,
        "primary_shadow": PRIMARY_SHADOW_RULE,
        "rule_version": RULE_VERSION,
        "confirm_evaluations": CONFIRM_EVALUATIONS,
        "sample_stage": sample_stage(n_closed),
        "cohort": {
            "total_rows": len(rows),
            "active": sum(1 for r in rows if r.status == "ACTIVE"),
            "shadow_tracking": sum(1 for r in rows if r.status == "SHADOW_TRACKING"),
            "completed": n_closed,
            "pre_existing_excluded": sum(
                1 for r in rows if r.status == STATUS_PRE_EXISTING_EXCLUDED
            ),
        },
        "baseline": _arm_kpis(baseline_nets),
        "confirm2": _arm_kpis(shadow_nets),
        "net_benefit": round(sum(shadow_nets) - sum(baseline_nets), 4)
        if baseline_nets and shadow_nets
        else None,
        "comparison": {
            "shadow_better_count": shadow_better,
            "baseline_better_count": baseline_better,
            "tie_count": tie,
        },
        "early_dump": {
            "baseline": early_baseline,
            "confirm2": early_shadow,
        },
        "safety": {
            "extra_loss_from_delay": extra_loss_delay,
            "confirm2_delayed_loss_count": extra_loss_delay,
            "stop_loss_delayed": stop_loss_delayed,
            "kill_delayed": kill_delayed,
            "risk_delayed": risk_delayed,
            "stop_loss_override_count_must_be_zero": stop_loss_delayed,
        },
        "hold_seconds": {
            "baseline_avg": round(statistics.mean(holds_b), 2) if holds_b else None,
            "baseline_median": round(statistics.median(holds_b), 2) if holds_b else None,
            "confirm2_avg": round(statistics.mean(holds_s), 2) if holds_s else None,
            "confirm2_median": round(statistics.median(holds_s), 2) if holds_s else None,
        },
        "by_symbol": sorted(by_symbol.values(), key=lambda x: x["benefit"], reverse=True),
        "daily": daily_rows,
        "slippage_modeled": "SLIPPAGE_NOT_MODELED",
    }


def list_forward_shadow_rows(
    session: Session,
    *,
    user_broker_account_id: int | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    q = select(UpbitMaExitForwardShadowEntity).order_by(
        UpbitMaExitForwardShadowEntity.created_at.desc()
    )
    if user_broker_account_id is not None:
        q = q.where(
            UpbitMaExitForwardShadowEntity.user_broker_account_id
            == int(user_broker_account_id)
        )
    count_q = select(func.count()).select_from(UpbitMaExitForwardShadowEntity)
    if user_broker_account_id is not None:
        count_q = count_q.where(
            UpbitMaExitForwardShadowEntity.user_broker_account_id
            == int(user_broker_account_id)
        )
    total = session.scalar(count_q) or 0
    offset = max(0, (page - 1) * page_size)
    rows = list(session.scalars(q.offset(offset).limit(page_size)))

    items = []
    for r in rows:
        diff = None
        if r.difference_net is not None:
            diff = float(r.difference_net)
        elif r.baseline_net_pnl is not None and r.shadow_net_pnl is not None:
            diff = float(r.shadow_net_pnl - r.baseline_net_pnl)
        items.append(
            {
                "shadow_row_id": int(r.shadow_row_id),
                "symbol": r.symbol,
                "status": r.status,
                "research_only": True,
                "entry_at": r.entry_at.isoformat() if r.entry_at else None,
                "entry_price": str(r.entry_price),
                "baseline_exit_reason": r.baseline_exit_reason,
                "baseline_exit_at": (
                    r.baseline_exit_at.isoformat() if r.baseline_exit_at else None
                ),
                "baseline_net_pnl": (
                    float(r.baseline_net_pnl) if r.baseline_net_pnl is not None else None
                ),
                "shadow_exit_reason": r.shadow_exit_reason,
                "shadow_exit_at": (
                    r.shadow_exit_at.isoformat() if r.shadow_exit_at else None
                ),
                "shadow_net_pnl": (
                    float(r.shadow_net_pnl) if r.shadow_net_pnl is not None else None
                ),
                "shadow_confirmation_count": int(r.shadow_confirmation_count or 0),
                "difference_net": diff,
                "rule_version": r.rule_version,
            }
        )
    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": int(total),
        "research_only_label": "연구용 · REAL 미적용",
    }
