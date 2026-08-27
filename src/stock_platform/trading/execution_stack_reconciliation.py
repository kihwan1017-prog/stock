"""Canonical execution stack desired-state + reconciliation.

LIVE/ARM/Activation/unattended lease가 유효할 때 desired execution state는
Runtime/Runner/Worker/Exit/Scanner/Feed 모두 RUNNING(REAL_FRESH)이다.

복구 판정·watchdog·startup은 이 모듈만 재사용한다 (중복 restore 로직 금지).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from stock_platform.broker.live_transition_service import LiveTradingTransitionService
from stock_platform.trading.account_models import UserBrokerAccount
from stock_platform.trading.autotrading_health_service import (
    build_trading_health_snapshot,
)
from stock_platform.trading.autotrading_health_slo import (
    AutotradingHealthSlo,
    load_autotrading_health_slo,
)
from stock_platform.trading.live_session_expiry import aware_utc
from stock_platform.trading.live_unattended_authorization_service import (
    STATUS_ACTIVE,
    LiveUnattendedAuthorizationService,
)

# Feed — health SoT와 동일
_FEED_OK = frozenset({"REAL_FRESH", "FRESH", "CONNECTED", "HEALTHY", "OK"})
_STACK_COMPONENTS = ("runtime", "runner", "worker", "exit_monitor", "scanner", "feed")


def evaluate_control_plane_desired(
    session: Session,
    *,
    user_broker_account_id: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    """LIVE/ARM/Activation/unattended lease — desired RUNNING 전제."""

    now = now or datetime.now(timezone.utc)
    uba_id = int(user_broker_account_id)
    uba = session.get(UserBrokerAccount, uba_id)
    if uba is None:
        return {
            "ok": False,
            "reason": "UBA_NOT_FOUND",
            "live": "OFF",
            "arm": "OFF",
            "activation": "INACTIVE",
            "lease": "MISSING",
        }

    live_on = bool(getattr(uba, "live_order_enabled", False))
    arm_exp = aware_utc(getattr(uba, "arm_expires_at", None))
    arm_on = bool(getattr(uba, "live_armed", False)) and (
        arm_exp is None or arm_exp > now
    )
    act = LiveTradingTransitionService(session).peek_active(
        broker_code=str(uba.broker_code or "").upper(),
        user_broker_account_id=uba_id,
    )
    activation_active = act is not None
    lease = LiveUnattendedAuthorizationService(session).get_active(uba_id)
    lease_active = (
        lease is not None
        and str(lease.status_code or "").upper() == STATUS_ACTIVE
    )

    desired_running = (
        live_on and arm_on and activation_active and lease_active
    )
    return {
        "ok": True,
        "broker": str(uba.broker_code or "").upper(),
        "live": "ON" if live_on else "OFF",
        "arm": "ON" if arm_on else "OFF",
        "activation": "ACTIVE" if activation_active else "INACTIVE",
        "lease": "ACTIVE" if lease_active else "MISSING",
        "desired_execution_running": desired_running,
    }


def evaluate_desired_execution_state(
    session: Session,
    *,
    user_broker_account_id: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Canonical desired component map."""

    ctrl = evaluate_control_plane_desired(
        session, user_broker_account_id=user_broker_account_id, now=now
    )
    if not ctrl.get("desired_execution_running"):
        return {
            **ctrl,
            "components": {k: "STOPPED" for k in _STACK_COMPONENTS},
            "reason": "CONTROL_PLANE_NOT_READY",
        }
    return {
        **ctrl,
        "components": {k: "RUNNING" for k in _STACK_COMPONENTS},
        "feed_desired": "REAL_FRESH",
        "reason": "LIVE_ARM_ACTIVATION_LEASE_ACTIVE",
    }


