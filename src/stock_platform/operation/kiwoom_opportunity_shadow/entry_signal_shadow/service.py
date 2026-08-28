"""KIWOOM Golden Cross forward shadow — enroll + outcome (REAL mutation 0)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select, text

from sqlalchemy.orm import Session

from stock_platform.operation.kiwoom_opportunity_shadow.entry_signal_shadow.constants import (
    ENTRY_EVENT_GOLDEN_CROSS,
    SOURCE_FORWARD,
    STATUS_COMPLETED,
    STATUS_INSUFFICIENT_OUTCOME,
    STATUS_PENDING,
    VARIANT_K0,
)
from stock_platform.operation.kiwoom_opportunity_shadow.entry_signal_shadow.entities import (
    KiwoomEntrySignalShadowEntity,
)
from stock_platform.operation.kiwoom_opportunity_shadow.entry_signal_shadow.replay import (
    future_prices_kiwoom,
)

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def build_research_opportunity_id(
    *,
    symbol: str,
    event_time: datetime,
) -> str:
    """BELOW→GOLDEN_CROSS episode — tick 반복 dedupe 키."""

    ts = _utc_now()
    et = event_time
    if et.tzinfo is None:
        et = et.replace(tzinfo=timezone.utc)
    else:
        et = et.astimezone(timezone.utc)
    return f"gc:{symbol.upper()}:{int(et.timestamp())}"


def enroll_golden_cross_observation(
    session: Session,
    *,
    uba_id: int,
    symbol: str,
    short_ma: Decimal,
    long_ma: Decimal,
    prev_short: Decimal,
    prev_long: Decimal,
    observed_at: datetime | None = None,
    entry_reference_price: Decimal | None = None,
    scope_key: str | None = None,
    commit: bool = False,
) -> dict[str, Any]:
    """K0 — REAL Golden Cross rule mirror. 주문/executor 미호출."""

    observed_at = observed_at or _utc_now()
    opp_id = build_research_opportunity_id(symbol=symbol, event_time=observed_at)

    exists = session.scalar(
        select(KiwoomEntrySignalShadowEntity.shadow_id).where(
            KiwoomEntrySignalShadowEntity.user_broker_account_id == int(uba_id),
            KiwoomEntrySignalShadowEntity.research_opportunity_id == opp_id,
            KiwoomEntrySignalShadowEntity.variant == VARIANT_K0,
            KiwoomEntrySignalShadowEntity.source == SOURCE_FORWARD,
        )
    )
    if exists is not None:
        return {
            "ok": True,
            "created": 0,
            "skipped_duplicate": 1,
            "research_opportunity_id": opp_id,
            "real_order_mutation": 0,
        }

    row = KiwoomEntrySignalShadowEntity(
        user_broker_account_id=int(uba_id),
        symbol=str(symbol).upper(),
        observed_at=observed_at,
        research_opportunity_id=opp_id,
        variant=VARIANT_K0,
        source=SOURCE_FORWARD,
        entry_event=ENTRY_EVENT_GOLDEN_CROSS,
        shadow_decision="PASS",
        shadow_block_reason=None,
        indicator_snapshot={
            "short_ma": str(short_ma),
            "long_ma": str(long_ma),
            "prev_short_ma": str(prev_short),
            "prev_long_ma": str(prev_long),
            "crossover": "BELOW_TO_ABOVE",
            "scope_key": scope_key,
        },
        entry_reference_price=entry_reference_price,
        outcome_status=STATUS_PENDING,
    )
    try:
        from stock_platform.trading.autotrading_data_trust import (
            resolve_open_window_attribution,
        )

        attr = resolve_open_window_attribution(
            session, market="KIWOOM", uba_id=int(uba_id)
        )
        row.data_quality_status = attr["data_quality_status"]
        row.included_in_research_metrics = attr["included_in_research_metrics"]
        row.quarantine_reason = attr["quarantine_reason"]
        row.quality_window_id = attr["quality_window_id"]
    except Exception:
        pass
    session.add(row)
    if commit:
        session.commit()
    return {
        "ok": True,
        "created": 1,
        "skipped_duplicate": 0,
        "research_opportunity_id": opp_id,
        "real_order_mutation": 0,
    }


def _apply_future_columns(row: KiwoomEntrySignalShadowEntity, fut: dict[str, Any]) -> None:
    futures = fut.get("futures") or {}
    mapping = {
        5: "future_5m_return_pct",
        15: "future_15m_return_pct",
        30: "future_30m_return_pct",
        60: "future_60m_return_pct",
        240: "future_240m_return_pct",
        1440: "future_1440m_return_pct",
    }
    for mins, col in mapping.items():
        key = f"future_{mins}m"
        val = futures.get(key)
        if val is not None:
            setattr(row, col, Decimal(str(val)))


def mature_pending_outcomes(
    session: Session,
    *,
    uba_id: int | None = None,
    limit: int = 200,
    commit: bool = True,
) -> dict[str, Any]:
    """Per-horizon as-of maturation — REAL path 불변."""

    now = _utc_now()
    min_window = min((5, 15, 30, 60, 240, 1440))
    cutoff = now - timedelta(minutes=min_window)
    q = select(KiwoomEntrySignalShadowEntity).where(
        KiwoomEntrySignalShadowEntity.outcome_status == STATUS_PENDING,
        KiwoomEntrySignalShadowEntity.observed_at <= cutoff,
    )
    if uba_id is not None:
        q = q.where(
            KiwoomEntrySignalShadowEntity.user_broker_account_id == int(uba_id)
        )
    rows = list(session.scalars(q.limit(limit)))
    matured = 0
    insufficient = 0
    partial = 0
    for row in rows:
        fut = future_prices_kiwoom(
            session, symbol=row.symbol, observed_at=row.observed_at, as_of=now
        )
        if not fut.get("ok"):
            row.outcome_status = STATUS_INSUFFICIENT_OUTCOME
            row.outcome_json = fut
            row.completed_at = now
            insufficient += 1
            continue
        _apply_future_columns(row, fut)
        row.entry_reference_price = fut.get("entry_reference_price")
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
        prev_json = dict(row.outcome_json or {})
        prev_json.update(
            {
                "horizons": fut.get("horizons") or {},
                "kiwoom_24h_semantics": fut.get("kiwoom_24h_semantics"),
                "as_of": fut.get("as_of"),
                "BACKFILL_SOURCE": "CANONICAL_CANDLE_MINUTE",
                "CALCULATED_AT": now.isoformat(),
            }
        )
        row.outcome_json = prev_json
        if fut.get("all_horizons_resolved"):
            row.outcome_status = STATUS_COMPLETED
            row.completed_at = now
            matured += 1
        else:
            partial += 1
    if commit:
        session.commit()
    return {
        "ok": True,
        "matured": matured,
        "partial": partial,
        "insufficient": insufficient,
    }


def forward_collection_status(session: Session, *, uba_id: int) -> dict[str, Any]:
    obs = session.scalar(
        text(
            """
            SELECT COUNT(DISTINCT research_opportunity_id)
            FROM operation.kiwoom_entry_signal_shadow
            WHERE user_broker_account_id = :uba AND source = :src
              AND variant = 'K0'
            """
        ),
        {"uba": int(uba_id), "src": SOURCE_FORWARD},
    )
    valid = session.scalar(
        text(
            """
            SELECT COUNT(DISTINCT research_opportunity_id)
            FROM operation.kiwoom_entry_signal_shadow
            WHERE user_broker_account_id = :uba AND source = :src
              AND variant = 'K0'
              AND COALESCE(included_in_research_metrics, true) = true
              AND COALESCE(data_quality_status, 'UNKNOWN') <> 'INVALID'
            """
        ),
        {"uba": int(uba_id), "src": SOURCE_FORWARD},
    )
    start = session.scalar(
        text(
            """
            SELECT MIN(created_at) FROM operation.kiwoom_entry_signal_shadow
            WHERE user_broker_account_id = :uba AND source = :src
            """
        ),
        {"uba": int(uba_id), "src": SOURCE_FORWARD},
    )
    return {
        "FORWARD_COLLECTION_ENABLED": True,
        "FORWARD_START_AT": start.isoformat() if start else None,
        "FORWARD_SAMPLE_COUNT": int(obs or 0),
        "VALID_SAMPLE_COUNT": int(valid or 0),
        "REAL_POLICY_UNCHANGED": True,
    }
