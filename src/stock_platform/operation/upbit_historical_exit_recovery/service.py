# -*- coding: utf-8 -*-
"""Historical orphan MA exit — DETECT_ONLY dry-run (mutation 금지).

WRK-20260829-UPBIT-HISTORICAL-EXIT-RECOVERY-AND-LONG-HOLD-WATCH-V1

실제 recovery INSERT/SELL는 별도 운영자 승인 WRK에서만.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from stock_platform.operation.upbit_historical_exit_recovery.constants import (
    ACTIVE_EXIT_INTENT_STATUSES,
    CANCELLED_STATUSES,
    DEFAULT_EXIT_MIN_MA_SEPARATION_PCT,
    EXIT_REASON_MA_DEAD_CROSS,
    MODE_DETECT_ONLY,
    OPEN_BINDING_STATUS,
    OWNERSHIP_AUTO,
    OWNERSHIP_MANUAL,
    OWNERSHIP_UNKNOWN,
    PROPOSED_ACTION_CREATE_INTENT,
    PROPOSED_INTENT_STATUS,
    VALID_HISTORICAL_EXIT_REASONS,
)
from stock_platform.risk_engine.exit_risk import PENDING_SELL_STATUSES

# Durable Exit Intent 초기 상태 (패키지 import 순환/무거운 의존 회피)
STATUS_CONFIRMED = PROPOSED_INTENT_STATUS
ACTIVE_STATUSES = ACTIVE_EXIT_INTENT_STATUSES


def _ma_separation_pct(
    short_ma: Decimal | None, long_ma: Decimal | None
) -> float | None:
    if short_ma is None or long_ma is None:
        return None
    if long_ma <= ZERO:
        return None
    try:
        return float((short_ma - long_ma) / long_ma * Decimal("100"))
    except Exception:  # noqa: BLE001
        return None


def _is_dead_cross_confirmed(
    *,
    short_ma: Decimal | None,
    long_ma: Decimal | None,
    exit_min_ma_separation_pct: float,
) -> bool:
    if short_ma is None or long_ma is None:
        return False
    if short_ma >= long_ma:
        return False
    sep = _ma_separation_pct(short_ma, long_ma)
    if sep is None:
        return False
    return sep <= -abs(float(exit_min_ma_separation_pct))


def _resolve_exit_min_sep(risk_group_policy_json: dict[str, Any] | None) -> float:
    if isinstance(risk_group_policy_json, dict):
        raw = risk_group_policy_json.get("exit_min_ma_separation_pct")
        if raw is not None:
            try:
                return float(raw)
            except (TypeError, ValueError):
                pass
    return float(DEFAULT_EXIT_MIN_MA_SEPARATION_PCT)

ZERO = Decimal("0")
QTY_TOLERANCE = Decimal("0.00000001")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _dec(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:  # noqa: BLE001
        return None


def _meta_reason(meta: Any) -> str | None:
    if not isinstance(meta, dict):
        return None
    for key in ("signal_reason", "exit_reason", "reason"):
        raw = meta.get(key)
        if raw:
            return str(raw).upper()
    return None


def _is_auto_order(meta: Any) -> bool:
    if not isinstance(meta, dict):
        return False
    src = str(meta.get("order_source") or "").upper()
    env = str(meta.get("environment") or meta.get("execution_mode") or "").upper()
    if src in {"TEST", "SMOKE", "PAPER"}:
        return False
    if env == "PAPER":
        return False
    return src == "AUTO" or str(meta.get("source") or "").upper() in {
        "REALTIME_SIGNAL",
        "POSITION_EXIT_MONITOR",
    }


def approximate_ma_from_ticks(
    session: Session,
    *,
    symbol: str,
    short_window: int = 5,
    long_window: int = 20,
) -> dict[str, Any]:
    """최근 trade_tick으로 MA 근사 (runtime deque와 완전 일치하지 않을 수 있음)."""

    needed = int(long_window) + 1
    rows = session.execute(
        text(
            """
            SELECT t.price::float8 AS price
            FROM market.trade_tick t
            JOIN market.instrument i ON i.instrument_id = t.instrument_id
            WHERE i.symbol = :sym
            ORDER BY t.traded_at DESC
            LIMIT :lim
            """
        ),
        {"sym": str(symbol).upper(), "lim": needed},
    ).mappings().all()
    prices = [Decimal(str(r["price"])) for r in rows if r.get("price") is not None]
    if len(prices) < int(long_window):
        return {
            "short_ma": None,
            "long_ma": None,
            "prev_short_ma": None,
            "prev_long_ma": None,
            "ok": False,
            "reason": "INSUFFICIENT_TICKS",
        }
    short = sum(prices[:short_window]) / Decimal(short_window)
    long = sum(prices[:long_window]) / Decimal(long_window)
    prev_short = sum(prices[1 : short_window + 1]) / Decimal(short_window)
    prev_long = sum(prices[1 : long_window + 1]) / Decimal(long_window)
    return {
        "short_ma": short,
        "long_ma": long,
        "prev_short_ma": prev_short,
        "prev_long_ma": prev_long,
        "ok": True,
        "reason": None,
    }


def _quote_price(
    session: Session, symbol: str
) -> tuple[Decimal | None, datetime | None, bool]:
    row = session.execute(
        text(
            """
            SELECT q.trade_price, q.quoted_at
            FROM market.quote_snapshot q
            JOIN market.instrument i ON i.instrument_id = q.instrument_id
            WHERE i.symbol = :sym
            LIMIT 1
            """
        ),
        {"sym": str(symbol).upper()},
    ).mappings().first()
    if not row:
        return None, None, False
    price = _dec(row.get("trade_price"))
    quoted_at = row.get("quoted_at")
    stale = False
    if quoted_at is not None:
        try:
            qa = quoted_at
            if getattr(qa, "tzinfo", None) is None:
                qa = qa.replace(tzinfo=timezone.utc)
            age = (_now() - qa).total_seconds()
            stale = age > 900
        except Exception:  # noqa: BLE001
            stale = True
    return price, quoted_at, stale


def _broker_qty(session: Session, uba_id: int, symbol: str) -> Decimal | None:
    row = session.execute(
        text(
            """
            SELECT quantity
            FROM trading.broker_position_snapshot
            WHERE user_broker_account_id = :uba
              AND symbol = :sym
            ORDER BY broker_position_snapshot_id DESC
            LIMIT 1
            """
        ),
        {"uba": int(uba_id), "sym": str(symbol).upper()},
    ).mappings().first()
    if not row:
        return None
    return _dec(row.get("quantity"))


def _has_open_sell(session: Session, uba_id: int, symbol: str) -> bool:
    statuses = [str(s) for s in PENDING_SELL_STATUSES]
    row = session.execute(
        text(
            """
            SELECT COUNT(*) AS n
            FROM trading.trading_order
            WHERE user_broker_account_id = :uba
              AND UPPER(symbol) = :sym
              AND UPPER(side_code) = 'SELL'
              AND UPPER(status_code) = ANY(:st)
            """
        ),
        {"uba": int(uba_id), "sym": str(symbol).upper(), "st": statuses},
    ).mappings().first()
    return int((row or {}).get("n") or 0) > 0


def _has_active_intent(session: Session, uba_id: int, symbol: str) -> bool:
    row = session.execute(
        text(
            """
            SELECT COUNT(*) AS n
            FROM operation.upbit_exit_intent
            WHERE user_broker_account_id = :uba
              AND UPPER(symbol) = :sym
              AND status = ANY(:st)
            """
        ),
        {
            "uba": int(uba_id),
            "sym": str(symbol).upper(),
            "st": list(ACTIVE_STATUSES),
        },
    ).mappings().first()
    return int((row or {}).get("n") or 0) > 0


def _blocking_lifecycle(session: Session, uba_id: int, symbol: str) -> list[str]:
    blockers: list[str] = []
    if _has_open_sell(session, uba_id, symbol):
        blockers.append("OPEN_SELL_EXISTS")
    row = session.execute(
        text(
            """
            SELECT
              COUNT(*) FILTER (
                WHERE UPPER(status_code) IN (
                  'CANCEL_REQUESTED', 'REPLACE_REQUESTED'
                )
              ) AS cancel_pending,
              COUNT(*) FILTER (
                WHERE UPPER(status_code) IN (
                  'SUBMITTING', 'SENT', 'AMBIGUOUS_SUBMISSION',
                  'REMOTE_LOOKUP_PENDING'
                )
              ) AS submission_inflight
            FROM trading.trading_order
            WHERE user_broker_account_id = :uba
              AND UPPER(symbol) = :sym
              AND UPPER(side_code) = 'SELL'
            """
        ),
        {"uba": int(uba_id), "sym": str(symbol).upper()},
    ).mappings().first()
    if row:
        if int(row.get("cancel_pending") or 0) > 0:
            blockers.append("CANCEL_PENDING")
        if int(row.get("submission_inflight") or 0) > 0:
            blockers.append("BROKER_SUBMISSION_INFLIGHT")
    return blockers


def _find_orphan_exit_order(
    session: Session,
    *,
    uba_id: int,
    symbol: str,
    entry_order_id: int,
) -> dict[str, Any] | None:
    rows = session.execute(
        text(
            """
            SELECT order_id, status_code, filled_quantity, order_quantity,
                   average_fill_price, order_price, metadata_payload,
                   created_at, cancelled_at, filled_at
            FROM trading.trading_order
            WHERE user_broker_account_id = :uba
              AND UPPER(symbol) = :sym
              AND UPPER(side_code) = 'SELL'
              AND order_id > :entry_id
            ORDER BY order_id DESC
            LIMIT 20
            """
        ),
        {
            "uba": int(uba_id),
            "sym": str(symbol).upper(),
            "entry_id": int(entry_order_id),
        },
    ).mappings().all()
    for row in rows:
        meta = row.get("metadata_payload") or {}
        if not _is_auto_order(meta):
            continue
        reason = _meta_reason(meta)
        if reason not in VALID_HISTORICAL_EXIT_REASONS:
            continue
        status = str(row.get("status_code") or "").upper()
        filled = _dec(row.get("filled_quantity")) or ZERO
        if status not in CANCELLED_STATUSES:
            continue
        if filled > ZERO:
            return {
                "order_id": int(row["order_id"]),
                "blocked": True,
                "block_reason": "PARTIAL_HISTORICAL_FILL",
                "filled_quantity": str(filled),
                "status_code": status,
                "exit_reason": reason,
            }
        return {
            "order_id": int(row["order_id"]),
            "blocked": False,
            "filled_quantity": "0",
            "status_code": status,
            "exit_reason": reason,
            "created_at": row.get("created_at"),
            "cancelled_at": row.get("cancelled_at"),
            "order_price": (
                str(row.get("order_price"))
                if row.get("order_price") is not None
                else None
            ),
            "metadata_payload": meta if isinstance(meta, dict) else {},
        }
    return None


def _slot_info(session: Session, uba_id: int, symbol: str) -> dict[str, Any]:
    row = session.execute(
        text(
            """
            SELECT slot_id, slot_no, status, entry_order_id, position_binding_id,
                   opened_at
            FROM operation.upbit_position_slot
            WHERE user_broker_account_id = :uba
              AND UPPER(symbol) = :sym
              AND UPPER(status) = 'OPEN'
            ORDER BY slot_id DESC
            LIMIT 1
            """
        ),
        {"uba": int(uba_id), "sym": str(symbol).upper()},
    ).mappings().first()
    return dict(row) if row else {}


def evaluate_exit_condition(
    *,
    short_ma: Decimal | None,
    long_ma: Decimal | None,
    prev_short_ma: Decimal | None = None,
    prev_long_ma: Decimal | None = None,
    risk_group_policy_json: dict[str, Any] | None = None,
    settings: Any = None,
) -> dict[str, Any]:
    """Historical recovery용 조건 — 새 edge 필수 아님."""

    if short_ma is None or long_ma is None:
        return {
            "ma_state": "UNKNOWN",
            "dead_cross_edge": False,
            "dead_cross_state": False,
            "current_exit_condition_active": False,
            "confirmed_for_retry": False,
            "separation_pct": None,
            "block_reason": "MA_UNKNOWN",
            "new_edge_required_for_recovery": False,
        }
    bearish = short_ma < long_ma
    edge = False
    if (
        prev_short_ma is not None
        and prev_long_ma is not None
        and prev_short_ma >= prev_long_ma
        and short_ma < long_ma
    ):
        edge = True
    th_sep = _resolve_exit_min_sep(risk_group_policy_json)
    if settings is not None:
        try:
            th_sep = float(
                getattr(
                    settings,
                    "upbit_portfolio_exit_min_ma_separation_pct",
                    th_sep,
                )
                or th_sep
            )
        except (TypeError, ValueError):
            pass
    sep = _ma_separation_pct(short_ma, long_ma)
    confirmed = _is_dead_cross_confirmed(
        short_ma=short_ma,
        long_ma=long_ma,
        exit_min_ma_separation_pct=th_sep,
    )
    return {
        "ma_state": "BEARISH" if bearish else "BULLISH",
        "dead_cross_edge": edge,
        "dead_cross_state": bearish,
        "current_exit_condition_active": bearish,
        "confirmed_for_retry": confirmed,
        "separation_pct": sep,
        "exit_min_ma_separation_pct": th_sep,
        "short_ma": str(short_ma),
        "long_ma": str(long_ma),
        "prev_short_ma": str(prev_short_ma) if prev_short_ma is not None else None,
        "prev_long_ma": str(prev_long_ma) if prev_long_ma is not None else None,
        "new_edge_required_for_recovery": False,
        "block_reason": None if bearish else "CURRENT_CONDITION_INACTIVE",
    }


def evaluate_candidate(
    session: Session,
    *,
    binding: dict[str, Any],
    short_ma: Decimal | None = None,
    long_ma: Decimal | None = None,
    prev_short_ma: Decimal | None = None,
    prev_long_ma: Decimal | None = None,
    risk_group_policy_json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """단일 OPEN binding 후보 평가 — DB mutation 없음."""

    blockers: list[str] = []
    uba_id = int(binding["user_broker_account_id"])
    symbol = str(binding["symbol"]).upper()
    ownership = str(binding.get("ownership_code") or "").upper()
    status = str(binding.get("status") or "").upper()
    qty = _dec(binding.get("owned_quantity")) or ZERO
    entry_order_id = binding.get("entry_order_id")
    entry_price = _dec(binding.get("entry_price"))
    opened_at = binding.get("opened_at")
    binding_id = int(binding["binding_id"])

    if ownership == OWNERSHIP_MANUAL:
        blockers.append("MANUAL_EXCLUDED")
    elif ownership == OWNERSHIP_UNKNOWN or not ownership:
        blockers.append("UNKNOWN_EXCLUDED")
    elif ownership != OWNERSHIP_AUTO:
        blockers.append("OWNERSHIP_NOT_AUTO")

    if status != OPEN_BINDING_STATUS:
        blockers.append("POSITION_NOT_OPEN")
    if qty <= ZERO:
        blockers.append("POSITION_FLAT")
    if entry_order_id is None:
        blockers.append("ENTRY_ORDER_MISSING")
    else:
        entry_order_id = int(entry_order_id)

    broker_qty = _broker_qty(session, uba_id, symbol)
    position_sync_ok = False
    if broker_qty is None:
        blockers.append("BROKER_QTY_MISSING")
    elif broker_qty <= ZERO:
        blockers.append("BROKER_QTY_ZERO")
    else:
        position_sync_ok = abs(broker_qty - qty) <= QTY_TOLERANCE
        if not position_sync_ok:
            blockers.append("POSITION_BROKER_QTY_MISMATCH")

    if _has_active_intent(session, uba_id, symbol):
        blockers.append("EXISTING_EXIT_INTENT")

    blockers.extend(_blocking_lifecycle(session, uba_id, symbol))
    if "OPEN_SELL_EXISTS" in blockers:
        blockers.append("EXIT_PENDING")

    orphan: dict[str, Any] | None = None
    if entry_order_id is not None and "ENTRY_ORDER_MISSING" not in blockers:
        orphan = _find_orphan_exit_order(
            session,
            uba_id=uba_id,
            symbol=symbol,
            entry_order_id=entry_order_id,
        )
        if orphan is None:
            blockers.append("HISTORICAL_EXIT_ORDER_MISSING")
        elif orphan.get("blocked"):
            blockers.append(str(orphan.get("block_reason") or "PARTIAL_HISTORICAL_FILL"))
        elif not orphan.get("exit_reason"):
            blockers.append("HISTORICAL_EXIT_REASON_MISSING")

    ma_injected = short_ma is not None and long_ma is not None
    if not ma_injected:
        ma_approx = approximate_ma_from_ticks(session, symbol=symbol)
        short_ma = ma_approx.get("short_ma")
        long_ma = ma_approx.get("long_ma")
        prev_short_ma = ma_approx.get("prev_short_ma")
        prev_long_ma = ma_approx.get("prev_long_ma")
        if not ma_approx.get("ok"):
            blockers.append("MA_DATA_INSUFFICIENT")

    cond = evaluate_exit_condition(
        short_ma=short_ma,
        long_ma=long_ma,
        prev_short_ma=prev_short_ma,
        prev_long_ma=prev_long_ma,
        risk_group_policy_json=risk_group_policy_json,
    )
    if not cond["current_exit_condition_active"]:
        blockers.append("CURRENT_CONDITION_INACTIVE")

    quote, quoted_at, quote_stale = _quote_price(session, symbol)
    hold_seconds = None
    if opened_at is not None:
        try:
            oa = opened_at
            if getattr(oa, "tzinfo", None) is None:
                oa = oa.replace(tzinfo=timezone.utc)
            hold_seconds = int((_now() - oa).total_seconds())
        except Exception:  # noqa: BLE001
            hold_seconds = None

    pnl = None
    pnl_rate = None
    if quote is not None and entry_price is not None and qty > ZERO:
        pnl = float((quote - entry_price) * qty)
        cost = float(entry_price * qty)
        pnl_rate = (pnl / cost * 100.0) if cost else None

    # 중복 제거
    blockers = list(dict.fromkeys(blockers))
    eligible = len(blockers) == 0
    slot = _slot_info(session, uba_id, symbol)

    proposed = None
    if eligible and orphan and not orphan.get("blocked"):
        proposed = {
            "proposed_action": PROPOSED_ACTION_CREATE_INTENT,
            "proposed_intent_status": PROPOSED_INTENT_STATUS,
            "proposed_retry_count": 0,
            "proposed_order": "NONE_IN_THIS_WRK",
            "remaining_qty": str(qty),
            "exit_reason": orphan.get("exit_reason") or EXIT_REASON_MA_DEAD_CROSS,
            "historical_exit_order_id": orphan.get("order_id"),
            "entry_order_id": entry_order_id,
            "binding_id": binding_id,
            "note": (
                "Would create operation.upbit_exit_intent CONFIRMED "
                "for existing durable retry path. NO INSERT this WRK."
            ),
            "expected_next_behavior": (
                "After operator-approved recovery: durable intent → "
                "state revalidation (no new edge) → SELL attempt → "
                "zero/partial retry → Alert V2. REAL SELL possible."
                if cond.get("confirmed_for_retry")
                else (
                    "After operator-approved recovery: intent CONFIRMED, "
                    "but current MA separation below confirm threshold — "
                    "revalidation may CONDITION_CLEARED until sep widens; "
                    "REAL SELL possible once condition confirms."
                )
            ),
        }

    return {
        "mode": MODE_DETECT_ONLY,
        "symbol": symbol,
        "binding_id": binding_id,
        "slot_id": slot.get("slot_id"),
        "slot_no": slot.get("slot_no"),
        "ownership": ownership,
        "status": status,
        "entry_order_id": entry_order_id,
        "entry_price": str(entry_price) if entry_price is not None else None,
        "qty": str(qty),
        "broker_qty": str(broker_qty) if broker_qty is not None else None,
        "position_sync_ok": position_sync_ok,
        "opened_at": opened_at.isoformat() if opened_at else None,
        "holding_seconds": hold_seconds,
        "current_price": None if quote is None or quote_stale else str(quote),
        "current_price_raw": str(quote) if quote is not None else None,
        "current_price_stale": quote_stale,
        "quoted_at": quoted_at.isoformat() if quoted_at else None,
        "estimated_pnl": pnl,
        "estimated_pnl_rate_pct": pnl_rate,
        "historical_exit_order": orphan,
        "ma_condition": cond,
        "eligible": eligible,
        "blockers": blockers,
        "current_condition_active": bool(cond["current_exit_condition_active"]),
        "new_edge_required_for_recovery": False,
        "proposed": proposed,
        "db_mutated": False,
        "order_created": False,
        "exit_intent_inserted": False,
    }


def list_open_auto_bindings(
    session: Session, *, user_broker_account_id: int
) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            SELECT binding_id, user_broker_account_id, symbol, status,
                   ownership_code, entry_order_id, owned_quantity,
                   entry_price, opened_at, meta_json
            FROM operation.strategy_position_binding
            WHERE user_broker_account_id = :uba
              AND UPPER(broker_code) = 'UPBIT'
              AND UPPER(status) = 'OPEN'
            ORDER BY binding_id
            """
        ),
        {"uba": int(user_broker_account_id)},
    ).mappings().all()
    return [dict(r) for r in rows]


