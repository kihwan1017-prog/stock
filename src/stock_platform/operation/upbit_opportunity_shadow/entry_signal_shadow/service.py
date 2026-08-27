"""Forward entry signal shadow — enroll + outcome (REAL mutation 0)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from stock_platform.operation.upbit_full_market.portfolio_entry_signal import (
    SymbolEntrySnapshot,
)
from stock_platform.operation.upbit_opportunity_shadow.entry_signal_shadow.constants import (
    ALL_VARIANTS,
    FEE_RT_PCT,
    FORWARD_SAMPLE_TARGET,
    OUTCOME_WINDOWS_MIN,
    RULE_VERSION,
    SOURCE_FORWARD,
    STATUS_COMPLETED,
    STATUS_INSUFFICIENT_OUTCOME,
    STATUS_PENDING,
    VARIANT_E0,
)
from stock_platform.operation.upbit_opportunity_shadow.entry_signal_shadow.entities import (
    UpbitEntrySignalShadowEntity,
)
from stock_platform.operation.upbit_opportunity_shadow.entry_signal_shadow.replay import (
    _future_prices,
)
from stock_platform.operation.upbit_opportunity_shadow.entry_signal_shadow.variants import (
    evaluate_all_variants,
)

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def enroll_forward_observation(
    session: Session,
    *,
    uba_id: int,
    symbol: str,
    selection_id: int | None,
    short_ma: Decimal,
    long_ma: Decimal,
    snap: SymbolEntrySnapshot | None,
    emit_suppressed: bool = False,
    observed_at: datetime | None = None,
    entry_reference_price: Decimal | None = None,
    commit: bool = False,
) -> dict[str, Any]:
    """Record E0–E4 shadow rows. Never touches slots/orders/daily count."""

    observed_at = observed_at or _utc_now()
    decisions = evaluate_all_variants(
        short_ma=short_ma,
        long_ma=long_ma,
        snap=snap,
        emit_suppressed=emit_suppressed,
        event_time=observed_at,
    )
    e0 = decisions[VARIANT_E0]
    created = 0
    skipped = 0
    for code in ALL_VARIANTS:
        d = decisions[code]
        if selection_id is not None:
            exists = session.scalar(
                select(UpbitEntrySignalShadowEntity.shadow_id).where(
                    UpbitEntrySignalShadowEntity.user_broker_account_id
                    == int(uba_id),
                    UpbitEntrySignalShadowEntity.selection_id
                    == int(selection_id),
                    UpbitEntrySignalShadowEntity.variant == code,
                    UpbitEntrySignalShadowEntity.source == SOURCE_FORWARD,
                )
            )
            if exists is not None:
                skipped += 1
                continue
        row = UpbitEntrySignalShadowEntity(
            user_broker_account_id=int(uba_id),
            symbol=str(symbol).upper(),
            observed_at=observed_at,
            selection_id=int(selection_id) if selection_id else None,
            variant=code,
            source=SOURCE_FORWARD,
            rule_version=RULE_VERSION,
            research_only=True,
            baseline_decision="PASS" if e0.get("pass") else "BLOCK",
            baseline_block_reason=e0.get("block_reason"),
            shadow_decision="PASS" if d.get("pass") else "BLOCK",
            shadow_block_reason=d.get("block_reason"),
            indicator_snapshot={
                "short_ma": str(short_ma),
                "long_ma": str(long_ma),
                "detail": d.get("detail") or {},
                "emit_suppressed": emit_suppressed,
            },
            entry_reference_price=entry_reference_price,
            fee_rt_pct=Decimal(str(FEE_RT_PCT)),
            outcome_status=STATUS_PENDING,
        )
        session.add(row)
        created += 1
    if commit:
        session.commit()
    return {
        "ok": True,
        "created": created,
        "skipped_duplicate": skipped,
        "real_order_mutation": 0,
        "slot_mutation": 0,
        "daily_count_mutation": 0,
    }


def mature_pending_outcomes(
    session: Session,
    *,
    uba_id: int | None = None,
    limit: int = 200,
    commit: bool = True,
) -> dict[str, Any]:
    """Fill future returns for PENDING rows older than 60m."""

    cutoff = _utc_now() - timedelta(minutes=max(OUTCOME_WINDOWS_MIN))
    q = select(UpbitEntrySignalShadowEntity).where(
        UpbitEntrySignalShadowEntity.outcome_status == STATUS_PENDING,
        UpbitEntrySignalShadowEntity.observed_at <= cutoff,
        UpbitEntrySignalShadowEntity.shadow_decision == "PASS",
    )
    if uba_id is not None:
        q = q.where(
            UpbitEntrySignalShadowEntity.user_broker_account_id == int(uba_id)
        )
    rows = list(session.scalars(q.limit(limit)))
    matured = 0
    insufficient = 0
    for row in rows:
        fut = _future_prices(
            session, symbol=row.symbol, observed_at=row.observed_at
        )
        if not fut.get("ok"):
            row.outcome_status = STATUS_INSUFFICIENT_OUTCOME
            row.outcome_json = fut
            row.completed_at = _utc_now()
            insufficient += 1
            continue
        futures = fut.get("futures") or {}
        row.entry_reference_price = fut.get("entry_reference_price")
        row.future_5m_return_pct = (
            Decimal(str(futures["future_5m"]))
            if futures.get("future_5m") is not None
            else None
        )
        row.future_15m_return_pct = (
            Decimal(str(futures["future_15m"]))
            if futures.get("future_15m") is not None
            else None
        )
        row.future_30m_return_pct = (
            Decimal(str(futures["future_30m"]))
            if futures.get("future_30m") is not None
            else None
        )
        row.future_60m_return_pct = (
            Decimal(str(futures["future_60m"]))
            if futures.get("future_60m") is not None
            else None
        )
        row.mfe_pct = (
            Decimal(str(fut["mfe_pct"])) if fut.get("mfe_pct") is not None else None
        )
        row.mae_pct = (
            Decimal(str(fut["mae_pct"])) if fut.get("mae_pct") is not None else None
        )
        row.net_return_15m_pct = (
            Decimal(str(fut["net_return_15m_pct"]))
            if fut.get("net_return_15m_pct") is not None
            else None
        )
        row.fee_rt_pct = Decimal(str(FEE_RT_PCT))
        row.outcome_json = {
            "fee_assumption": fut.get("fee_assumption"),
            "slippage_assumption": fut.get("slippage_assumption"),
        }
        row.outcome_status = STATUS_COMPLETED
        row.completed_at = _utc_now()
        matured += 1
    if commit:
        session.commit()
    return {"ok": True, "matured": matured, "insufficient": insufficient}


def forward_collection_status(session: Session, *, uba_id: int = 1380) -> dict[str, Any]:
    total = session.scalar(
        text(
            """
            SELECT COUNT(*) FROM operation.upbit_entry_signal_shadow
            WHERE user_broker_account_id = :uba AND source = :src
            """
        ),
        {"uba": uba_id, "src": SOURCE_FORWARD},
    )
    # observations = distinct selection_id for E0
    obs = session.scalar(
        text(
            """
            SELECT COUNT(DISTINCT COALESCE(selection_id::text, shadow_id::text))
            FROM operation.upbit_entry_signal_shadow
            WHERE user_broker_account_id = :uba AND source = :src
              AND variant = 'E0'
            """
        ),
        {"uba": uba_id, "src": SOURCE_FORWARD},
    )
    completed = session.scalar(
        text(
            """
            SELECT COUNT(*) FROM operation.upbit_entry_signal_shadow
            WHERE user_broker_account_id = :uba AND source = :src
              AND outcome_status = :st AND variant = 'E0'
            """
        ),
        {"uba": uba_id, "src": SOURCE_FORWARD, "st": STATUS_COMPLETED},
    )
    start = session.scalar(
        text(
            """
            SELECT MIN(created_at) FROM operation.upbit_entry_signal_shadow
            WHERE user_broker_account_id = :uba AND source = :src
            """
        ),
        {"uba": uba_id, "src": SOURCE_FORWARD},
    )
    return {
        "FORWARD_COLLECTION_ENABLED": True,
        "FORWARD_START_AT": start.isoformat() if start else None,
        "FORWARD_SAMPLE_COUNT": int(obs or 0),
        "COMPLETED_COUNT": int(completed or 0),
        "ROW_COUNT": int(total or 0),
        "TARGET": FORWARD_SAMPLE_TARGET,
        "REAL_POLICY_UNCHANGED": True,
    }
