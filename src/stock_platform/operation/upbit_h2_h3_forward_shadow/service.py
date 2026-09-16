"""H2/H3 forward-shadow service — research only, never publishes StrategySignal."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Sequence

import structlog
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from stock_platform.operation.upbit_h2_h3_forward_shadow.entities import (
    UpbitH2H3ForwardShadowEntity,
)
from stock_platform.operation.upbit_h2_h3_forward_shadow.features import features_at
from stock_platform.operation.upbit_h2_h3_forward_shadow.frozen_rules import (
    FEE_RATE,
    FORWARD_VALIDATION_STARTED_AT,
    H2_NAME,
    H2_RULE_HASH,
    H3_NAME,
    H3_RULE_HASH,
    OUTCOME_HORIZONS_MIN,
    PRIMARY_HORIZON_MIN,
    RULE_VERSION,
    SAMPLE_EVERY_MIN,
    SLIP_BPS_BASELINE,
    matches_frozen,
    rule_hash,
)
from stock_platform.operation.upbit_h2_h3_forward_shadow.metrics import (
    net_pnl_krw,
    net_return_pct,
    profit_factor,
    summarize_nets,
)

logger = structlog.get_logger(__name__)

STATUS_PENDING = "PENDING"
STATUS_PARTIAL = "PARTIAL"
STATUS_COMPLETE = "COMPLETE"

# Explicit isolation — never import trading signal publisher from this module path
_ASSERT_NO_SIGNAL_PUBLISH = True


def floor_sample(ts: datetime) -> datetime:
    ts = ts.astimezone(timezone.utc).replace(second=0, microsecond=0)
    m = ts.minute - (ts.minute % SAMPLE_EVERY_MIN)
    return ts.replace(minute=m)


def _cost_bundle(gross_pct: float) -> dict[str, float]:
    net_pct_2 = net_return_pct(gross_pct, fee_rate=FEE_RATE, slip_bps=SLIP_BPS_BASELINE)
    out = {
        "gross_return_pct": float(gross_pct),
        "fee_rt_pct": float(FEE_RATE * 2 * 100),
        "slip_bps": SLIP_BPS_BASELINE,
        "net_return_pct": float(net_pct_2),
        "net_pnl_krw": float(net_pnl_krw(net_pct_2)),
    }
    for bps in (1.0, 5.0):
        np = net_return_pct(gross_pct, fee_rate=FEE_RATE, slip_bps=bps)
        out[f"net_pnl_krw_{bps:g}bps"] = float(net_pnl_krw(np))
        out[f"net_return_pct_{bps:g}bps"] = float(np)
    return out


def insert_opportunity(
    session: Session,
    *,
    strategy: str,
    symbol: str,
    evaluated_at: datetime,
    entry_price: float,
    feature_snapshot: dict[str, Any],
) -> bool:
    """Insert shadow opportunity. Returns True if new row. Never creates orders."""

    assert _ASSERT_NO_SIGNAL_PUBLISH
    eva = floor_sample(evaluated_at)
    if eva < FORWARD_VALIDATION_STARTED_AT:
        return False
    rh = rule_hash(strategy)
    sym = symbol.upper()
    # 세션 미flush 중복 방지 — DB unique와 함께 idempotent
    exists = session.scalar(
        select(UpbitH2H3ForwardShadowEntity.shadow_id).where(
            UpbitH2H3ForwardShadowEntity.strategy == strategy,
            UpbitH2H3ForwardShadowEntity.symbol == sym,
            UpbitH2H3ForwardShadowEntity.evaluated_at == eva,
            UpbitH2H3ForwardShadowEntity.rule_hash == rh,
        )
    )
    if exists is not None:
        return False
    stmt = (
        pg_insert(UpbitH2H3ForwardShadowEntity)
        .values(
            strategy=strategy,
            rule_hash=rh,
            rule_version=RULE_VERSION,
            symbol=sym,
            evaluated_at=eva,
            entry_reference_price=Decimal(str(entry_price)),
            feature_snapshot=feature_snapshot,
            research_only=True,
            outcome_status=STATUS_PENDING,
            outcome_json={},
        )
        .on_conflict_do_nothing(
            constraint="uq_h2h3_fs_strat_sym_at_hash"
        )
    )
    res = session.execute(stmt)
    session.flush()
    return bool(res.rowcount)


def evaluate_symbol_bars(
    session: Session,
    *,
    symbol: str,
    candle_ats: Sequence[datetime],
    closes: Sequence[float],
    highs: Sequence[float],
    lows: Sequence[float],
) -> dict[str, int]:
    """Scan bars after STARTED_AT on SAMPLE_EVERY grid; insert H2/H3 hits."""

    created = {"H2": 0, "H3": 0}
    by_min = {
        a.astimezone(timezone.utc).replace(second=0, microsecond=0): i
        for i, a in enumerate(candle_ats)
    }
    if not by_min:
        return created
    start = max(min(by_min), FORWARD_VALIDATION_STARTED_AT)
    end = max(by_min)
    t = floor_sample(start)
    if t < start:
        t += timedelta(minutes=SAMPLE_EVERY_MIN)
    while t <= end:
        idx = by_min.get(t)
        if idx is not None:
            feat = features_at(closes=closes, lows=lows, idx=idx)
            if feat is not None:
                for strat in (H2_NAME, H3_NAME):
                    if matches_frozen(strat, feat):
                        ok = insert_opportunity(
                            session,
                            strategy=strat,
                            symbol=symbol,
                            evaluated_at=t,
                            entry_price=float(feat["close"]),
                            feature_snapshot={
                                k: feat[k]
                                for k in (
                                    "dist_ma20_pct",
                                    "ret_1m",
                                    "dist_low_20_pct",
                                    "close",
                                )
                            },
                        )
                        if ok:
                            created[strat] += 1
        t += timedelta(minutes=SAMPLE_EVERY_MIN)
    return created


def compute_horizon_outcome(
    *,
    entry_price: float,
    path: Sequence[dict[str, Any]],
    mature_at: datetime,
) -> dict[str, Any]:
    """Build one horizon outcome from post-entry candle path (no future leak)."""

    if not path or entry_price <= 0:
        return {"status": "MISSING_DATA"}
    last = path[-1]
    close = float(last["close_price"])
    gross = (close / entry_price - 1.0) * 100.0
    highs = [float(p["high_price"]) for p in path]
    lows = [float(p["low_price"]) for p in path]
    bundle = _cost_bundle(gross)
    bundle.update(
        {
            "status": "READY",
            "mfe_pct": (max(highs) / entry_price - 1.0) * 100.0,
            "mae_pct": (min(lows) / entry_price - 1.0) * 100.0,
            "as_of": mature_at.isoformat(),
        }
    )
    return bundle


def apply_maturity_to_outcomes(
    *,
    evaluated_at: datetime,
    entry_price: float,
    outcomes: dict[str, Any],
    now: datetime,
    path_loader,
) -> tuple[dict[str, Any], str]:
    """Fill ready horizons only. path_loader(h_min, mature_at) -> candle rows.

    Returns (outcomes, status). PENDING until first horizon ready.
    """

    outcomes = dict(outcomes or {})
    done = 0
    for h in OUTCOME_HORIZONS_MIN:
        key = f"{h}m"
        mature_at = evaluated_at + timedelta(minutes=h)
        if now < mature_at:
            continue
        if key in outcomes and outcomes[key].get("status") == "READY":
            done += 1
            continue
        path = path_loader(h, mature_at)
        outcomes[key] = compute_horizon_outcome(
            entry_price=entry_price, path=path, mature_at=mature_at
        )
        if outcomes[key].get("status") == "READY":
            done += 1
    if done >= len(OUTCOME_HORIZONS_MIN):
        return outcomes, STATUS_COMPLETE
    if done > 0:
        return outcomes, STATUS_PARTIAL
    return outcomes, STATUS_PENDING


def mature_pending(
    session: Session,
    *,
    now: datetime | None = None,
    limit: int = 500,
    commit: bool = True,
) -> dict[str, Any]:
    """Fill outcomes only after horizons have elapsed. No lookahead. Restart-safe."""

    now = now or datetime.now(timezone.utc)
    rows = list(
        session.scalars(
            select(UpbitH2H3ForwardShadowEntity)
            .where(
                UpbitH2H3ForwardShadowEntity.outcome_status.in_(
                    [STATUS_PENDING, STATUS_PARTIAL]
                )
            )
            .order_by(UpbitH2H3ForwardShadowEntity.evaluated_at.asc())
            .limit(limit)
        )
    )
    matured = partial = 0
    for row in rows:
        entry = float(row.entry_reference_price)

        def _loader(h: int, mature_at: datetime, _row=row) -> list[dict[str, Any]]:
            return list(
                session.execute(
                    text(
                        """
                        SELECT c.candle_at, c.close_price, c.high_price, c.low_price
                        FROM market.candle_minute c
                        JOIN market.instrument i ON i.instrument_id = c.instrument_id
                        WHERE i.exchange_code='UPBIT' AND i.symbol=:sym
                          AND c.timeframe=1
                          AND c.candle_at > :t0 AND c.candle_at <= :t1
                        ORDER BY c.candle_at
                        """
                    ),
                    {
                        "sym": _row.symbol,
                        "t0": _row.evaluated_at,
                        "t1": mature_at,
                    },
                ).mappings()
            )

        outcomes, status = apply_maturity_to_outcomes(
            evaluated_at=row.evaluated_at,
            entry_price=entry,
            outcomes=dict(row.outcome_json or {}),
            now=now,
            path_loader=_loader,
        )
        row.outcome_json = outcomes
        row.outcome_status = status
        row.updated_at = now
        if status == STATUS_COMPLETE:
            row.completed_at = now
            matured += 1
        elif status == STATUS_PARTIAL:
            partial += 1
    if commit:
        session.commit()
    return {"matured": matured, "partial": partial, "scanned": len(rows)}


def compute_readiness(
    rows: Sequence[Any],
    *,
    strategy: str,
) -> dict[str, Any]:
    """Pure readiness from row-like objects (FORWARD only — caller filters)."""

    primary = f"{PRIMARY_HORIZON_MIN}m"
    complete = [
        r
        for r in rows
        if getattr(r, "outcome_status", None) == STATUS_COMPLETE
        and (getattr(r, "outcome_json", None) or {})
        .get(primary, {})
        .get("status")
        == "READY"
    ]
    pending = sum(
        1
        for r in rows
        if getattr(r, "outcome_status", None) != STATUS_COMPLETE
    )
    nets = [
        float((getattr(r, "outcome_json", None) or {})[primary]["net_pnl_krw"])
        for r in complete
    ]
    day_set = {
        getattr(r, "evaluated_at").date()
        for r in complete
        if getattr(r, "evaluated_at", None) is not None
    }
    summary = summarize_nets(nets, days=max(1.0, float(len(day_set) or 1)))
    n = len(complete)
    pf = float(summary.get("pf") or 0)
    net = float(summary.get("total_net") or 0)
    nets5 = [
        float(
            (getattr(r, "outcome_json", None) or {})[primary].get(
                "net_pnl_krw_5bps"
            )
            or 0
        )
        for r in complete
    ]
    pf5 = profit_factor(nets5) if nets5 else 0.0
    conc_top2 = 0.0
    if nets:
        wins = sorted([x for x in nets if x > 0], reverse=True)
        tot = sum(wins)
        if tot > 0:
            conc_top2 = sum(wins[:2]) / tot
    by_sym: dict[str, float] = {}
    for r in complete:
        nval = float(
            (getattr(r, "outcome_json", None) or {})[primary]["net_pnl_krw"]
        )
        if nval > 0:
            sym = str(getattr(r, "symbol", "?"))
            by_sym[sym] = by_sym.get(sym, 0.0) + nval
    sym_share = 0.0
    tw = sum(by_sym.values())
    if tw > 0 and by_sym:
        sym_share = max(by_sym.values()) / tw

    if n < 300:
        status = "NOT_ENOUGH_FORWARD_DATA"
    elif (
        net > 0
        and pf >= 1.10
        and pf5 >= 0.85
        and conc_top2 < 0.55
        and sym_share < 0.5
    ):
        status = "READY_FOR_USER_REVIEW"
    elif net > 0 and pf >= 1.0:
        status = "PROMISING"
    else:
        status = "FAIL"

    hz: dict[str, Any] = {}
    for h in OUTCOME_HORIZONS_MIN:
        key = f"{h}m"
        xs = [
            float(
                (getattr(r, "outcome_json", None) or {})
                .get(key, {})
                .get("net_pnl_krw")
                or 0
            )
            for r in complete
            if (getattr(r, "outcome_json", None) or {})
            .get(key, {})
            .get("status")
            == "READY"
        ]
        hz[key] = summarize_nets(xs, days=1) if xs else {"n": 0}

    return {
        "strategy": strategy,
        "rule_hash": H2_RULE_HASH if strategy == H2_NAME else H3_RULE_HASH,
        "total": len(rows),
        "pending": pending,
        "complete": n,
        "primary_horizon": PRIMARY_HORIZON_MIN,
        "summary_primary": summary,
        "horizons": hz,
        "readiness": status,
        "user_approval_required": True,
        "profit_concentration_top2": round(conc_top2, 3),
        "top_symbol_profit_share": round(sym_share, 3),
        "slip5_pf": round(float(pf5), 3),
        "mdd": summary.get("mdd"),
        "source": "FORWARD_SHADOW",
    }


def readiness_for(session: Session, *, strategy: str) -> dict[str, Any]:
    """Compute readiness from FORWARD samples only (not historical WRK-018)."""

    rows = list(
        session.scalars(
            select(UpbitH2H3ForwardShadowEntity).where(
                UpbitH2H3ForwardShadowEntity.strategy == strategy,
                UpbitH2H3ForwardShadowEntity.evaluated_at
                >= FORWARD_VALIDATION_STARTED_AT,
            )
        )
    )
    return compute_readiness(rows, strategy=strategy)


def run_evaluate_tick(session: Session, *, symbols: list[str] | None = None) -> dict[str, Any]:
    """Load recent candles (read-only) and evaluate H2/H3. No signal publish."""

    assert _ASSERT_NO_SIGNAL_PUBLISH
    if symbols is None:
        symbols = [
            str(s)
            for s in session.execute(
                text(
                    """
                    SELECT i.symbol FROM market.instrument i
                    WHERE i.exchange_code='UPBIT' AND i.symbol LIKE 'KRW-%'
                      AND i.symbol <> 'KRW-USDT'
                    ORDER BY i.symbol
                    LIMIT 40
                    """
                )
            ).scalars()
        ]
    lookback_start = FORWARD_VALIDATION_STARTED_AT - timedelta(hours=2)
    created = {"H2": 0, "H3": 0}
    for sym in symbols:
        rows = session.execute(
            text(
                """
                SELECT c.candle_at, c.close_price, c.high_price, c.low_price
                FROM market.candle_minute c
                JOIN market.instrument i ON i.instrument_id = c.instrument_id
                WHERE i.exchange_code='UPBIT' AND i.symbol=:sym AND c.timeframe=1
                  AND c.candle_at >= :start
                ORDER BY c.candle_at
                """
            ),
            {"sym": sym, "start": lookback_start},
        ).mappings().all()
        if len(rows) < 30:
            continue
        ats = [r["candle_at"] for r in rows]
        closes = [float(r["close_price"]) for r in rows]
        highs = [float(r["high_price"]) for r in rows]
        lows = [float(r["low_price"]) for r in rows]
        c = evaluate_symbol_bars(
            session,
            symbol=sym,
            candle_ats=ats,
            closes=closes,
            highs=highs,
            lows=lows,
        )
        created["H2"] += c["H2"]
        created["H3"] += c["H3"]
    session.commit()
    matured = mature_pending(session, limit=500)
    logger.info(
        "h2_h3_forward_shadow_tick",
        created=created,
        matured=matured,
        research_only=True,
        strategy_signal_published=0,
    )
    return {
        "created": created,
        "matured": matured,
        "strategy_signal_published": 0,
        "executor_calls": 0,
        "real_orders": 0,
    }
