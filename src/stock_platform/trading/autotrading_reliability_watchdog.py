"""AutoTradingReliabilityWatchdog — 30s health check + safe L1/L2 self-heal."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any

from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory
from stock_platform.trading.autotrading_health_service import (
    HEALTH_BROKEN,
    HEALTH_READY,
    build_trading_health_snapshot,
)

logger = logging.getLogger(__name__)

# market:uba_id -> last health state (edge-trigger telegram)
_last_health_state: dict[str, str] = {}
# market:uba_id -> last starvation alert escalation (edge-trigger)
_last_starvation_escalation: dict[str, str] = {}
# market:uba_id -> restore lock
_restore_locks: dict[str, asyncio.Lock] = {}
# market:uba_id -> backoff state
_restore_backoff: dict[str, dict[str, Any]] = {}
# forensic — component transitions
_stack_forensic: dict[str, list[dict[str, Any]]] = {}

BACKOFF_SCHEDULE_SEC = (30.0, 60.0, 300.0, 600.0)
MAX_RESTORE_ATTEMPTS_PER_WINDOW = 8


def _market_key(market: str, uba_id: int) -> str:
    return f"{market.upper()}:{int(uba_id)}"


def _get_lock(key: str) -> asyncio.Lock:
    if key not in _restore_locks:
        _restore_locks[key] = asyncio.Lock()
    return _restore_locks[key]


def record_stack_forensic(
    *,
    market: str,
    uba_id: int,
    component: str,
    event: str,
    reason: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    key = _market_key(market, uba_id)
    entry = {
        "at": datetime.now(timezone.utc).isoformat(),
        "component": component,
        "event": event,
        "reason": reason,
        "detail": detail or {},
    }
    buf = _stack_forensic.setdefault(key, [])
    buf.append(entry)
    if len(buf) > 200:
        del buf[:-200]


def get_stack_forensic(*, market: str, uba_id: int) -> list[dict[str, Any]]:
    return list(_stack_forensic.get(_market_key(market, uba_id), []))


def first_stack_failure(*, market: str, uba_id: int) -> dict[str, Any] | None:
    events = [
        e
        for e in get_stack_forensic(market=market, uba_id=uba_id)
        if e.get("event") in {"STOP", "DEGRADED", "PARTIAL_RESTORE"}
    ]
    return events[0] if events else None


def _backoff_allowed(key: str) -> tuple[bool, float]:
    st = _restore_backoff.get(key) or {}
    attempts = int(st.get("attempts") or 0)
    last_at = float(st.get("last_attempt_mono") or 0.0)
    if attempts <= 0:
        return True, 0.0
    idx = min(attempts - 1, len(BACKOFF_SCHEDULE_SEC) - 1)
    wait = BACKOFF_SCHEDULE_SEC[idx]
    elapsed = time.monotonic() - last_at
    if elapsed < wait:
        return False, wait - elapsed
    return True, 0.0


def _record_restore_attempt(key: str, *, success: bool) -> None:
    st = _restore_backoff.setdefault(key, {"attempts": 0, "last_attempt_mono": 0.0})
    if success:
        st["attempts"] = 0
        st["last_success_mono"] = time.monotonic()
    else:
        st["attempts"] = min(
            MAX_RESTORE_ATTEMPTS_PER_WINDOW, int(st.get("attempts") or 0) + 1
        )
    st["last_attempt_mono"] = time.monotonic()


def _emit_reliability_telegram(
    *,
    market: str,
    uba_id: int,
    event_type: str,
    title: str,
    message: str,
    detail: dict[str, Any],
) -> None:
    try:
        from stock_platform.order.live_safety_audit import emit_live_order_telegram

        emit_live_order_telegram(
            event_type=event_type,
            title=title,
            message=message,
            detail={
                **detail,
                "broker_code": market,
                "user_broker_account_id": uba_id,
            },
        )
    except Exception:  # noqa: BLE001
        logger.exception("reliability_telegram_failed", extra={"market": market})


def _handle_health_transition(
    *,
    market: str,
    uba_id: int,
    prev: str | None,
    current: str,
    snapshot: dict[str, Any],
) -> None:
    key = _market_key(market, uba_id)
    if prev == current:
        return

    if current == HEALTH_BROKEN and prev != HEALTH_BROKEN:
        comps = snapshot.get("components") or {}
        down = [
            k
            for k, v in comps.items()
            if str(v).upper() != "RUNNING" and k != "scanner"
        ]
        _emit_reliability_telegram(
            market=market,
            uba_id=uba_id,
            event_type="AUTOTRADING_RELIABILITY_BROKEN",
            title=f"[{market}] 자동매매 실행 장애 감지",
            message=(
                f"상태: {current}. 문제: {', '.join(down) or 'stack'}. "
                "자동복구 시도 중."
            ),
            detail={
                "health_state": current,
                "partial_restore": snapshot.get("partial_restore"),
                "components": comps,
                "blockers": snapshot.get("blockers"),
            },
        )
        record_stack_forensic(
            market=market,
            uba_id=uba_id,
            component="health",
            event="BROKEN",
            reason=str(snapshot.get("health_reasons")),
        )
    elif current == HEALTH_READY and prev == HEALTH_BROKEN:
        _emit_reliability_telegram(
            market=market,
            uba_id=uba_id,
            event_type="AUTOTRADING_RELIABILITY_RECOVERED",
            title=f"[{market}] 자동매매 자동 복구 완료",
            message="Runtime/Worker/Exit/Feed 정상 복구.",
            detail={"health_state": current, "components": snapshot.get("components")},
        )


def _handle_starvation_transition(
    *,
    market: str,
    uba_id: int,
    snapshot: dict[str, Any],
) -> None:
    """WAITING_SLOT_STARVATION — BROKEN threshold 1회 Telegram (반복 금지)."""

    key = _market_key(market, uba_id)
    starv = snapshot.get("waiting_starvation") or {}
    if not isinstance(starv, dict):
        return
    esc = str(starv.get("escalation") or "NONE")
    prev = _last_starvation_escalation.get(key, "NONE")
    _last_starvation_escalation[key] = esc
    if esc != "BROKEN" or prev == "BROKEN":
        return
    if market != "UPBIT":
        return
    wc = int(snapshot.get("waiting_count") or 0)
    oldest = starv.get("oldest_waiting_age_seconds")
    _emit_reliability_telegram(
        market=market,
        uba_id=uba_id,
        event_type="UPBIT_WAITING_SLOT_STARVATION",
        title="🟡 [업비트] 매수 대기 슬롯 정체",
        message=(
            f"현재: {wc}/{wc} 슬롯이 대기 상태입니다.\n"
            "유효 매수신호: 0\n"
            "자동 조치: 대기 후보를 재검증하고 있습니다."
        ),
        detail={
            "waiting_count": wc,
            "oldest_waiting_age_seconds": oldest,
            "no_trade_classification": snapshot.get("no_trade_classification"),
        },
    )


def _l1_waiting_self_heal(
    session: Any, *, uba_id: int, actor: str
) -> dict[str, Any]:
    """Starvation self-heal — revalidation/release only (REAL order 금지)."""

    try:
        from stock_platform.operation.upbit_full_market.portfolio_entry_signal import (
            portfolio_entry_telemetry,
        )
        from stock_platform.operation.upbit_full_market.waiting_lifecycle import (
            revalidate_waiting_slots,
        )

        telem = portfolio_entry_telemetry.snapshot(uba_id) or {}
        if not isinstance(telem, dict):
            telem = {}
        return revalidate_waiting_slots(
            session,
            user_broker_account_id=uba_id,
            telemetry_by_symbol=telem,
            actor=actor,
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": type(exc).__name__, "message": str(exc)[:200]}


async def _l1_feed_reconnect(
    session: Any, *, uba_id: int, actor: str
) -> dict[str, Any]:
    try:
        from stock_platform.realtime.upbit_quote_feed_restore import (
            ensure_upbit_quote_feed_from_hub,
        )

        result = await ensure_upbit_quote_feed_from_hub(
            source=f"WATCHDOG:{actor}", session=session
        )
        from stock_platform.realtime.market_data_hub import (
            get_realtime_market_data_hub,
        )

        hub = get_realtime_market_data_hub()
        if not bool((hub.status() or {}).get("dispatch_running")):
            await hub.start_dispatch()
        return {"ok": True, "feed": result}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": type(exc).__name__, "message": str(exc)[:200]}


def _l1_scanner_restore(*, actor: str) -> dict[str, Any]:
    try:
        from stock_platform.operation.upbit_opportunity_scanner.scheduler import (
            upbit_opportunity_scanner_scheduler,
        )

        st = upbit_opportunity_scanner_scheduler.status()
        if bool(st.get("started")):
            return {"ok": True, "reason": "ALREADY_STARTED", "idempotent": True}
        return upbit_opportunity_scanner_scheduler.start()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": type(exc).__name__}


async def _l2_stack_restore(
    session: Any, *, uba_id: int, market: str, actor: str
) -> dict[str, Any]:
    if market == "UPBIT":
        from stock_platform.trading.upbit_unattended_stack_restore import (
            restore_upbit_trading_stack,
        )

        return await restore_upbit_trading_stack(
            session,
            user_broker_account_id=uba_id,
            actor=actor,
        )
    if market == "KIWOOM":
        from stock_platform.trading.kiwoom_unattended_stack_restore import (
            restore_kiwoom_trading_stack,
        )

        return await restore_kiwoom_trading_stack(
            session,
            user_broker_account_id=uba_id,
            actor=actor,
        )
    return {"restored": False, "reason": "UNSUPPORTED_MARKET"}


async def reconcile_market_health(
    *,
    market: str,
    uba_id: int,
    actor: str = "AUTOTRADING_RELIABILITY_WATCHDOG",
) -> dict[str, Any]:
    """단일 UBA 1 tick — 관측 + L1/L2 복구."""

    key = _market_key(market, uba_id)
    factory = get_session_factory()
    session = factory()
    outcome: dict[str, Any] = {
        "market": market,
        "user_broker_account_id": uba_id,
        "restore_trigger": None,
        "restore_attempted": False,
        "restore_succeeded": False,
    }
    try:
        snap = build_trading_health_snapshot(
            session, user_broker_account_id=uba_id
        )
        outcome["snapshot"] = {
            "health_state": snap.get("health_state"),
            "partial_restore": snap.get("partial_restore"),
            "components": snap.get("components"),
            "no_trade_classification": snap.get("no_trade_classification"),
            "first_zero_stage": snap.get("first_zero_stage"),
        }

        prev = _last_health_state.get(key)
        current = str(snap.get("health_state") or "UNKNOWN")
        _handle_health_transition(
            market=market,
            uba_id=uba_id,
            prev=prev,
            current=current,
            snapshot=snap,
        )
        _handle_starvation_transition(
            market=market, uba_id=uba_id, snapshot=snap
        )
        _last_health_state[key] = current

        if snap.get("partial_restore"):
            record_stack_forensic(
                market=market,
                uba_id=uba_id,
                component="stack",
                event="PARTIAL_RESTORE",
                reason=str(snap.get("health_reasons")),
            )

        allowed, wait_sec = _backoff_allowed(key)
        if not allowed:
            outcome["restore_skipped"] = "BACKOFF"
            outcome["backoff_wait_seconds"] = round(wait_sec, 1)
            return outcome

        lock = _get_lock(key)
        if lock.locked():
            outcome["restore_skipped"] = "RESTORE_IN_PROGRESS"
            return outcome

        async with lock:
            actions: list[str] = []
            # LEVEL 1 — feed / scanner / waiting self-heal (UPBIT only)
            if market == "UPBIT":
                starv = snap.get("waiting_starvation") or {}
                if isinstance(starv, dict) and starv.get("waiting_slot_starvation"):
                    l1w = _l1_waiting_self_heal(
                        session, uba_id=uba_id, actor=actor
                    )
                    actions.append("L1_WAITING_REVALIDATE")
                    outcome["l1_waiting"] = l1w
                    if int(l1w.get("released") or 0) > 0:
                        session.commit()

                feed_st = str((snap.get("components") or {}).get("feed") or "")
                if feed_st not in {"REAL_FRESH", "FRESH", "CONNECTED", "HEALTHY", "OK"}:
                    l1f = await _l1_feed_reconnect(session, uba_id=uba_id, actor=actor)
                    actions.append("L1_FEED")
                    outcome["l1_feed"] = l1f

                scanner_st = str(
                    (snap.get("components") or {}).get("scanner") or "STOPPED"
                )
                if scanner_st != "RUNNING":
                    l1s = _l1_scanner_restore(actor=actor)
                    actions.append("L1_SCANNER")
                    outcome["l1_scanner"] = l1s

            # LEVEL 2 — partial restore or broken stack (LIVE/ARM valid only)
            need_l2 = bool(snap.get("partial_restore")) or (
                current == HEALTH_BROKEN
                and snap.get("live") == "ON"
                and snap.get("arm") == "ON"
                and snap.get("activation") == "ACTIVE"
            )
            if need_l2 and (market != "KIWOOM" or snap.get("kiwoom_stack_slo_active")):
                outcome["restore_attempted"] = True
                outcome["restore_trigger"] = "WATCHDOG"
                started = time.monotonic()
                l2 = await _l2_stack_restore(
                    session, uba_id=uba_id, market=market, actor=actor
                )
                outcome["l2_restore"] = l2
                outcome["restore_duration_seconds"] = round(
                    time.monotonic() - started, 2
                )
                restored = bool(l2.get("restored"))
                outcome["restore_succeeded"] = restored
                _record_restore_attempt(key, success=restored)
                actions.append("L2_STACK")
                session.commit()

                if not restored:
                    missing = (l2.get("detail") or {}).get("missing_components")
                    if missing:
                        _emit_reliability_telegram(
                            market=market,
                            uba_id=uba_id,
                            event_type="AUTOTRADING_RELIABILITY_RESTORE_FAILED",
                            title=f"[{market}] 자동매매 자동 복구 실패",
                            message="관리자 확인 필요.",
                            detail={"missing": missing, "l2": l2},
                        )
            else:
                _record_restore_attempt(key, success=True)

            outcome["actions"] = actions

            # post-restore snapshot
            snap2 = build_trading_health_snapshot(
                session, user_broker_account_id=uba_id
            )
            outcome["post_snapshot"] = {
                "health_state": snap2.get("health_state"),
                "auto_trading_ready": snap2.get("auto_trading_ready"),
                "components": snap2.get("components"),
            }
            return outcome
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        _record_restore_attempt(key, success=False)
        logger.exception("watchdog_tick_failed", extra={"market": market, "uba": uba_id})
        outcome["error"] = type(exc).__name__
        outcome["message"] = str(exc)[:300]
        return outcome
    finally:
        session.close()


def _discover_watch_targets(session: Any) -> list[tuple[str, int]]:
    """ACTIVE unattended lease UBA만 watchdog 대상."""

    from sqlalchemy import select

    from stock_platform.trading.account_models import UserBrokerAccount
    from stock_platform.trading.live_unattended_authorization_service import (
        STATUS_ACTIVE,
        LiveUnattendedAuthorizationService,
    )
    from stock_platform.trading.live_unattended_entities import (
        LiveUnattendedAuthorizationEntity,
    )

    targets: list[tuple[str, int]] = []
    rows = list(
        session.scalars(
            select(LiveUnattendedAuthorizationEntity).where(
                LiveUnattendedAuthorizationEntity.enabled.is_(True),
                LiveUnattendedAuthorizationEntity.status_code == STATUS_ACTIVE,
            )
        )
    )
    for row in rows:
        uba = session.get(UserBrokerAccount, int(row.user_broker_account_id))
        if uba is None:
            continue
        broker = str(uba.broker_code or "").upper()
        if broker in {"UPBIT", "KIWOOM"}:
            targets.append((broker, int(uba.user_broker_account_id)))
    return targets


async def run_watchdog_cycle(*, actor: str = "AUTOTRADING_RELIABILITY_WATCHDOG") -> dict[str, Any]:
    factory = get_session_factory()
    session = factory()
    results: list[dict[str, Any]] = []
    try:
        targets = _discover_watch_targets(session)
    finally:
        session.close()

    for market, uba_id in targets:
        res = await reconcile_market_health(
            market=market, uba_id=uba_id, actor=actor
        )
        results.append(res)
    return {
        "ok": True,
        "count": len(results),
        "results": results,
        "at": datetime.now(timezone.utc).isoformat(),
    }


class AutoTradingReliabilityWatchdog:
    """30s asyncio loop — live_session_expiry_runtime 패턴."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stopping: asyncio.Event | None = None
        self._last_run_at: datetime | None = None
        self._last_summary: dict[str, Any] | None = None
        self._last_error: str | None = None
        self._running = False

    def start(self) -> dict[str, Any]:
        if self._task is not None and not self._task.done():
            return {"started": False, "reason": "ALREADY_RUNNING", **self.status()}
        self._stopping = asyncio.Event()
        self._task = asyncio.create_task(self._run(), name="autotrading-reliability-watchdog")
        self._running = True
        return {"started": True, **self.status()}

    async def shutdown(self) -> None:
        if self._stopping is not None:
            self._stopping.set()
        task = self._task
        if task is not None and not task.done():
            try:
                await asyncio.wait_for(task, timeout=10.0)
            except (TimeoutError, asyncio.CancelledError):
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
        self._task = None
        self._stopping = None
        self._running = False

    async def run_once(self) -> dict[str, Any]:
        summary = await run_watchdog_cycle()
        self._last_run_at = datetime.now(timezone.utc)
        self._last_summary = summary
        self._last_error = None
        return summary

    async def _run(self) -> None:
        settings = get_settings()
        interval = float(
            getattr(settings, "autotrading_reliability_watchdog_interval_seconds", 30.0)
            or 30.0
        )
        interval = max(15.0, min(120.0, interval))

        # startup immediate reconcile (current PARTIAL_RESTORE)
        try:
            await self.run_once()
        except Exception as exc:  # noqa: BLE001
            self._last_error = f"{type(exc).__name__}:{exc}"[:300]
            logger.exception("watchdog_startup_tick_failed")

        while self._stopping is not None and not self._stopping.is_set():
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=interval)
                break
            except TimeoutError:
                pass
            if self._stopping is None or self._stopping.is_set():
                break
            try:
                await self.run_once()
            except Exception as exc:  # noqa: BLE001
                self._last_error = f"{type(exc).__name__}:{exc}"[:300]
                logger.exception("watchdog_tick_failed")

    def status(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "last_run_at": (
                self._last_run_at.isoformat() if self._last_run_at else None
            ),
            "last_error": self._last_error,
            "last_summary": self._last_summary,
        }


autotrading_reliability_watchdog = AutoTradingReliabilityWatchdog()
