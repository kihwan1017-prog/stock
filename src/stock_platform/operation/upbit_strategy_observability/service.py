# -*- coding: utf-8 -*-
"""Fail-open persistence for strategy observability (own DB session)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from stock_platform.operation.upbit_strategy_observability.constants import (
    EVENT_ADMISSION,
    EVENT_EXIT,
    EVENT_ORDER_TIMELINE,
    EVENT_REGIME,
    EVENT_SIGNAL_BUY,
    EVENT_SIGNAL_SELL,
    ORDERBOOK_POLICY,
    RULE_VERSION,
    RULE_VERSION_V1_1,
)
from stock_platform.operation.upbit_strategy_observability.entities import (
    UpbitStrategyObsEventEntity,
    UpbitStrategyObsOrderTimelineEntity,
    UpbitStrategyObsPostTradeEntity,
    UpbitStrategyObsScannerRunMetaEntity,
    UpbitStrategyObsScannerUniverseEntity,
)
from stock_platform.operation.upbit_strategy_observability.leakage import (
    assert_no_lookahead_in_trading_payload,
)
from stock_platform.operation.upbit_strategy_observability.regime import (
    classify_btc_trend,
    classify_symbol_regime,
    regime_formula_doc,
)

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _dec(v: Any) -> Decimal | None:
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v))
    except Exception:
        return None


def _own_session() -> Session:
    from stock_platform.database.session import get_session_factory

    return get_session_factory()()


def _fail(code: str, exc: BaseException | None = None) -> dict[str, Any]:
    logger.warning(
        "OBSERVABILITY_WRITE_FAILED",
        extra={"code": code, "error": type(exc).__name__ if exc else None},
    )
    return {
        "ok": False,
        "code": "OBSERVABILITY_WRITE_FAILED",
        "detail_code": code,
        "error": type(exc).__name__ if exc else None,
    }


def _extract_metrics(tm: dict[str, Any] | None, row: dict[str, Any]) -> dict[str, Any]:
    tm = dict(tm or {})
    # Only copy already-present keys — do not invent trading indicators
    keys = (
        "fast_ma",
        "slow_ma",
        "ma_short",
        "ma_long",
        "short_ma",
        "long_ma",
        "ma_spread",
        "ma_slope",
        "momentum",
        "roc",
        "rsi",
        "macd",
        "volume",
        "volume_ratio",
        "volatility",
        "atr",
        "recent_return_1m",
        "recent_return_3m",
        "recent_return_5m",
        "recent_return_10m",
        "recent_return_15m",
        "recent_return_30m",
        "recent_return_1h",
        "return_1m",
        "return_5m",
        "return_15m",
        "price",
        "trade_price",
    )
    out: dict[str, Any] = {}
    for k in keys:
        if k in tm and tm[k] is not None:
            out[k] = tm[k]
        elif k in row and row[k] is not None:
            out[k] = row[k]
    out["orderbook"] = ORDERBOOK_POLICY
    return out


def persist_scanner_universe(
    *,
    scanner_run_id: str,
    observed_at: datetime | None,
    strategy_id: int | None,
    user_broker_account_id: int | None,
    rows: list[dict[str, Any]],
    selected_symbols: set[str] | None = None,
    scanner_source: str = "UPBIT_OPPORTUNITY_SCANNER",
) -> dict[str, Any]:
    """Batch upsert ranked universe (SELECTED + NOT_SELECTED). Own session."""

    selected_symbols = {s.upper() for s in (selected_symbols or set())}
    session = _own_session()
    try:
        at = observed_at or _now()
        payload_rows: list[dict[str, Any]] = []
        for raw in rows:
            if not isinstance(raw, dict):
                continue
            sym = str(raw.get("symbol") or "").upper()
            if not sym.startswith("KRW-"):
                continue
            rejected = bool(raw.get("rejected"))
            reject_reason = raw.get("reject_reason") or raw.get("skip_reason")
            if reject_reason is None and raw.get("cooldown_suppressed"):
                rejected = True
                reject_reason = "COOLDOWN_SUPPRESSED"
            selected = sym in selected_symbols or bool(raw.get("selected"))
            tm = raw.get("technical_metrics")
            if not isinstance(tm, dict):
                tm = {}
            metrics = _extract_metrics(tm, raw)
            # Regime labels are observation-only nested under metrics
            metrics["regime_formula"] = regime_formula_doc()
            payload_rows.append(
                {
                    "scanner_run_id": str(scanner_run_id),
                    "observed_at": at,
                    "strategy_id": int(strategy_id) if strategy_id else None,
                    "user_broker_account_id": (
                        int(user_broker_account_id)
                        if user_broker_account_id
                        else None
                    ),
                    "symbol": sym,
                    "candidate_rank": (
                        int(raw["rank"]) if raw.get("rank") is not None else None
                    ),
                    "candidate_score": _dec(raw.get("score")),
                    "selected": bool(selected),
                    "rejected": bool(rejected) and not selected,
                    "reject_reason": str(reject_reason)[:120] if reject_reason else None,
                    "scanner_source": scanner_source,
                    "price": _dec(
                        raw.get("price")
                        or raw.get("trade_price")
                        or tm.get("price")
                        or tm.get("trade_price")
                    ),
                    "metrics_json": metrics,
                    "rule_version": RULE_VERSION,
                }
            )
        if not payload_rows:
            session.close()
            return {"ok": True, "inserted": 0, "note": "EMPTY_UNIVERSE"}

        stmt = pg_insert(UpbitStrategyObsScannerUniverseEntity).values(payload_rows)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_upbit_obs_scanner_run_symbol",
            set_={
                "selected": stmt.excluded.selected,
                "rejected": stmt.excluded.rejected,
                "reject_reason": stmt.excluded.reject_reason,
                "candidate_rank": stmt.excluded.candidate_rank,
                "candidate_score": stmt.excluded.candidate_score,
                "metrics_json": stmt.excluded.metrics_json,
                "price": stmt.excluded.price,
                "user_broker_account_id": stmt.excluded.user_broker_account_id,
                "strategy_id": stmt.excluded.strategy_id,
            },
        )
        session.execute(stmt)
        session.commit()

        # Run meta — expected count from this canonical full-ranked write
        try:
            _upsert_run_meta(
                scanner_run_id=str(scanner_run_id),
                observed_at=at,
                strategy_id=strategy_id,
                user_broker_account_id=user_broker_account_id,
                expected_universe_count=len(payload_rows),
                # Re-count after upsert (includes prior rows for same run)
                refresh_persisted=True,
            )
        except Exception as meta_exc:  # noqa: BLE001
            logger.warning(
                "OBSERVABILITY_WRITE_FAILED",
                extra={"code": "RUN_META", "error": type(meta_exc).__name__},
            )

        return {
            "ok": True,
            "inserted": len(payload_rows),
            "selected_count": sum(1 for r in payload_rows if r["selected"]),
            "not_selected_count": sum(1 for r in payload_rows if not r["selected"]),
            "expected_universe_count": len(payload_rows),
        }
    except Exception as exc:  # noqa: BLE001
        try:
            session.rollback()
        except Exception:  # noqa: BLE001
            pass
        return _fail("SCANNER_UNIVERSE", exc)
    finally:
        session.close()


def _count_persisted_universe(session: Session, scanner_run_id: str) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(UpbitStrategyObsScannerUniverseEntity)
            .where(
                UpbitStrategyObsScannerUniverseEntity.scanner_run_id
                == str(scanner_run_id)
            )
        )
        or 0
    )


def _upsert_run_meta(
    *,
    scanner_run_id: str,
    observed_at: datetime,
    strategy_id: int | None,
    user_broker_account_id: int | None,
    expected_universe_count: int | None = None,
    refresh_persisted: bool = True,
) -> dict[str, Any]:
    """Maintain expected vs persisted universe completeness (own session)."""

    session = _own_session()
    try:
        persisted = (
            _count_persisted_universe(session, scanner_run_id)
            if refresh_persisted
            else 0
        )
        existing = session.get(
            UpbitStrategyObsScannerRunMetaEntity, str(scanner_run_id)
        )
        if existing is None:
            expected = int(expected_universe_count or persisted)
            complete = persisted >= expected and expected > 0
            session.add(
                UpbitStrategyObsScannerRunMetaEntity(
                    scanner_run_id=str(scanner_run_id),
                    observed_at=observed_at,
                    strategy_id=int(strategy_id) if strategy_id else None,
                    user_broker_account_id=(
                        int(user_broker_account_id)
                        if user_broker_account_id
                        else None
                    ),
                    expected_universe_count=expected,
                    persisted_universe_count=persisted,
                    universe_complete=complete,
                    meta_json={"canonical_source": "SCANNER_FULL_RANKED"},
                    rule_version=RULE_VERSION_V1_1,
                    updated_at=_now(),
                )
            )
        else:
            # Never shrink expected once set from full ranked
            if expected_universe_count is not None:
                if int(existing.expected_universe_count or 0) < int(
                    expected_universe_count
                ):
                    existing.expected_universe_count = int(expected_universe_count)
            existing.persisted_universe_count = persisted
            existing.universe_complete = persisted >= int(
                existing.expected_universe_count or 0
            ) and int(existing.expected_universe_count or 0) > 0
            if strategy_id and not existing.strategy_id:
                existing.strategy_id = int(strategy_id)
            if user_broker_account_id and not existing.user_broker_account_id:
                existing.user_broker_account_id = int(user_broker_account_id)
            existing.updated_at = _now()
        session.commit()
        meta = session.get(UpbitStrategyObsScannerRunMetaEntity, str(scanner_run_id))
        return {
            "ok": True,
            "expected_universe_count": int(meta.expected_universe_count) if meta else 0,
            "persisted_universe_count": int(meta.persisted_universe_count)
            if meta
            else 0,
            "universe_complete": bool(meta.universe_complete) if meta else False,
        }
    except Exception as exc:  # noqa: BLE001
        try:
            session.rollback()
        except Exception:  # noqa: BLE001
            pass
        return _fail("RUN_META", exc)
    finally:
        session.close()


def mark_selected_symbols_only(
    *,
    scanner_run_id: str,
    selected_symbols: set[str] | list[str],
    strategy_id: int | None = None,
    user_broker_account_id: int | None = None,
) -> dict[str, Any]:
    """Update selected flags only — never delete / never shrink universe rows.

    Canonical full-ranked snapshot remains the first scanner persist.
    """

    selected = {str(s).upper() for s in (selected_symbols or set()) if s}
    if not scanner_run_id:
        return {"ok": True, "note": "NO_RUN_ID"}
    session = _own_session()
    try:
        # Clear previous selected for this run, then mark chosen (preserves all rows)
        session.execute(
            update(UpbitStrategyObsScannerUniverseEntity)
            .where(
                UpbitStrategyObsScannerUniverseEntity.scanner_run_id
                == str(scanner_run_id)
            )
            .values(selected=False)
        )
        if selected:
            values: dict[str, Any] = {"selected": True, "rejected": False}
            if strategy_id is not None:
                values["strategy_id"] = int(strategy_id)
            if user_broker_account_id is not None:
                values["user_broker_account_id"] = int(user_broker_account_id)
            session.execute(
                update(UpbitStrategyObsScannerUniverseEntity)
                .where(
                    UpbitStrategyObsScannerUniverseEntity.scanner_run_id
                    == str(scanner_run_id),
                    UpbitStrategyObsScannerUniverseEntity.symbol.in_(
                        list(selected)
                    ),
                )
                .values(**values)
            )
        # Optional: if chosen missing from universe, insert minimal selected row
        for sym in selected:
            exists = session.scalar(
                select(UpbitStrategyObsScannerUniverseEntity.id).where(
                    UpbitStrategyObsScannerUniverseEntity.scanner_run_id
                    == str(scanner_run_id),
                    UpbitStrategyObsScannerUniverseEntity.symbol == sym,
                )
            )
            if exists is None:
                session.add(
                    UpbitStrategyObsScannerUniverseEntity(
                        scanner_run_id=str(scanner_run_id),
                        observed_at=_now(),
                        strategy_id=int(strategy_id) if strategy_id else None,
                        user_broker_account_id=(
                            int(user_broker_account_id)
                            if user_broker_account_id
                            else None
                        ),
                        symbol=sym,
                        selected=True,
                        rejected=False,
                        scanner_source="UPBIT_PORTFOLIO_ASSIGN_SELECTED_ONLY",
                        metrics_json={
                            "note": "SELECTED_NOT_IN_INITIAL_UNIVERSE",
                            "observation_only": True,
                        },
                        rule_version=RULE_VERSION_V1_1,
                    )
                )
        session.commit()
        persisted = _count_persisted_universe(session, scanner_run_id)
        selected_count = int(
            session.scalar(
                select(func.count())
                .select_from(UpbitStrategyObsScannerUniverseEntity)
                .where(
                    UpbitStrategyObsScannerUniverseEntity.scanner_run_id
                    == str(scanner_run_id),
                    UpbitStrategyObsScannerUniverseEntity.selected.is_(True),
                )
            )
            or 0
        )
    except Exception as exc:  # noqa: BLE001
        try:
            session.rollback()
        except Exception:  # noqa: BLE001
            pass
        return _fail("MARK_SELECTED", exc)
    finally:
        session.close()

    meta = _upsert_run_meta(
        scanner_run_id=str(scanner_run_id),
        observed_at=_now(),
        strategy_id=strategy_id,
        user_broker_account_id=user_broker_account_id,
        expected_universe_count=None,
        refresh_persisted=True,
    )
    return {
        "ok": True,
        "scanner_run_id": str(scanner_run_id),
        "selected_count": selected_count,
        "persisted_universe_count": persisted,
        "universe_complete": meta.get("universe_complete"),
        "expected_universe_count": meta.get("expected_universe_count"),
        "non_selected_preserved": True,
    }


def universe_completeness(scanner_run_id: str) -> dict[str, Any]:
    session = _own_session()
    try:
        meta = session.get(
            UpbitStrategyObsScannerRunMetaEntity, str(scanner_run_id)
        )
        persisted = _count_persisted_universe(session, scanner_run_id)
        if meta is None:
            return {
                "scanner_run_id": str(scanner_run_id),
                "expected_universe_count": None,
                "persisted_universe_count": persisted,
                "universe_complete": False,
                "status": "SOURCE_DATA_MISSING",
            }
        return {
            "scanner_run_id": str(scanner_run_id),
            "expected_universe_count": int(meta.expected_universe_count),
            "persisted_universe_count": persisted,
            "universe_complete": bool(
                persisted >= int(meta.expected_universe_count)
                and int(meta.expected_universe_count) > 0
            ),
            "status": "AVAILABLE",
        }
    finally:
        session.close()


def persist_event(
    *,
    event_type: str,
    payload: dict[str, Any],
    observed_at: datetime | None = None,
    user_broker_account_id: int | None = None,
    strategy_id: int | None = None,
    symbol: str | None = None,
    scanner_run_id: str | None = None,
    selection_id: int | None = None,
    signal_id: str | None = None,
    order_id: int | None = None,
    binding_id: int | None = None,
) -> dict[str, Any]:
    # Guard: event payload for trading-adjacent events must not carry look-ahead
    try:
        if event_type in {EVENT_SIGNAL_BUY, EVENT_ADMISSION, EVENT_SIGNAL_SELL}:
            assert_no_lookahead_in_trading_payload(payload)
    except AssertionError as exc:
        return _fail("LOOKAHEAD_BLOCKED_IN_EVENT", exc)

    session = _own_session()
    try:
        row = UpbitStrategyObsEventEntity(
            event_type=str(event_type),
            observed_at=observed_at or _now(),
            user_broker_account_id=(
                int(user_broker_account_id) if user_broker_account_id else None
            ),
            strategy_id=int(strategy_id) if strategy_id else None,
            symbol=str(symbol).upper() if symbol else None,
            scanner_run_id=str(scanner_run_id) if scanner_run_id else None,
            selection_id=int(selection_id) if selection_id else None,
            signal_id=str(signal_id) if signal_id else None,
            order_id=int(order_id) if order_id else None,
            binding_id=int(binding_id) if binding_id else None,
            payload_json=dict(payload or {}),
            rule_version=RULE_VERSION,
        )
        session.add(row)
        session.commit()
        return {"ok": True, "event_id": int(row.id), "event_type": event_type}
    except Exception as exc:  # noqa: BLE001
        try:
            session.rollback()
        except Exception:  # noqa: BLE001
            pass
        return _fail(f"EVENT_{event_type}", exc)
    finally:
        session.close()


def _ms(a: datetime | None, b: datetime | None) -> float | None:
    if a is None or b is None:
        return None
    if a.tzinfo is None:
        a = a.replace(tzinfo=timezone.utc)
    if b.tzinfo is None:
        b = b.replace(tzinfo=timezone.utc)
    return (b - a).total_seconds() * 1000.0


def upsert_order_timeline(
    *,
    user_broker_account_id: int,
    symbol: str,
    side_code: str,
    order_id: int,
    strategy_id: int | None = None,
    binding_id: int | None = None,
    signal_id: str | None = None,
    selection_id: int | None = None,
    stamps: dict[str, datetime | None] | None = None,
    note: dict[str, Any] | None = None,
) -> dict[str, Any]:
    stamps = dict(stamps or {})
    session = _own_session()
    try:
        existing = session.scalar(
            select(UpbitStrategyObsOrderTimelineEntity).where(
                UpbitStrategyObsOrderTimelineEntity.order_id == int(order_id),
                UpbitStrategyObsOrderTimelineEntity.side_code
                == str(side_code).upper(),
            )
        )
        if existing is None:
            existing = UpbitStrategyObsOrderTimelineEntity(
                user_broker_account_id=int(user_broker_account_id),
                strategy_id=int(strategy_id) if strategy_id else None,
                symbol=str(symbol).upper(),
                side_code=str(side_code).upper(),
                order_id=int(order_id),
                binding_id=int(binding_id) if binding_id else None,
                signal_id=str(signal_id) if signal_id else None,
                selection_id=int(selection_id) if selection_id else None,
                rule_version=RULE_VERSION,
            )
            session.add(existing)

        for field in (
            "candidate_at",
            "signal_at",
            "admission_at",
            "intent_created_at",
            "broker_submit_at",
            "broker_ack_at",
            "fill_at",
        ):
            if stamps.get(field) is not None:
                setattr(existing, field, stamps[field])

        lat = {
            "candidate_to_signal_ms": _ms(
                existing.candidate_at, existing.signal_at
            ),
            "signal_to_admission_ms": _ms(
                existing.signal_at, existing.admission_at
            ),
            "admission_to_intent_ms": _ms(
                existing.admission_at, existing.intent_created_at
            ),
            "intent_to_submit_ms": _ms(
                existing.intent_created_at, existing.broker_submit_at
            ),
            "submit_to_ack_ms": _ms(
                existing.broker_submit_at, existing.broker_ack_at
            ),
            "ack_to_fill_ms": _ms(existing.broker_ack_at, existing.fill_at),
            "candidate_to_fill_ms": _ms(existing.candidate_at, existing.fill_at),
            "signal_to_fill_ms": _ms(existing.signal_at, existing.fill_at),
        }
        existing.latency_json = {k: v for k, v in lat.items() if v is not None}
        if note:
            merged = dict(existing.note_json or {})
            merged.update(note)
            existing.note_json = merged
        existing.updated_at = _now()
        session.commit()

        # Also append timeline event for query convenience
        persist_event(
            event_type=EVENT_ORDER_TIMELINE,
            payload={
                "order_id": int(order_id),
                "side_code": str(side_code).upper(),
                "latency_json": existing.latency_json,
                "stamps": {k: (v.isoformat() if v else None) for k, v in stamps.items()},
            },
            user_broker_account_id=user_broker_account_id,
            strategy_id=strategy_id,
            symbol=symbol,
            order_id=order_id,
            signal_id=signal_id,
            selection_id=selection_id,
            binding_id=binding_id,
        )
        return {"ok": True, "order_id": int(order_id), "latency": existing.latency_json}
    except Exception as exc:  # noqa: BLE001
        try:
            session.rollback()
        except Exception:  # noqa: BLE001
            pass
        return _fail("ORDER_TIMELINE", exc)
    finally:
        session.close()


def build_signal_payload(
    *,
    signal_type: str,
    price: Any,
    short_ma: Any,
    long_ma: Any,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    short = _dec(short_ma)
    long = _dec(long_ma)
    spread = None
    if short is not None and long is not None:
        spread = short - long
    payload: dict[str, Any] = {
        "signal_type": signal_type,
        "price_at_signal": str(price) if price is not None else None,
        "fast_ma": str(short) if short is not None else None,
        "slow_ma": str(long) if long is not None else None,
        "ma_spread": str(spread) if spread is not None else None,
        "ma_slope": None,  # not computed for trading; leave null unless provided
        "orderbook": ORDERBOOK_POLICY,
        "observation_only": True,
        "used_in_trading_decision": False,
    }
    if extra:
        # Strip any accidental look-ahead
        cleaned = {
            k: v
            for k, v in extra.items()
            if k not in {"mfe_pct", "mae_pct", "post_exit_json", "forward_return"}
        }
        payload.update(cleaned)
    assert_no_lookahead_in_trading_payload(payload)
    return payload


def build_admission_payload(admission_dict: dict[str, Any]) -> dict[str, Any]:
    snap = dict(admission_dict.get("snapshot") or {})
    payload = {
        "admission_allowed": bool(admission_dict.get("allowed")),
        "reason": admission_dict.get("reason_code"),
        "source": admission_dict.get("source"),
        "open_order_count": snap.get("open_order_count"),
        "position_count": snap.get("position_count")
        or snap.get("auto_position_count"),
        "daily_loss": snap.get("daily_loss") or snap.get("realized_pnl"),
        "daily_loss_limit": snap.get("daily_loss_limit"),
        "managed_symbol": snap.get("managed_symbol") or snap.get("symbol_managed"),
        "ambiguous_state": snap.get("ambiguous_state") or snap.get("ambiguous_count"),
        "recovery_conflict": snap.get("recovery_conflict")
        or snap.get("recovery_conflicts"),
        "activation_status": snap.get("activation_status"),
        "authorization_status": snap.get("authorization_status"),
        "LIVE": snap.get("live") or snap.get("LIVE"),
        "ARM": snap.get("arm") or snap.get("ARM"),
        "runtime_state": snap.get("runtime_state"),
        "raw_snapshot_keys": sorted(snap.keys()),
        "observation_only": True,
        "used_in_trading_decision": False,
    }
    assert_no_lookahead_in_trading_payload(payload)
    return payload


def build_regime_payload(
    *,
    btc_returns: dict[str, float | None] | None = None,
    eth_returns: dict[str, float | None] | None = None,
    breadth: dict[str, Any] | None = None,
    symbol_ret_30m: float | None = None,
    symbol_range_30m: float | None = None,
) -> dict[str, Any]:
    btc_returns = dict(btc_returns or {})
    eth_returns = dict(eth_returns or {})
    return {
        "btc": btc_returns,
        "eth": eth_returns,
        "btc_trend": classify_btc_trend(btc_returns.get("return_15m")),
        "symbol_regime": classify_symbol_regime(
            ret_30m_pct=symbol_ret_30m, range_pct_30m=symbol_range_30m
        ),
        "breadth": breadth or {},
        "formula": regime_formula_doc(),
        "observation_only": True,
        "used_in_trading_decision": False,
    }


# Re-export event type constants for hooks
__all_event__ = (
    EVENT_ADMISSION,
    EVENT_EXIT,
    EVENT_REGIME,
    EVENT_SIGNAL_BUY,
    EVENT_SIGNAL_SELL,
    EVENT_ORDER_TIMELINE,
)