def list_historical_exit_recovery_candidates(
    session: Session,
    *,
    user_broker_account_id: int,
    short_ma: Decimal | None = None,
    long_ma: Decimal | None = None,
    prev_short_ma: Decimal | None = None,
    prev_long_ma: Decimal | None = None,
    risk_group_policy_json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """UBA 단위 DETECT_ONLY 후보 목록."""

    policy = risk_group_policy_json
    if policy is None:
        prow = session.execute(
            text(
                """
                SELECT risk_group_policy_json
                FROM operation.upbit_portfolio_policy
                WHERE user_broker_account_id = :uba
                LIMIT 1
                """
            ),
            {"uba": int(user_broker_account_id)},
        ).mappings().first()
        if prow and isinstance(prow.get("risk_group_policy_json"), dict):
            policy = prow["risk_group_policy_json"]

    bindings = list_open_auto_bindings(
        session, user_broker_account_id=int(user_broker_account_id)
    )
    candidates = [
        evaluate_candidate(
            session,
            binding=b,
            short_ma=short_ma,
            long_ma=long_ma,
            prev_short_ma=prev_short_ma,
            prev_long_ma=prev_long_ma,
            risk_group_policy_json=policy,
        )
        for b in bindings
    ]
    eligible = [c for c in candidates if c.get("eligible")]
    return {
        "mode": MODE_DETECT_ONLY,
        "user_broker_account_id": int(user_broker_account_id),
        "as_of": _now().isoformat(),
        "candidate_count": len(candidates),
        "eligible_count": len(eligible),
        "candidates": candidates,
        "db_mutated": False,
        "order_created": False,
        "exit_intent_inserted": False,
        "post_recover_endpoint": None,
        "note": (
            "GET detect-only. POST recover requires separate "
            "operator-approved WRK."
        ),
    }


def dry_run_historical_exit_recovery(
    session: Session,
    *,
    user_broker_account_id: int,
    symbol: str,
    short_ma: Decimal | None = None,
    long_ma: Decimal | None = None,
    prev_short_ma: Decimal | None = None,
    prev_long_ma: Decimal | None = None,
) -> dict[str, Any]:
    """단일 심볼 dry-run — INSERT/SELL 절대 없음."""

    listing = list_historical_exit_recovery_candidates(
        session,
        user_broker_account_id=int(user_broker_account_id),
        short_ma=short_ma,
        long_ma=long_ma,
        prev_short_ma=prev_short_ma,
        prev_long_ma=prev_long_ma,
    )
    sym = str(symbol).upper()
    match = next(
        (c for c in listing["candidates"] if c.get("symbol") == sym),
        None,
    )
    if match is None:
        return {
            "mode": MODE_DETECT_ONLY,
            "symbol": sym,
            "eligible": False,
            "RESULT": "NOT_ELIGIBLE",
            "blockers": ["POSITION_NOT_FOUND"],
            "db_mutated": False,
            "order_created": False,
            "exit_intent_inserted": False,
            "proposed_action": None,
            "proposed_intent_status": None,
        }
    return {
        "mode": MODE_DETECT_ONLY,
        "RESULT": "ELIGIBLE" if match["eligible"] else "NOT_ELIGIBLE",
        **match,
        "proposed_action": (match.get("proposed") or {}).get("proposed_action"),
        "proposed_intent_status": (match.get("proposed") or {}).get(
            "proposed_intent_status"
        )
        or (STATUS_CONFIRMED if match["eligible"] else None),
        "remaining_qty": (match.get("proposed") or {}).get("remaining_qty")
        or match.get("qty"),
        "expected_next_behavior": (match.get("proposed") or {}).get(
            "expected_next_behavior"
        ),
    }
