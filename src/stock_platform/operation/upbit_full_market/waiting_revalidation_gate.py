"""UPBIT WAITING → REAL BUY 직전 revalidation / restore-epoch gate.

Daily admission과 독립. stale/pre-restore WAITING의 무조건 submit을 막는다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session


REASON_STALE_PRE_RESTORE_WAITING = "STALE_PRE_RESTORE_WAITING"
REASON_EXIT_MONITOR_NOT_RUNNING = "EXIT_MONITOR_NOT_RUNNING"
REASON_MARKET_FEED_NOT_FRESH = "MARKET_FEED_NOT_FRESH"
REASON_WAITING_REVALIDATION_REQUIRED = "WAITING_REVALIDATION_REQUIRED"
REASON_ENTRY_CONDITION_INVALID = "ENTRY_CONDITION_INVALID"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _exit_monitor_running() -> tuple[bool, dict[str, Any]]:
    try:
        from stock_platform.trading.upbit_24x7_control import exit_monitor_status

        st = exit_monitor_status()
        running = str(st.get("status") or "").upper() == "RUNNING"
        return running, dict(st or {})
    except Exception as exc:  # noqa: BLE001
        return False, {"error": type(exc).__name__}


def _feed_real_fresh(session: Session, uba_id: int) -> tuple[bool, dict[str, Any]]:
    """Market feed REAL_FRESH 여부 — readiness와 동일 계열 평가."""

    try:
        from stock_platform.trading.uba_operational_summary import (
            build_uba_operational_summary,
        )

        sm = build_uba_operational_summary(
            session, user_broker_account_id=int(uba_id)
        )
        feed = sm.get("market_feed") or {}
        status = str(feed.get("status") or "").upper()
        detail = feed.get("detail") or {}
        age = detail.get("age_seconds")
        ok = status in {"REAL_FRESH", "FRESH", "CONNECTED", "HEALTHY", "OK"}
        if age is not None:
            try:
                ok = ok and float(age) < 60.0
            except (TypeError, ValueError):
                pass
        # detail.ok 우선
        if "ok" in detail:
            ok = bool(detail.get("ok")) and status not in {
                "DISCONNECTED",
                "STALE",
                "UNHEALTHY",
            }
        return ok, {"status": status, "detail": detail}
    except Exception as exc:  # noqa: BLE001
        return False, {"error": type(exc).__name__}


def load_waiting_slot_updated_at(
    session: Session,
    *,
    user_broker_account_id: int,
    symbol: str,
) -> datetime | None:
    """WAITING_SIGNAL 슬롯 updated_at (없으면 None)."""

    try:
        from sqlalchemy import select

        from stock_platform.operation.upbit_full_market.entities import (
            UpbitPositionSlotEntity,
        )
        from stock_platform.operation.upbit_full_market.constants import (
            SLOT_WAITING_SIGNAL,
        )

        row = session.scalar(
            select(UpbitPositionSlotEntity).where(
                UpbitPositionSlotEntity.user_broker_account_id
                == int(user_broker_account_id),
                UpbitPositionSlotEntity.symbol == str(symbol or "").upper(),
                UpbitPositionSlotEntity.status == SLOT_WAITING_SIGNAL,
            )
        )
        if row is None:
            return None
        return _aware(getattr(row, "updated_at", None))
    except Exception:  # noqa: BLE001
        return None


def evaluate_waiting_buy_revalidation_gate(
    session: Session,
    *,
    user_broker_account_id: int,
    symbol: str,
    order_source: str | None = None,
    broker_code: str | None = None,
    side: str | None = None,
    is_risk_reducing: bool = False,
    waiting_updated_at: datetime | None = None,
    skip_if_not_waiting: bool = True,
) -> dict[str, Any]:
    """REAL BUY persist / begin_entry 직전 WAITING 재검증.

    - SELL / risk-reducing: 통과
    - UPBIT AUTO BUY만 적용
    - Exit Monitor RUNNING + Feed fresh 필수 (신규 BUY 우선순위)
    - restore-epoch: outage 이전·중 WAITING은 STALE_PRE_RESTORE_WAITING
    """

    side_u = str(side or "BUY").upper()
    if side_u != "BUY" or bool(is_risk_reducing):
        return {"allowed": True, "reason": None, "skipped": "NOT_BUY"}

    broker_u = str(broker_code or "").upper()
    if broker_u and broker_u != "UPBIT":
        return {"allowed": True, "reason": None, "skipped": "NOT_UPBIT"}

    source_u = str(order_source or "MANUAL").upper()
    if source_u == "MANUAL":
        return {"allowed": True, "reason": None, "skipped": "NOT_AUTO"}
    # AUTO / STRATEGY / RUNTIME / SIGNAL / REALTIME_SIGNAL 등 자동 경로
    if source_u not in {
        "AUTO",
        "STRATEGY",
        "RUNTIME",
        "SIGNAL",
        "REALTIME_SIGNAL",
    }:
        return {"allowed": True, "reason": None, "skipped": "NOT_AUTO"}

    uba_id = int(user_broker_account_id)
    sym = str(symbol or "").strip().upper()
    detail: dict[str, Any] = {
        "user_broker_account_id": uba_id,
        "symbol": sym,
        "order_source": source_u,
    }

    waiting_at = _aware(waiting_updated_at)
    if waiting_at is None and sym:
        waiting_at = load_waiting_slot_updated_at(
            session, user_broker_account_id=uba_id, symbol=sym
        )
    detail["waiting_updated_at"] = (
        waiting_at.isoformat() if waiting_at else None
    )

    # 1) Exit Monitor
    exit_ok, exit_st = _exit_monitor_running()
    detail["exit_monitor"] = {
        "running": exit_ok,
        "status": exit_st.get("status"),
    }
    if not exit_ok:
        return {
            "allowed": False,
            "reason": REASON_EXIT_MONITOR_NOT_RUNNING,
            "detail": detail,
        }

    # 2) Feed REAL_FRESH
    feed_ok, feed_st = _feed_real_fresh(session, uba_id)
    detail["market_feed"] = feed_st
    if not feed_ok:
        return {
            "allowed": False,
            "reason": REASON_MARKET_FEED_NOT_FRESH,
            "detail": detail,
        }

    # 3) Restore epoch — WAITING_SIGNAL 에만 적용.
    # ENTRY_PENDING 등(waiting_at=None)에서 restored_at 만으로
    # STALE_PRE_RESTORE_WAITING 을 강제하면 begin_entry 성공 후
    # persist 가 100% 차단된다 (2026-08-27 20:39+ no-trade root).
    from stock_platform.trading.upbit_execution_restore_epoch import (
        upbit_execution_restore_epoch,
    )

    epoch = upbit_execution_restore_epoch.snapshot()
    detail["restore_epoch"] = epoch
    if waiting_at is None and skip_if_not_waiting:
        detail["restore_epoch_skipped"] = "NOT_WAITING_SLOT"
        return {"allowed": True, "reason": None, "detail": detail}

    if upbit_execution_restore_epoch.is_pre_or_during_outage_waiting(
        waiting_at
    ):
        detail["classification"] = "STALE_PRE_RESTORE_WAITING"
        return {
            "allowed": False,
            "reason": REASON_STALE_PRE_RESTORE_WAITING,
            "detail": detail,
        }

    return {"allowed": True, "reason": None, "detail": detail}
