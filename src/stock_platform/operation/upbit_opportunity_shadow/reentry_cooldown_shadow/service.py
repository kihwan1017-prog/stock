"""Post-exit re-entry cooldown shadow service — REAL entry 차단 없음."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.operation.upbit_opportunity_shadow.reentry_cooldown_shadow.constants import (
    FAMILY,
    RULE_VERSION,
    STATUS_COMPLETED,
    STATUS_OBSERVED,
    VARIANT_R0,
    VARIANT_R1,
    VARIANT_R2,
    VARIANT_R3,
    VARIANT_SECONDS,
)
from stock_platform.operation.upbit_opportunity_shadow.reentry_cooldown_shadow.entities import (
    UpbitPostExitReentryCooldownShadowEntity,
)
from stock_platform.operation.upbit_opportunity_shadow.trailing_forward_shadow.baseline import (
    resolve_baseline_outcome_for_entry,
)
from stock_platform.risk_engine.strategy_owned_entities import (
    StrategyPositionBindingEntity,
)


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _would_block(gap_seconds: float, cooldown: int) -> bool:
    if cooldown <= 0:
        return False
    return gap_seconds < float(cooldown)


def observe_reentry_on_new_entry(
    session: Session,
    *,
    user_broker_account_id: int,
    symbol: str,
    new_entry_order_id: int | None,
    new_entry_at: datetime,
) -> dict[str, Any]:
    """REAL BUY 직후 — 동일 symbol 직전 CLOSED 대비 gap 관찰만."""

    if new_entry_order_id is None:
        return {"ok": False, "reason": "NO_ENTRY_ORDER"}

    existing = session.scalar(
        select(UpbitPostExitReentryCooldownShadowEntity).where(
            UpbitPostExitReentryCooldownShadowEntity.new_entry_order_id
            == int(new_entry_order_id)
        )
    )
    if existing is not None:
        return {"ok": True, "duplicate": True, "shadow_id": int(existing.shadow_id)}

    sym = str(symbol).upper()
    uba = int(user_broker_account_id)
    entry_at = _as_utc(new_entry_at) or datetime.now(timezone.utc)

    prev = session.scalar(
        select(StrategyPositionBindingEntity)
        .where(
            StrategyPositionBindingEntity.user_broker_account_id == uba,
            StrategyPositionBindingEntity.symbol == sym,
            StrategyPositionBindingEntity.status == "CLOSED",
            StrategyPositionBindingEntity.closed_at.is_not(None),
            StrategyPositionBindingEntity.closed_at < entry_at,
        )
        .order_by(StrategyPositionBindingEntity.closed_at.desc())
        .limit(1)
    )
    if prev is None:
        return {"ok": True, "observed": False, "reason": "NO_PRIOR_EXIT"}

    prev_exit_at = _as_utc(prev.closed_at)
    if prev_exit_at is None:
        return {"ok": True, "observed": False, "reason": "NO_PRIOR_EXIT_AT"}

    gap = max(0.0, (entry_at - prev_exit_at).total_seconds())
    meta = dict(prev.meta_json or {})
    prev_exit_oid = meta.get("exit_order_id")
    prev_reason = None
    if prev_exit_oid is not None:
        from stock_platform.order.entities import TradingOrderEntity

        sell = session.get(TradingOrderEntity, int(prev_exit_oid))
        if sell is not None:
            mp = getattr(sell, "metadata_payload", None) or {}
            if isinstance(mp, dict):
                prev_reason = str(
                    mp.get("exit_reason") or mp.get("signal_reason") or ""
                ) or None

    variants: dict[str, Any] = {}
    for code, secs in VARIANT_SECONDS.items():
        wb = _would_block(gap, int(secs))
        variants[code] = {
            "cooldown_seconds": int(secs),
            "WOULD_BLOCK": wb,
            # NULL 금지 — ALLOW|BLOCK (이 lab은 시간 cooldown만, UNKNOWN 없음)
            "SHADOW_DECISION": "BLOCK" if wb else "ALLOW",
            "avoided_net_impact": None,  # close 시 채움
        }

    row = UpbitPostExitReentryCooldownShadowEntity(
        user_broker_account_id=uba,
        symbol=sym,
        family=FAMILY,
        rule_version=RULE_VERSION,
        previous_exit_order_id=int(prev_exit_oid) if prev_exit_oid else None,
        previous_exit_at=prev_exit_at,
        previous_exit_reason=(prev_reason or "")[:64] or None,
        new_entry_order_id=int(new_entry_order_id),
        new_entry_at=entry_at,
        gap_seconds=Decimal(str(round(gap, 4))),
        status=STATUS_OBSERVED,
        research_only=True,
        variants_json=variants,
        context_json={
            "prior_risk_binding_id": int(prev.binding_id),
            "capital_substitution_estimated": False,
        },
    )
    session.add(row)
    session.flush()
    return {
        "ok": True,
        "observed": True,
        "shadow_id": int(row.shadow_id),
        "gap_seconds": gap,
        "variants": variants,
    }


def finalize_reentry_outcome(
    session: Session,
    *,
    entry_order_id: int | None,
    user_broker_account_id: int | None = None,
) -> dict[str, Any]:
    """재진입 trade baseline net → cooldown avoided impact."""

    if entry_order_id is None:
        return {"ok": False, "reason": "NO_ENTRY_ORDER"}
    row = session.scalar(
        select(UpbitPostExitReentryCooldownShadowEntity).where(
            UpbitPostExitReentryCooldownShadowEntity.new_entry_order_id
            == int(entry_order_id)
        )
    )
    if row is None:
        return {"ok": False, "reason": "NOT_FOUND"}
    if row.status == STATUS_COMPLETED and row.baseline_reentry_net is not None:
        return {"ok": True, "duplicate": True}

    resolved = resolve_baseline_outcome_for_entry(
        session,
        entry_order_id=int(entry_order_id),
        user_broker_account_id=user_broker_account_id
        or int(row.user_broker_account_id),
    )
    if not resolved or not resolved.get("ok"):
        return {"ok": False, "reason": "BASELINE_UNRESOLVED", "detail": resolved}

    net = float(resolved["net_pnl"])
    row.baseline_reentry_net = Decimal(str(round(net, 4)))
    variants = dict(row.variants_json or {})
    for code, v in list(variants.items()):
        vv = dict(v or {})
        # cooldown이면 trade 없음 → impact = -baseline_net
        if vv.get("WOULD_BLOCK"):
            vv["avoided_net_impact"] = round(-net, 4)
        else:
            vv["avoided_net_impact"] = 0.0
        variants[code] = vv
    row.variants_json = variants
    row.status = STATUS_COMPLETED
    session.flush()
    return {"ok": True, "baseline_reentry_net": net, "shadow_id": int(row.shadow_id)}


def summarize_reentry_cooldown(
    session: Session,
    *,
    user_broker_account_id: int | None = None,
) -> dict[str, Any]:
    q = select(UpbitPostExitReentryCooldownShadowEntity)
    if user_broker_account_id is not None:
        q = q.where(
            UpbitPostExitReentryCooldownShadowEntity.user_broker_account_id
            == int(user_broker_account_id)
        )
    rows = list(session.scalars(q))
    completed = [r for r in rows if r.status == STATUS_COMPLETED]

    def _agg(code: str) -> dict[str, Any]:
        blocked = []
        impacts = []
        for r in completed:
            v = (r.variants_json or {}).get(code) or {}
            if v.get("WOULD_BLOCK"):
                blocked.append(r)
                if v.get("avoided_net_impact") is not None:
                    impacts.append(float(v["avoided_net_impact"]))
        return {
            "variant": code,
            "cooldown_seconds": VARIANT_SECONDS[code],
            "N": len(completed),
            "would_block_n": len(blocked),
            "avoided_net_impact": round(sum(impacts), 4) if impacts else 0.0,
        }

    return {
        "ok": True,
        "family": FAMILY,
        "TOTAL": len(rows),
        "COMPLETED": len(completed),
        "OBSERVED": len([r for r in rows if r.status == STATUS_OBSERVED]),
        "R0": _agg(VARIANT_R0),
        "R1": _agg(VARIANT_R1),
        "R2": _agg(VARIANT_R2),
        "R3": _agg(VARIANT_R3),
        "REAL_ENTRY_BLOCKED": False,
        "NOTE": "Direct avoided re-entry outcome only; no capital substitution.",
    }


def evaluate_would_block_matrix(gap_seconds: float) -> dict[str, bool]:
    """순수 함수 — 테스트용."""

    return {
        code: _would_block(gap_seconds, secs)
        for code, secs in VARIANT_SECONDS.items()
    }
