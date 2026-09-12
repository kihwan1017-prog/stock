"""Entry Gate V2 shadow persist — own session, REAL mutation 0."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.operation.upbit_opportunity_shadow.entry_gate_v2.constants import (
    ALL_V2_VARIANTS,
    LIVE_PROMOTION_ELIGIBLE,
    OUTCOME_WINDOWS_MIN,
    RULE_VERSION,
    SOURCE_FORWARD,
    STATUS_COMPLETED,
    STATUS_INSUFFICIENT,
    STATUS_PENDING,
)
from stock_platform.operation.upbit_opportunity_shadow.entry_gate_v2.entities import (
    UpbitEntryGateV2ShadowEntity,
)
from stock_platform.operation.upbit_opportunity_shadow.entry_gate_v2.features import (
    V2Features,
    build_features_from_closes,
)
from stock_platform.operation.upbit_opportunity_shadow.entry_gate_v2.variants import (
    evaluate_all_v2,
)

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def observed_bucket(ts: datetime) -> str:
    t = ts.astimezone(timezone.utc)
    minute = (t.minute // 5) * 5
    return t.strftime("%Y%m%d%H") + f"{minute:02d}"


def enroll_v2_shadow(
    session: Session,
    *,
    uba_id: int,
    symbol: str,
    live_e0_decision: str,
    live_e0_block_reason: str | None,
    short_ma: Decimal | float,
    long_ma: Decimal | float,
    closes: Sequence[float],
    highs: Sequence[float] | None = None,
    lows: Sequence[float] | None = None,
    selection_id: int | None = None,
    strategy_id: int | None = None,
    scanner_run_id: str | None = None,
    rsi14: float | None = None,
    volume_surge: float | None = None,
    cand_score: float | None = None,
    cand_rank: float | None = None,
    entry_reference_price: Decimal | float | None = None,
    observed_at: datetime | None = None,
    commit: bool = False,
) -> dict[str, Any]:
    """Write V2_A/C/D rows. Never creates intents/orders/slots."""

    observed_at = observed_at or _utc_now()
    bucket = observed_bucket(observed_at)
    feat = build_features_from_closes(
        closes=closes,
        highs=highs,
        lows=lows,
        short_ma=short_ma,
        long_ma=long_ma,
        rsi14=rsi14,
        volume_surge=volume_surge,
        cand_score=cand_score,
        cand_rank=cand_rank,
    )
    decisions = evaluate_all_v2(feat)
    created = 0
    skipped = 0
    for code in ALL_V2_VARIANTS:
        exists = session.scalar(
            select(UpbitEntryGateV2ShadowEntity.id).where(
                UpbitEntryGateV2ShadowEntity.user_broker_account_id == int(uba_id),
                UpbitEntryGateV2ShadowEntity.symbol == str(symbol).upper(),
                UpbitEntryGateV2ShadowEntity.observed_bucket == bucket,
                UpbitEntryGateV2ShadowEntity.v2_candidate == code,
            )
        )
        if exists is not None:
            skipped += 1
            continue
        d = decisions[code]
        row = UpbitEntryGateV2ShadowEntity(
            observed_at=observed_at,
            observed_bucket=bucket,
            user_broker_account_id=int(uba_id),
            strategy_id=int(strategy_id) if strategy_id else None,
            symbol=str(symbol).upper(),
            scanner_run_id=scanner_run_id,
            selection_id=int(selection_id) if selection_id else None,
            live_e0_decision=str(live_e0_decision).upper(),
            live_e0_block_reason=live_e0_block_reason,
            v2_version=RULE_VERSION,
            v2_candidate=code,
            v2_decision="ALLOW" if d["allow"] else "HOLD",
            v2_score=Decimal(str(round(float(d["score"]), 6))),
            v2_block_reason=d.get("block_reason"),
            feature_snapshot={
                **feat.as_dict(),
                "source": SOURCE_FORWARD,
                "hard_block": d.get("hard_block"),
            },
            regime=feat.regime,
            research_only=True,
            live_promotion_eligible=LIVE_PROMOTION_ELIGIBLE,
            counterfactual_status=STATUS_PENDING,
            entry_reference_price=(
                Decimal(str(entry_reference_price))
                if entry_reference_price is not None
                else None
            ),
        )
        session.add(row)
        created += 1
    if commit:
        session.commit()
    return {
        "ok": True,
        "created": created,
        "skipped_duplicate": skipped,
        "order_intent_mutation": 0,
        "broker_mutation": 0,
        "position_mutation": 0,
        "live_e0_mutation": 0,
        "features": feat.as_dict(),
        "decisions": decisions,
    }


def mature_pending_v2_outcomes(
    session: Session,
    *,
    uba_id: int | None = None,
    limit: int = 200,
    commit: bool = True,
) -> dict[str, Any]:
    """Fill forward returns — as-of only (no lookahead into features)."""

    now = _utc_now()
    cutoff = now - timedelta(minutes=min(OUTCOME_WINDOWS_MIN))
    q = select(UpbitEntryGateV2ShadowEntity).where(
        UpbitEntryGateV2ShadowEntity.counterfactual_status == STATUS_PENDING,
        UpbitEntryGateV2ShadowEntity.observed_at <= cutoff,
    )
    if uba_id is not None:
        q = q.where(
            UpbitEntryGateV2ShadowEntity.user_broker_account_id == int(uba_id)
        )
    q = q.order_by(UpbitEntryGateV2ShadowEntity.observed_at.asc()).limit(limit)
    rows = list(session.scalars(q))
    matured = 0
    insufficient = 0
    for row in rows:
        try:
            from stock_platform.operation.upbit_opportunity_shadow.entry_signal_shadow.replay import (
                _future_prices,
            )

            fut = _future_prices(
                session,
                symbol=row.symbol,
                observed_at=row.observed_at,
            )
        except Exception as exc:  # noqa: BLE001
            row.outcome_json = {"error": type(exc).__name__}
            row.counterfactual_status = STATUS_INSUFFICIENT
            insufficient += 1
            continue
        futures = fut.get("futures") or {}
        mapping = {
            5: "future_5m_return_pct",
            15: "future_15m_return_pct",
            30: "future_30m_return_pct",
            60: "future_60m_return_pct",
        }
        any_filled = False
        for mins, col in mapping.items():
            val = futures.get(f"future_{mins}m")
            if val is not None:
                setattr(row, col, Decimal(str(val)))
                any_filled = True
        row.outcome_json = {"futures_meta": fut.get("meta") or {}}
        if any_filled:
            row.counterfactual_status = STATUS_COMPLETED
            row.completed_at = now
            matured += 1
        else:
            row.counterfactual_status = STATUS_INSUFFICIENT
            insufficient += 1
    if commit:
        session.commit()
    return {
        "ok": True,
        "scanned": len(rows),
        "matured": matured,
        "insufficient": insufficient,
        "broker_mutation": 0,
    }
