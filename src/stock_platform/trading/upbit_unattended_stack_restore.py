"""24H unattended lease 복구 후 UPBIT 운영 스택(Runtime/Worker/Exit) 재기동.

LIVE/ARM/Activation은 LiveUnattendedAuthorizationService.restore_from_active_lease
가 담당한다. 이 모듈은 그 이후의 운영 컴포넌트만 복구한다.

정책:
- Scheduler 강제 RUN 없음
- REAL 주문 강제 생성 없음
- Gate FAIL 시 stack start 금지
- Worker/Runtime 중복 start는 idempotent
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.database.session import get_session_factory
from stock_platform.strategy_deployment.runtime_scope import (
    RuntimeLifecycleStatus,
)
from stock_platform.trading.account_models import UserBrokerAccount
from stock_platform.trading.live_unattended_authorization_service import (
    STATUS_ACTIVE,
    LiveUnattendedAuthorizationService,
)
from stock_platform.trading.live_unattended_entities import (
    LiveUnattendedAuthorizationEntity,
)

logger = structlog.get_logger(__name__)


def evaluate_stack_restore_gates(
    session: Session,
    *,
    user_broker_account_id: int,
) -> dict[str, Any]:
    """스택 복구 전용 gate. 전부 PASS일 때만 Worker/Runtime 기동."""

    uba_id = int(user_broker_account_id)
    blockers: list[str] = []
    checks: dict[str, Any] = {}

    uba = session.get(UserBrokerAccount, uba_id)
    if uba is None:
        return {"ok": False, "blockers": ["UBA_NOT_FOUND"], "checks": checks}
    if str(uba.broker_code or "").upper() != "UPBIT":
        return {
            "ok": False,
            "blockers": ["UBA_BROKER_MISMATCH"],
            "checks": checks,
        }

    # lease ACTIVE
    lease = LiveUnattendedAuthorizationService(session).get_active(uba_id)
    if lease is None or str(lease.status_code or "").upper() != STATUS_ACTIVE:
        blockers.append("NO_ACTIVE_LEASE")
        checks["lease"] = "MISSING"
    else:
        checks["lease"] = "ACTIVE"

    # LIVE/ARM (lease restore 이후여야 함)
    if not bool(getattr(uba, "live_order_enabled", False)):
        blockers.append("LIVE_OFF")
    if not bool(getattr(uba, "live_armed", False)):
        blockers.append("ARM_OFF")

    # 안전 gate 재사용 (Credential/Connection/Recovery/Kill/Conflict 등)
    enable = LiveUnattendedAuthorizationService(session).evaluate_enable_gates(
        uba_id
    )
    checks["enable_gates"] = {
        "ok": enable.get("ok"),
        "blockers": list(enable.get("blockers") or []),
        "execution_env": enable.get("execution_env"),
    }
    # Runtime/Worker 미기동은 지금 복구 대상이므로 제외
    ignored = {
        "RUNTIME_NOT_RUNNING",
        "OUTBOX_WORKER_NOT_RUNNING",
    }
    for code in enable.get("blockers") or []:
        if code in ignored:
            continue
        if code not in blockers:
            blockers.append(str(code))

    # Portfolio enabled
    try:
        from stock_platform.operation.upbit_full_market.service import (
            UpbitFullMarketAssignmentService,
        )

        assignment = UpbitFullMarketAssignmentService(session).status_dict(
            uba_id
        )
        checks["portfolio"] = {
            "portfolio_enabled": bool(assignment.get("portfolio_enabled")),
            "mode": assignment.get("mode"),
            "strategy_id": assignment.get("strategy_id"),
            "deployment_id": assignment.get("deployment_id"),
        }
        if not bool(assignment.get("portfolio_enabled")):
            blockers.append("PORTFOLIO_NOT_ENABLED")
    except Exception:  # noqa: BLE001
        blockers.append("PORTFOLIO_CHECK_FAILED")
        checks["portfolio"] = {"error": True}

    uniq = list(dict.fromkeys(blockers))
    return {"ok": len(uniq) == 0, "blockers": uniq, "checks": checks}


async def restore_upbit_trading_stack(
    session: Session,
    *,
    user_broker_account_id: int,
    actor: str = "SYSTEM_UNATTENDED_STACK_RESTORE",
) -> dict[str, Any]:
    """Gate PASS 시 Worker → Runtime resume → Exit(필요 시) 복구."""

    uba_id = int(user_broker_account_id)
    gates = evaluate_stack_restore_gates(session, user_broker_account_id=uba_id)
    if not gates["ok"]:
        return {
            "restored": False,
            "reason": "STACK_GATES_FAILED",
            "blockers": gates["blockers"],
            "gates": gates,
            "actor": actor,
        }

    detail: dict[str, Any] = {"gates": gates, "actor": actor}
    portfolio = (gates.get("checks") or {}).get("portfolio") or {}
    strategy_id = portfolio.get("strategy_id")

    # 1) Live Outbox Worker
    from stock_platform.order.live_outbox_worker_runtime import (
        live_outbox_worker_runtime,
    )

    worker_before = live_outbox_worker_runtime.status()
    detail["worker_before"] = {
        "enabled": worker_before.get("enabled"),
        "running": worker_before.get("running"),
    }
    if not bool(worker_before.get("enabled")):
        return {
            "restored": False,
            "reason": "LIVE_OUTBOX_WORKER_DISABLED",
            "detail": detail,
        }
    if bool(worker_before.get("running")):
        detail["worker"] = {
            "started": True,
            "reason": "ALREADY_RUNNING",
            "idempotent": True,
        }
    else:
        detail["worker"] = live_outbox_worker_runtime.start()

    # 2) Strategy Runtime resume (UPBIT portfolio strategy만)
    from stock_platform.strategy_deployment.runtime_manager import (
        dynamic_strategy_runtime_manager,
    )
    from stock_platform.trading.upbit_24x7_control import (
        evaluate_runtime_start_gates,
        runtime_status_for_uba,
    )

    if strategy_id is None:
        detail["runtime"] = {
            "resumed": False,
            "reason": "STRATEGY_ID_MISSING",
        }
    else:
        rt_gates = evaluate_runtime_start_gates(
            session,
            user_broker_account_id=uba_id,
            strategy_id=int(strategy_id),
            require_worker_running=True,
        )
        detail["runtime_gates"] = rt_gates
        if not rt_gates.get("ok"):
            detail["runtime"] = {
                "resumed": False,
                "reason": "RUNTIME_GATES_FAILED",
                "blockers": rt_gates.get("blockers"),
            }
        else:
            entries = [
                e
                for e in dynamic_strategy_runtime_manager.list_entries(
                    user_broker_account_id=uba_id,
                    strategy_id=int(strategy_id),
                )
                if str(e.scope.broker_code or "").upper() == "UPBIT"
            ]
            running = [
                e
                for e in entries
                if e.status == RuntimeLifecycleStatus.RUNNING
            ]
            paused = [
                e for e in entries if e.status == RuntimeLifecycleStatus.PAUSED
            ]
            if running:
                detail["runtime"] = {
                    "resumed": True,
                    "reason": "ALREADY_RUNNING",
                    "idempotent": True,
                }
            elif paused:
                entry = paused[0]
                await dynamic_strategy_runtime_manager.resume_runtime(
                    entry.scope.scope_key
                )
                detail["runtime"] = {
                    "resumed": True,
                    "reason": "RESUMED",
                    "scope_key": entry.scope.scope_key,
                }
            else:
                detail["runtime"] = {
                    "resumed": False,
                    "reason": "NO_PAUSED_RUNTIME",
                    "hint": "operator START RUNTIME required if never started",
                }
            detail["runtime_status"] = runtime_status_for_uba(
                user_broker_account_id=uba_id,
                strategy_id=int(strategy_id),
            )
            # resume/already-running 모두 portfolio entry ctx 재부착
            try:
                from stock_platform.operation.upbit_full_market.portfolio_entry_signal import (
                    ensure_portfolio_entry_evaluator_for_uba,
                )

                detail["portfolio_entry_context"] = (
                    ensure_portfolio_entry_evaluator_for_uba(uba_id)
                )
            except Exception as ctx_exc:  # noqa: BLE001
                detail["portfolio_entry_context"] = {
                    "ok": False,
                    "error": type(ctx_exc).__name__,
                }

    # 3) Exit Monitor — STOPPED일 때만 (플래그 변경 없음)
    from stock_platform.trading.upbit_24x7_control import exit_monitor_status

    exit_before = exit_monitor_status()
    detail["exit_before"] = exit_before.get("status")
    if str(exit_before.get("status") or "").upper() == "STOPPED":
        from stock_platform.position.exit_monitor_scheduler import (
            position_exit_monitor_scheduler,
        )

        position_exit_monitor_scheduler.start()
        detail["exit"] = {
            "started": True,
            "status": exit_monitor_status(),
        }
    else:
        detail["exit"] = {
            "started": False,
            "reason": "ALREADY_RUNNING_OR_OK",
            "status": exit_before,
        }

    logger.info(
        "upbit_unattended_stack_restored",
        uba_id=uba_id,
        actor=actor,
        worker_reason=(detail.get("worker") or {}).get("reason"),
        runtime_reason=(detail.get("runtime") or {}).get("reason"),
    )
    return {"restored": True, "detail": detail}


async def restore_all_active_unattended_upbit_leases(
    *,
    actor: str = "SYSTEM_UNATTENDED_STARTUP_RESTORE",
) -> dict[str, Any]:
    """Startup 등에서 ACTIVE UPBIT lease 전수: LIVE/ARM 복구 → stack 복구."""

    sf = get_session_factory()
    session = sf()
    results: list[dict[str, Any]] = []
    try:
        rows = list(
            session.scalars(
                select(LiveUnattendedAuthorizationEntity).where(
                    LiveUnattendedAuthorizationEntity.enabled.is_(True),
                    LiveUnattendedAuthorizationEntity.status_code
                    == STATUS_ACTIVE,
                )
            )
        )
        svc = LiveUnattendedAuthorizationService(session)
        for row in rows:
            uba_id = int(row.user_broker_account_id)
            uba = session.get(UserBrokerAccount, uba_id)
            if uba is None or str(uba.broker_code or "").upper() != "UPBIT":
                results.append(
                    {
                        "user_broker_account_id": uba_id,
                        "skipped": True,
                        "reason": "NOT_UPBIT",
                    }
                )
                continue
            lease_restore = svc.restore_from_active_lease(
                uba_id, actor=actor, restore_stack=False
            )
            stack: dict[str, Any] = {"restored": False, "reason": "SKIPPED"}
            if lease_restore.get("restored") or bool(
                getattr(uba, "live_order_enabled", False)
            ):
                # lease 이미 LIVE였어도 stack은 startup_forced_idle일 수 있음
                session.flush()
                uba = session.get(UserBrokerAccount, uba_id)
                if uba is not None and bool(uba.live_order_enabled):
                    stack = await restore_upbit_trading_stack(
                        session,
                        user_broker_account_id=uba_id,
                        actor=f"{actor}_STACK",
                    )
            results.append(
                {
                    "user_broker_account_id": uba_id,
                    "lease_restore": lease_restore,
                    "stack_restore": stack,
                }
            )
        session.commit()
        return {"ok": True, "count": len(results), "results": results}
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        logger.exception("unattended_startup_restore_failed")
        return {
            "ok": False,
            "error": type(exc).__name__,
            "message": str(exc)[:300],
            "results": results,
        }
    finally:
        session.close()
