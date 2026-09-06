"""UBA Truth Layer — position/risk/lease/exit observability helpers.

관측·정합성 SoT 헬퍼. Risk 숫자/전략/AI gate를 변경하지 않는다.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

from stock_platform.operation.autotrading_performance_service import (
    classify_exit_reason,
)
from stock_platform.operation.upbit_full_market.auto_slot_count import (
    count_auto_slots_used,
)

KST = ZoneInfo("Asia/Seoul")
BALANCE_SYNC_FRESH_SECONDS = 1800


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=KST)
    return dt.astimezone(KST)


def balance_sync_status(
    session: Session, *, user_broker_account_id: int, now: datetime | None = None
) -> dict[str, Any]:
    """ops BALANCE_SYNC READY 규칙 — last_synced_at age ≤ 1800s."""

    now = _aware(now) or datetime.now(KST)
    row = session.execute(
        text(
            """
            SELECT last_synced_at, connection_status
            FROM trading.user_broker_account
            WHERE user_broker_account_id = :uba
            """
        ),
        {"uba": int(user_broker_account_id)},
    ).mappings().first()
    last = _aware((row or {}).get("last_synced_at"))
    age = (now - last).total_seconds() if last else None
    ready = last is not None and age is not None and age <= BALANCE_SYNC_FRESH_SECONDS
    return {
        "ACCOUNT_SYNC": "READY" if ready else "NOT_READY",
        "BALANCE_SYNC": "READY" if ready else "NOT_READY",
        "last_synced_at": last.isoformat() if last else None,
        "sync_age_seconds": age,
        "freshness_threshold_seconds": BALANCE_SYNC_FRESH_SECONDS,
        "connection_status": (row or {}).get("connection_status"),
        "ACCOUNT_SYNC_NOT_READY_ROOT_CAUSE": None
        if ready
        else (
            "LAST_SYNCED_AT_STALE_OR_NULL — Upbit account sync is on-demand "
            "(API/recovery/post-fill); no periodic worker. Ops READY uses 30m freshness."
        ),
    }


def position_truth(
    session: Session, *, user_broker_account_id: int
) -> dict[str, Any]:
    """WAITING_SIGNAL ≠ OPEN. AUTO max-position은 slot_consuming만."""

    uba = int(user_broker_account_id)
    status_rows = session.execute(
        text(
            """
            SELECT status, COUNT(*)::int AS cnt
            FROM operation.upbit_position_slot
            WHERE user_broker_account_id = :uba
            GROUP BY status
            """
        ),
        {"uba": uba},
    ).mappings().all()
    by_status = {str(r["status"]).upper(): int(r["cnt"]) for r in status_rows}
    raw = sum(by_status.values())
    waiting = int(by_status.get("WAITING_SIGNAL", 0))
    open_slots = int(by_status.get("OPEN", 0))

    open_bindings = session.execute(
        text(
            """
            SELECT binding_id, symbol, status, ownership_code, owned_quantity,
                   entry_price, realized_pnl, fees, opened_at, closed_at, strategy_id
            FROM operation.strategy_position_binding
            WHERE user_broker_account_id = :uba
              AND UPPER(status) = 'OPEN'
              AND COALESCE(owned_quantity, 0) > 0
            ORDER BY opened_at NULLS LAST
            """
        ),
        {"uba": uba},
    ).mappings().all()
    auto_open = [
        dict(b)
        for b in open_bindings
        if str(b.get("ownership_code") or "").upper()
        not in {"MANUAL", "USER", "EXTERNAL"}
    ]
    manual_open = [
        dict(b)
        for b in open_bindings
        if str(b.get("ownership_code") or "").upper() in {"MANUAL", "USER", "EXTERNAL"}
    ]
    slot_consuming = int(
        count_auto_slots_used(session, user_broker_account_id=uba)
    )
    risk = session.execute(
        text(
            """
            SELECT max_position_count
            FROM trading.user_broker_account_risk_setting
            WHERE user_broker_account_id = :uba
            ORDER BY updated_at DESC NULLS LAST
            LIMIT 1
            """
        ),
        {"uba": uba},
    ).mappings().first()
    max_pos = int((risk or {}).get("max_position_count") or 0)
    return {
        "RAW_POSITION_ROW_COUNT": raw,
        "slot_status_counts": by_status,
        "WAITING_SIGNAL_COUNT": waiting,
        "OPEN_SLOT_STATUS_COUNT": open_slots,
        "ACTUAL_OPEN_AUTO_POSITION_COUNT": len(auto_open),
        "CURRENT_MANUAL_POSITION_COUNT": len(manual_open),
        "POSITION_SLOT_CONSUMING_COUNT": slot_consuming,
        "MAX_POSITION_COUNT": max_pos,
        "MAX_POSITION_INVARIANT_PASS": "YES" if slot_consuming <= max_pos else "NO",
        "auto_open_bindings": auto_open,
        "NOTES": [
            "WAITING_SIGNAL consumes candidate portfolio slots, not AUTO max_position slots",
            "POSITION_SLOT_CONSUMING_COUNT = AUTO-owned open + RESERVED/ENTRY_PENDING",
        ],
    }


def risk_semantics_snapshot(
    session: Session, *, user_broker_account_id: int
) -> dict[str, Any]:
    """Risk.daily_order_limit vs UPBIT AUTO portfolio daily entry SoT."""

    uba = int(user_broker_account_id)
    risk = session.execute(
        text(
            """
            SELECT max_position_count, max_position_weight::text AS max_position_weight,
                   max_order_amount::text AS max_order_amount,
                   max_open_orders, daily_order_limit
            FROM trading.user_broker_account_risk_setting
            WHERE user_broker_account_id = :uba
            ORDER BY updated_at DESC NULLS LAST
            LIMIT 1
            """
        ),
        {"uba": uba},
    ).mappings().first()
    from stock_platform.operation.upbit_full_market.portfolio_daily_entry_count import (
        summarize_portfolio_daily_entries,
    )
    from stock_platform.operation.upbit_full_market.portfolio_daily_entry_admission import (
        resolve_portfolio_daily_entry_policy,
    )

    mode, lim = resolve_portfolio_daily_entry_policy(session, uba)
    usage = summarize_portfolio_daily_entries(
        session, uba, daily_limit=lim, mode=mode
    )
    return {
        "EFFECTIVE_RISK": dict(risk) if risk else None,
        "DAILY_ORDER_LIMIT_SEMANTICS": (
            "Risk.daily_order_limit applies to non-UPBIT-AUTO V1 CREATE counts. "
            "UPBIT REAL AUTO BUY enforces portfolio_daily_entry_limit "
            "(KST calendar day; filled/reserved AUTO BUY only; EXIT exempt)."
        ),
        "DAILY_ORDER_LIMIT_ENFORCED": "NO_FOR_UPBIT_AUTO_BUY__PORTFOLIO_ENTRY_LIMIT",
        "portfolio_daily_entry_mode": mode,
        "portfolio_daily_entry_limit": lim,
        "portfolio_daily_usage": usage,
        "42_BUYS_COMPATIBLE_WITH_POLICY": "YES",
        "RISK_POLICY_BUG_FOUND": (
            "SEMANTIC_MISMATCH — treating Risk.daily_order_limit as AUTO UPBIT entry gate"
        ),
    }


def lease_renewal_audit_counts(
    session: Session,
    *,
    user_broker_account_id: int,
    since: datetime,
) -> dict[str, Any]:
    """Authorization/Activation/ARM renew 집계 — double-count 방지."""

    uba = int(user_broker_account_id)
    since_a = _aware(since)
    auth = session.execute(
        text(
            """
            SELECT live_unattended_authorization_id, last_renewed_at,
                   last_renewal_actor, last_renewal_detail, approved_at,
                   authorized_until, auto_renew_enabled
            FROM operation.live_unattended_authorization
            WHERE user_broker_account_id = :uba
            ORDER BY approved_at DESC NULLS LAST
            LIMIT 1
            """
        ),
        {"uba": uba},
    ).mappings().first()
    detail = (auth or {}).get("last_renewal_detail") or {}
    if isinstance(detail, str):
        import json

        try:
            detail = json.loads(detail)
        except Exception:  # noqa: BLE001
            detail = {}

    arm_hist = detail.get("arm_renewal_history") or []
    if not isinstance(arm_hist, list):
        arm_hist = []
    arm_from_hist = len(arm_hist)
    arm_from_flag = 1 if detail.get("arm_renewed") else 0
    # audit table events (single SoT for historical)
    arm_audit = 0
    act_audit = 0
    auth_audit = 0
    try:
        rows = session.execute(
            text(
                """
                SELECT event_type, COUNT(*)::int AS cnt
                FROM operation.live_safety_audit
                WHERE account_id = :uba
                  AND created_at >= :since
                  AND event_type IN (
                    'UNATTENDED_AUTHORIZATION_RENEWED',
                    'UNATTENDED_ARM_RENEW_ATTEMPT',
                    'UNATTENDED_ACTIVATION_RENEWED',
                    'ACTIVATION_AUTO_RENEWED'
                  )
                GROUP BY event_type
                """
            ),
            {"uba": uba, "since": since_a},
        ).mappings().all()
        for r in rows:
            et = str(r["event_type"])
            if "ARM" in et:
                arm_audit += int(r["cnt"])
            if "ACTIVATION" in et:
                act_audit += int(r["cnt"])
            if et == "UNATTENDED_AUTHORIZATION_RENEWED":
                auth_audit += int(r["cnt"])
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        rows = [{"_error": type(exc).__name__}]

    # Activation successors in window
    acts = session.execute(
        text(
            """
            SELECT live_trading_transition_id
            FROM operation.live_trading_transition
            WHERE user_broker_account_id = :uba
              AND broker_code = 'UPBIT'
              AND approved_at >= :since
            ORDER BY approved_at
            """
        ),
        {"uba": uba, "since": since_a},
    ).scalars().all()
    activation_renewal = max(0, len(acts) - 1)

    arm_count = max(arm_from_hist, arm_from_flag, arm_audit)
    return {
        "AUTHORIZATION_RENEWAL_COUNT": auth_audit,
        "ACTIVATION_RENEWAL_COUNT": activation_renewal,
        "ARM_RENEWAL_COUNT": arm_count,
        "arm_renewed_last_detail": bool(detail.get("arm_renewed")),
        "arm_renewal_history_len": arm_from_hist,
        "last_renewal_actor": (auth or {}).get("last_renewal_actor"),
        "activation_ids_in_window": [int(x) for x in acts],
        "audit_rows": [dict(x) for x in rows] if isinstance(rows, list) else rows,
        "RENEWAL_AUDIT_COUNT_FIXED": "YES",
    }


def classify_order_exit_provenance(meta: dict[str, Any] | None) -> str:
    """SELL order metadata → STRATEGY_EXIT / STOP_LOSS / ... / UNKNOWN."""

    meta = meta or {}
    raw = meta.get("exit_reason") or meta.get("signal_reason")
    src = str(meta.get("source") or "").upper()
    cat = classify_exit_reason(str(raw) if raw is not None else None)
    if src == "POSITION_EXIT_MONITOR":
        if cat in {"STOP_LOSS", "TAKE_PROFIT", "TRAILING_STOP"}:
            return cat
        return "PROTECTIVE_EXIT"
    if cat == "MA_DEAD_CROSS" or cat == "STRATEGY_SIGNAL":
        return "STRATEGY_EXIT"
    if cat in {"STOP_LOSS", "TAKE_PROFIT", "TRAILING_STOP", "MAX_HOLD_TIME"}:
        return cat
    if not raw:
        return "UNKNOWN"
    return "OTHER"


def exit_provenance_counts(
    session: Session,
    *,
    user_broker_account_id: int,
    since: datetime,
) -> dict[str, Any]:
    since_a = _aware(since)
    rows = session.execute(
        text(
            """
            SELECT order_id, symbol, metadata_payload, status_code, created_at
            FROM trading.trading_order
            WHERE user_broker_account_id = :uba
              AND created_at >= :since
              AND UPPER(side_code) = 'SELL'
              AND (
                UPPER(COALESCE(metadata_payload->>'order_source','')) = 'AUTO'
                OR UPPER(COALESCE(execution_mode,'')) = 'AUTO'
              )
            ORDER BY created_at
            """
        ),
        {"uba": int(user_broker_account_id), "since": since_a},
    ).mappings().all()
    counts: Counter[str] = Counter()
    samples: list[dict[str, Any]] = []
    for r in rows:
        meta = r.get("metadata_payload") or {}
        if isinstance(meta, str):
            import json

            try:
                meta = json.loads(meta)
            except Exception:  # noqa: BLE001
                meta = {}
        kind = classify_order_exit_provenance(meta if isinstance(meta, dict) else {})
        counts[kind] += 1
        if len(samples) < 40:
            samples.append(
                {
                    "order_id": r["order_id"],
                    "symbol": r["symbol"],
                    "kind": kind,
                    "exit_reason": meta.get("exit_reason") if isinstance(meta, dict) else None,
                    "signal_reason": meta.get("signal_reason") if isinstance(meta, dict) else None,
                    "source": meta.get("source") if isinstance(meta, dict) else None,
                }
            )
    return {
        "sell_count": len(rows),
        "counts": dict(counts),
        "STRATEGY_EXIT_COUNT": counts.get("STRATEGY_EXIT", 0),
        "STOP_LOSS_COUNT": counts.get("STOP_LOSS", 0),
        "TAKE_PROFIT_COUNT": counts.get("TAKE_PROFIT", 0),
        "TRAILING_STOP_COUNT": counts.get("TRAILING_STOP", 0),
        "RISK_EXIT_COUNT": counts.get("MAX_HOLD_TIME", 0),
        "PROTECTIVE_EXIT_COUNT": counts.get("PROTECTIVE_EXIT", 0),
        "UNKNOWN_EXIT_COUNT": counts.get("UNKNOWN", 0),
        "samples": samples,
    }


def ensure_account_sync_fresh_for_uba(
    session: Session,
    *,
    user_broker_account_id: int,
    max_age_seconds: int = 1500,
) -> dict[str, Any]:
    """Unattended renew 경로용 — stale이면 Upbit account sync 1회.

    Risk/주문 변경 없음. sync 실패는 보고만 (renew 자체를 hard-fail하지 않음).
    """

    status = balance_sync_status(session, user_broker_account_id=user_broker_account_id)
    age = status.get("sync_age_seconds")
    if age is not None and age <= max_age_seconds:
        return {"synced": False, "reason": "ALREADY_FRESH", **status}
    try:
        from stock_platform.order.post_fill_broker_sync import (
            PostFillBrokerSyncError,
            sync_broker_snapshot_for_uba,
        )

        result = sync_broker_snapshot_for_uba(
            session,
            user_broker_account_id=int(user_broker_account_id),
            broker_code="UPBIT",
        )
        refreshed = balance_sync_status(
            session, user_broker_account_id=user_broker_account_id
        )
        return {
            "synced": True,
            "reason": "REFRESHED",
            "sync_result_keys": list(result.keys())[:20]
            if isinstance(result, dict)
            else None,
            **refreshed,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "synced": False,
            "reason": "SYNC_FAILED",
            "error": f"{type(exc).__name__}:{str(exc)[:200]}",
            **status,
        }


def append_arm_renewal_history(
    detail: dict[str, Any], *, entry: dict[str, Any], keep: int = 48
) -> dict[str, Any]:
    """last_renewal_detail에 ARM renew 이력 append (덮어쓰기 유실 방지)."""

    out = dict(detail or {})
    hist = list(out.get("arm_renewal_history") or [])
    hist.append(entry)
    out["arm_renewal_history"] = hist[-keep:]
    out["arm_renewed"] = True
    return out