def execution_stack_needs_restore(
    session: Session,
    *,
    user_broker_account_id: int,
    snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """desired RUNNING vs actual mismatch — FULL/PARTIAL stack down 모두 포함."""

    desired = evaluate_desired_execution_state(
        session, user_broker_account_id=user_broker_account_id
    )
    snap = snapshot or build_trading_health_snapshot(
        session, user_broker_account_id=user_broker_account_id
    )
    actual = snap.get("components") or {}
    if not desired.get("desired_execution_running"):
        return {
            "needs_restore": False,
            "reason": desired.get("reason"),
            "desired": desired,
            "actual": actual,
            "down_components": [],
            "restore_kind": None,
        }

    down: list[str] = []
    for key in _STACK_COMPONENTS:
        want = "RUNNING" if key != "feed" else "REAL_FRESH"
        got = str(actual.get(key) or "STOPPED").upper()
        if key == "feed":
            if got not in _FEED_OK:
                down.append(key)
        elif got != want:
            down.append(key)

    all_core_down = all(
        str(actual.get(k) or "STOPPED").upper() != "RUNNING"
        for k in ("runtime", "runner", "worker", "exit_monitor")
    )
    restore_kind: str | None = None
    if down:
        restore_kind = (
            "FULL_EXECUTION_STACK_DOWN"
            if all_core_down and len(down) >= 4
            else "PARTIAL_RESTORE"
        )

    return {
        "needs_restore": bool(down),
        "reason": restore_kind or "ALREADY_OK",
        "restore_kind": restore_kind,
        "desired": desired,
        "actual": actual,
        "down_components": down,
        "health_state": snap.get("health_state"),
        "partial_restore": snap.get("partial_restore"),
    }


def verify_stack_restored(
    session: Session,
    *,
    user_broker_account_id: int,
    slo: AutotradingHealthSlo | None = None,
    now: datetime | None = None,
    snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """복구 성공 — status + heartbeat freshness (running flag만으로 판정 금지)."""

    slo = slo or load_autotrading_health_slo()
    now = now or datetime.now(timezone.utc)
    snap = snapshot or build_trading_health_snapshot(
        session, user_broker_account_id=user_broker_account_id
    )
    comps = snap.get("components") or {}
    hb = snap.get("heartbeats") or {}

    verified: dict[str, bool] = {}
    stale: dict[str, float | None] = {}
    missing: list[str] = []

    def _fresh(age: Any, max_age: float) -> bool:
        if age is None:
            return True
        try:
            return float(age) <= max_age
        except (TypeError, ValueError):
            return False

    # Runtime
    rt_ok = str(comps.get("runtime") or "").upper() == "RUNNING"
    rt_age = hb.get("runtime_heartbeat_age_seconds")
    if rt_ok and not _fresh(rt_age, slo.runner_heartbeat_max_age_seconds * 3):
        if rt_age is not None:
            rt_ok = False
            stale["runtime"] = rt_age
    verified["runtime"] = rt_ok
    if not rt_ok:
        missing.append("runtime")

    # Runner
    rn_ok = str(comps.get("runner") or "").upper() == "RUNNING"
    rn_age = hb.get("runner_heartbeat_age_seconds")
    if rn_ok and not _fresh(rn_age, slo.runner_heartbeat_max_age_seconds):
        if rn_age is not None:
            rn_ok = False
            stale["runner"] = rn_age
    verified["runner"] = rn_ok
    if not rn_ok:
        missing.append("runner")

    # Worker
    wk_ok = str(comps.get("worker") or "").upper() == "RUNNING"
    wk_age = hb.get("worker_heartbeat_age_seconds")
    if wk_ok and not _fresh(wk_age, slo.worker_heartbeat_max_age_seconds):
        if wk_age is not None:
            wk_ok = False
            stale["worker"] = wk_age
    verified["worker"] = wk_ok
    if not wk_ok:
        missing.append("worker")

    # Exit
    ex_ok = str(comps.get("exit_monitor") or "").upper() == "RUNNING"
    ex_age = hb.get("exit_heartbeat_age_seconds")
    if ex_ok and not _fresh(ex_age, slo.exit_monitor_heartbeat_max_age_seconds):
        if ex_age is not None:
            ex_ok = False
            stale["exit_monitor"] = ex_age
    verified["exit_monitor"] = ex_ok
    if not ex_ok:
        missing.append("exit_monitor")

    # Scanner — RUNNING + optional cycle age
    sc_ok = str(comps.get("scanner") or "").upper() == "RUNNING"
    sc_age = hb.get("scanner_last_success_at")
    if sc_ok:
        from stock_platform.trading.autotrading_health_service import _age_seconds, _parse_iso

        sc_sec = _age_seconds(_parse_iso(sc_age), now=now) if sc_age else None
        if sc_sec is not None and sc_sec > slo.scanner_max_age_seconds:
            sc_ok = False
            stale["scanner"] = sc_sec
    verified["scanner"] = sc_ok
    if not sc_ok:
        missing.append("scanner")

    # Feed
    feed_st = str(comps.get("feed") or "").upper()
    feed_ok = feed_st in _FEED_OK
    feed_age = hb.get("feed_age_seconds")
    if feed_ok and not _fresh(feed_age, slo.feed_max_age_seconds):
        if feed_age is not None:
            feed_ok = False
            stale["feed"] = feed_age
    verified["feed"] = feed_ok
    if not feed_ok:
        missing.append("feed")

    restore_succeeded = all(verified.values())
    return {
        "restore_succeeded": restore_succeeded,
        "verified": verified,
        "missing_components": missing,
        "stale_heartbeats": stale,
        "components": comps,
        "heartbeats": hb,
        "checked_at": now.isoformat(),
    }


async def reconcile_desired_execution_state(
    session: Session,
    *,
    user_broker_account_id: int,
    actor: str = "EXECUTION_STACK_RECONCILE",
    broker: str | None = None,
) -> dict[str, Any]:
    """Official stack restore path — L1(feed/scanner) → L2(stack) → heartbeat verify."""

    uba_id = int(user_broker_account_id)
    need = execution_stack_needs_restore(session, user_broker_account_id=uba_id)
    outcome: dict[str, Any] = {
        "user_broker_account_id": uba_id,
        "needs_restore": need.get("needs_restore"),
        "restore_kind": need.get("restore_kind"),
        "down_components": need.get("down_components"),
        "actions": [],
    }
    if not need.get("needs_restore"):
        verify = verify_stack_restored(session, user_broker_account_id=uba_id)
        outcome["restore_succeeded"] = verify.get("restore_succeeded")
        outcome["verify"] = verify
        outcome["reason"] = "ALREADY_OK"
        return outcome

    market = (broker or (need.get("desired") or {}).get("broker") or "UPBIT").upper()
    outcome["market"] = market

    # L1 — feed / scanner (순서: feed → scanner)
    if market == "UPBIT":
        actual = need.get("actual") or {}
        feed_st = str(actual.get("feed") or "")
        from stock_platform.trading.autotrading_reliability_watchdog import (
            _l1_feed_reconnect,
            _l1_scanner_restore,
        )

        if feed_st not in _FEED_OK:
            l1f = await _l1_feed_reconnect(session, uba_id=uba_id, actor=actor)
            outcome["actions"].append("L1_FEED")
            outcome["l1_feed"] = l1f

        scanner_st = str(actual.get("scanner") or "STOPPED")
        if scanner_st != "RUNNING":
            l1s = _l1_scanner_restore(actor=actor)
            outcome["actions"].append("L1_SCANNER")
            outcome["l1_scanner"] = l1s

    # L2 — canonical stack restore (operator 경로와 동일)
    if market == "UPBIT":
        from stock_platform.trading.upbit_unattended_stack_restore import (
            restore_upbit_trading_stack,
        )

        l2 = await restore_upbit_trading_stack(
            session,
            user_broker_account_id=uba_id,
            actor=actor,
        )
    elif market == "KIWOOM":
        from stock_platform.trading.kiwoom_unattended_stack_restore import (
            restore_kiwoom_trading_stack,
        )

        l2 = await restore_kiwoom_trading_stack(
            session,
            user_broker_account_id=uba_id,
            actor=actor,
        )
    else:
        l2 = {"restored": False, "reason": "UNSUPPORTED_MARKET"}

    outcome["actions"].append("L2_STACK")
    outcome["l2_restore"] = l2

    # heartbeat 기반 최종 판정 (return success만 믿지 않음)
    verify = verify_stack_restored(session, user_broker_account_id=uba_id)
    outcome["verify"] = verify
    outcome["restore_succeeded"] = bool(verify.get("restore_succeeded"))
    outcome["restore_attempted"] = True
    if not outcome["restore_succeeded"]:
        outcome["missing_components"] = verify.get("missing_components")
        outcome["stale_heartbeats"] = verify.get("stale_heartbeats")

    return outcome


async def reconcile_all_active_unattended_leases(
    *,
    actor: str = "STARTUP_EXECUTION_STACK_RECONCILE",
) -> dict[str, Any]:
    """Startup 완료 후 ACTIVE lease UBA 전수 reconciliation."""

    from sqlalchemy import select

    from stock_platform.database.session import get_session_factory
    from stock_platform.trading.live_unattended_entities import (
        LiveUnattendedAuthorizationEntity,
    )

    sf = get_session_factory()
    session = sf()
    results: list[dict[str, Any]] = []
    try:
        rows = list(
            session.scalars(
                select(LiveUnattendedAuthorizationEntity).where(
                    LiveUnattendedAuthorizationEntity.enabled.is_(True),
                    LiveUnattendedAuthorizationEntity.status_code == STATUS_ACTIVE,
                )
            )
        )
        for row in rows:
            uba_id = int(row.user_broker_account_id)
            uba = session.get(UserBrokerAccount, uba_id)
            if uba is None:
                continue
            broker = str(uba.broker_code or "").upper()
            if broker not in {"UPBIT", "KIWOOM"}:
                continue
            res = await reconcile_desired_execution_state(
                session,
                user_broker_account_id=uba_id,
                actor=actor,
                broker=broker,
            )
            results.append(res)
        session.commit()
        return {"ok": True, "count": len(results), "results": results}
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        return {
            "ok": False,
            "error": type(exc).__name__,
            "message": str(exc)[:300],
            "results": results,
        }
    finally:
        session.close()
