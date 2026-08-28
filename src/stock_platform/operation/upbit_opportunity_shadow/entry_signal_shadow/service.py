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
        # Data Trust: INVALID open window → quarantine (raw 유지)
        try:
            from stock_platform.trading.autotrading_data_trust import (
                resolve_open_window_attribution,
            )

            attr = resolve_open_window_attribution(
                session, market="UPBIT", uba_id=int(uba_id)
            )
            row.data_quality_status = attr["data_quality_status"]
            row.included_in_research_metrics = attr["included_in_research_metrics"]
            row.quarantine_reason = attr["quarantine_reason"]
            row.quality_window_id = attr["quality_window_id"]
        except Exception:
            pass
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


def _apply_future_columns(row: UpbitEntrySignalShadowEntity, fut: dict[str, Any]) -> None:
    """Fill return columns from _future_prices result (partial horizon OK)."""

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
    """Fill forward returns per horizon — as-of maturation, look-ahead 금지.

    PASS/BLOCK 모두 성숙시킨다 — counterfactual outcome 필요.
    REAL order/slot/daily 경로는 절대 건드리지 않는다.
    """

    now = _utc_now()
    min_window = min(OUTCOME_WINDOWS_MIN)
    cutoff = now - timedelta(minutes=min_window)
    from sqlalchemy import or_

    q = select(UpbitEntrySignalShadowEntity).where(
        UpbitEntrySignalShadowEntity.observed_at <= cutoff,
        or_(
            UpbitEntrySignalShadowEntity.outcome_status == STATUS_PENDING,
            (
                (UpbitEntrySignalShadowEntity.outcome_status == STATUS_COMPLETED)
                & (
                    UpbitEntrySignalShadowEntity.future_240m_return_pct.is_(None)
                    | UpbitEntrySignalShadowEntity.future_1440m_return_pct.is_(None)
                )
            ),
        ),
    )
    if uba_id is not None:
        q = q.where(
            UpbitEntrySignalShadowEntity.user_broker_account_id == int(uba_id)
        )
    rows = list(session.scalars(q.limit(limit)))
    matured = 0
    insufficient = 0
    partial = 0
    for row in rows:
        fut = _future_prices(
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
        row.fee_rt_pct = Decimal(str(FEE_RT_PCT))
        prev_json = dict(row.outcome_json or {})
        prev_json.update(
            {
                "fee_assumption": fut.get("fee_assumption"),
                "slippage_assumption": fut.get("slippage_assumption"),
                "horizons": fut.get("horizons") or {},
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
        elif row.outcome_status == STATUS_PENDING:
            partial += 1
        else:
            # COMPLETED row — extended horizon backfill only
            partial += 1
    if commit:
        session.commit()
    return {
        "ok": True,
        "matured": matured,
        "partial": partial,
        "insufficient": insufficient,
    }


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
    # observations = distinct selection_id for E0 (natural opportunity only)
    obs = session.scalar(
        text(
            """
            SELECT COUNT(DISTINCT selection_id)
            FROM operation.upbit_entry_signal_shadow
            WHERE user_broker_account_id = :uba AND source = :src
              AND variant = 'E0'
              AND selection_id IS NOT NULL
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
