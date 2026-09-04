"""Kiwoom MARKET_HOURS lease 복구 후 운영 스택 재기동.

대상: Market REALTIME feed · Strategy Runtime ensure/resume ·
LIVE Signal Execution Runner.

LIVE/ARM/Activation/lease는 LiveUnattendedAuthorizationService /
KiwoomTradingDayLifecycleService가 담당한다.

정책:
- Scheduler 강제 RUN 없음
- REAL 주문 강제 생성 없음
- Gate FAIL 시 stack start 금지
- Upbit UBA runner/상태 변경 금지 (scoped only)
- Worker/Runtime/ExecutionRunner 중복 start는 idempotent
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.strategy_deployment.definition_entities import (
    AccountStrategyLinkEntity,
)
from stock_platform.strategy_deployment.runtime_scope import (
    RuntimeLifecycleStatus,
)
from stock_platform.trading.account_models import UserBrokerAccount
from stock_platform.trading.live_unattended_authorization_service import (
    STATUS_ACTIVE,
    LiveUnattendedAuthorizationService,
)

logger = structlog.get_logger(__name__)


async def sync_kiwoom_account_state_for_startup(
    session: Session,
    *,
    user_broker_account_id: int,
) -> dict[str, Any]:
    """자동 시작 직전 예수금·보유·미체결 스냅샷 갱신 (주문 없음).

    공식 KiwoomAccountStateSyncService 경로 재사용.
    실패 시 LIVE/ARM 진행 금지용으로 ok=False 반환.
    """

    uba_id = int(user_broker_account_id)
    try:
        from stock_platform.broker.credential_adapter_factory import (
            build_kiwoom_account_client_for_uba,
            build_kiwoom_pending_order_client_for_uba,
        )
        from stock_platform.broker.kiwoom.account_sync_service import (
            KiwoomAccountSyncService,
        )
        from stock_platform.broker.kiwoom.account_state_sync_service import (
            KiwoomAccountStateSyncService,
        )
        from stock_platform.broker.kiwoom.pending_service import (
            KiwoomPendingOrderService,
        )

        account_client, _acct = build_kiwoom_account_client_for_uba(
            session, uba_id
        )
        result = await KiwoomAccountStateSyncService(
            session=session,
            account_sync_service=KiwoomAccountSyncService(
                session=session,
                account_client=account_client,
                user_broker_account_id=uba_id,
            ),
            pending_order_service=KiwoomPendingOrderService(
                session,
                build_kiwoom_pending_order_client_for_uba(session, uba_id),
            ),
        ).synchronize(user_broker_account_id=uba_id)
        session.flush()
        account = dict(result.account or {})
        pending = dict(result.pending_orders or {})
        # UNKNOWN/미체결 카운트 요약 (민감정보 제외)
        pending_count = pending.get("count")
        if pending_count is None:
            items = pending.get("items") or pending.get("orders") or []
            pending_count = len(items) if isinstance(items, list) else None
        return {
            "ok": True,
            "synced": True,
            "user_broker_account_id": uba_id,
            "snapshot_keys": sorted(account.keys())[:20],
            "has_deposit": "deposit_amount" in account
            or "ord_psbl_cash" in account
            or bool(account),
            "pending_order_count": pending_count,
            "fields": dict(result.fields or {}),
        }
    except Exception as exc:  # noqa: BLE001
        # CredentialVaultError 포함 — 민감정보 없이 코드만
        code = str(getattr(exc, "code", "") or "") or type(exc).__name__
        logger.warning(
            "kiwoom_startup_account_sync_failed",
            uba_id=uba_id,
            error=code,
        )
        return {
            "ok": False,
            "synced": False,
            "reason": (
                code
                if code
                not in {"", "Exception", "Error"}
                else "ACCOUNT_SYNC_FAILED"
            ),
            "error": type(exc).__name__,
            "message": str(exc)[:200],
        }


def evaluate_kiwoom_stack_restore_gates(
    session: Session,
    *,
    user_broker_account_id: int,
) -> dict[str, Any]:
    """스택 복구 전용 gate. 전부 PASS일 때만 feed/runtime/runner 기동."""

    uba_id = int(user_broker_account_id)
    blockers: list[str] = []
    checks: dict[str, Any] = {}

    uba = session.get(UserBrokerAccount, uba_id)
    if uba is None:
        return {"ok": False, "blockers": ["UBA_NOT_FOUND"], "checks": checks}
    if str(uba.broker_code or "").upper() != "KIWOOM":
        return {
            "ok": False,
            "blockers": ["UBA_BROKER_MISMATCH"],
            "checks": checks,
        }

    lease = LiveUnattendedAuthorizationService(session).get_active(uba_id)
    if lease is None or str(lease.status_code or "").upper() != STATUS_ACTIVE:
        blockers.append("NO_ACTIVE_LEASE")
        checks["lease"] = "MISSING"
    else:
        checks["lease"] = "ACTIVE"

    if not bool(getattr(uba, "live_order_enabled", False)):
        blockers.append("LIVE_OFF")
    if not bool(getattr(uba, "live_armed", False)):
        blockers.append("ARM_OFF")

    enable = LiveUnattendedAuthorizationService(session).evaluate_enable_gates(
        uba_id,
        authorization_mode="MARKET_HOURS",
    )
    checks["enable_gates"] = {
        "ok": enable.get("ok"),
        "blockers": list(enable.get("blockers") or []),
        "execution_env": enable.get("execution_env"),
    }
    ignored = {
        "RUNTIME_NOT_RUNNING",
        "OUTBOX_WORKER_NOT_RUNNING",
    }
    for code in enable.get("blockers") or []:
        if code in ignored:
            continue
        if code not in blockers:
            blockers.append(str(code))

    link = session.scalar(
        select(AccountStrategyLinkEntity)
        .where(
            AccountStrategyLinkEntity.user_broker_account_id == uba_id,
            AccountStrategyLinkEntity.is_active.is_(True),
        )
        .limit(1)
    )
    if link is None:
        blockers.append("NO_ACTIVE_STRATEGY_LINK")
        checks["strategy_link"] = None
    else:
        checks["strategy_link"] = {
            "strategy_id": int(link.strategy_id),
            "link_id": int(link.account_strategy_link_id),
        }

    uniq = list(dict.fromkeys(blockers))
    return {"ok": len(uniq) == 0, "blockers": uniq, "checks": checks}


def _latest_kiwoom_multi_symbol_monitor_symbols(
    session: Session, *, user_broker_account_id: int
) -> list[str]:
    """승인된 TOP10 monitor 최신 batch 심볼 — 임의 목록 생성 금지."""

    try:
        from stock_platform.operation.kiwoom_multi_symbol_universe.entities import (
            KiwoomMultiSymbolMonitorEntity,
        )
        from stock_platform.operation.kiwoom_multi_symbol_universe.mode import (
            is_kiwoom_multi_symbol_shadow_observability_enabled,
            resolve_kiwoom_multi_symbol_mode,
        )
        from stock_platform.operation.kiwoom_multi_symbol_universe.constants import (
            MODE_REAL,
        )

        # SHADOW observability 또는 REAL 모드일 때만 기존 roster 재사용
        mode = resolve_kiwoom_multi_symbol_mode()
        if mode != MODE_REAL and not is_kiwoom_multi_symbol_shadow_observability_enabled():
            return []

        uba_id = int(user_broker_account_id)
        latest_batch = session.scalar(
            select(KiwoomMultiSymbolMonitorEntity.refresh_batch_id)
            .where(
                KiwoomMultiSymbolMonitorEntity.user_broker_account_id == uba_id
            )
            .order_by(KiwoomMultiSymbolMonitorEntity.selected_at.desc())
            .limit(1)
        )
        if not latest_batch:
            return []
        rows = session.scalars(
            select(KiwoomMultiSymbolMonitorEntity.symbol).where(
                KiwoomMultiSymbolMonitorEntity.user_broker_account_id == uba_id,
                KiwoomMultiSymbolMonitorEntity.refresh_batch_id == latest_batch,
            )
        )
        return sorted(
            {
                str(s).strip().upper()
                for s in rows
                if str(s or "").strip()
            }
        )
    except Exception:  # noqa: BLE001
        return []


def _resolve_kiwoom_stack_feed_symbols(
    session: Session,
    *,
    user_broker_account_id: int,
    strategy_id: int | None,
    symbols: list[str] | None,
) -> list[str]:
    """공식 stack restore용 시세 심볼 SoT (하드코딩 금지).

    우선순위:
      1) 호출자 명시 symbols
      2) ACTIVE strategy_deployment.symbol / payload
      3) definition/backtest/perf 복원 (_resolve_runtime_payload_and_symbol)
      4) settings.realtime_strategy_symbol
      +) 승인된 multi-symbol TOP10 monitor 최신 batch 를 union
         (고정 전략 심볼 034310 유지 + TOP10 — canonical #79)
    """

    cleaned = sorted(
        {
            str(s).strip().upper()
            for s in (symbols or [])
            if str(s or "").strip()
        }
    )
    if cleaned:
        # 명시 symbols에도 TOP10 union (부분 복구 시 drift 방지)
        monitor = _latest_kiwoom_multi_symbol_monitor_symbols(
            session, user_broker_account_id=int(user_broker_account_id)
        )
        if monitor:
            return sorted(set(cleaned) | set(monitor))
        return cleaned

    from stock_platform.common.settings import get_settings
    from stock_platform.strategy_deployment.definition_entities import (
        StrategyDefinitionEntity,
    )
    from stock_platform.strategy_deployment.entities import (
        StrategyDeploymentEntity,
    )
    from stock_platform.strategy_deployment.models import (
        StrategyDeploymentStatus,
    )
    from stock_platform.strategy_deployment.runtime_loader import (
        _resolve_runtime_payload_and_symbol,
    )

    base: list[str] = []
    sid = int(strategy_id) if strategy_id is not None else None
    if sid is not None:
        deployment = session.scalar(
            select(StrategyDeploymentEntity)
            .where(
                StrategyDeploymentEntity.strategy_id == sid,
                StrategyDeploymentEntity.status_code
                == StrategyDeploymentStatus.ACTIVE.value,
            )
            .order_by(StrategyDeploymentEntity.strategy_deployment_id.desc())
            .limit(1)
        )
        definition = session.get(StrategyDefinitionEntity, sid)
        if deployment is not None or definition is not None:
            _payload, symbol = _resolve_runtime_payload_and_symbol(
                session,
                deployment
                or SimpleNamespace(symbol=None, parameter_payload={}),
                definition,
            )
            if symbol:
                base = [str(symbol).strip().upper()]

        # performance run fallback (deployment.symbol 비어 있을 때)
        if not base:
            try:
                from stock_platform.performance.entities import (
                    StrategyPerformanceRunEntity,
                )

                perf = session.scalar(
                    select(StrategyPerformanceRunEntity)
                    .where(StrategyPerformanceRunEntity.strategy_id == sid)
                    .order_by(
                        StrategyPerformanceRunEntity.strategy_performance_run_id.desc()
                    )
                    .limit(1)
                )
                if perf is not None and str(getattr(perf, "symbol", "") or "").strip():
                    base = [str(perf.symbol).strip().upper()]
            except Exception:  # noqa: BLE001
                pass

    if not base:
        settings = get_settings()
        fallback = str(
            getattr(settings, "realtime_strategy_symbol", "") or ""
        ).strip().upper()
        if fallback:
            base = [fallback]

    monitor = _latest_kiwoom_multi_symbol_monitor_symbols(
        session, user_broker_account_id=int(user_broker_account_id)
    )
    if monitor:
        return sorted(set(base) | set(monitor))
    return base


async def restore_kiwoom_trading_stack(
    session: Session,
    *,
    user_broker_account_id: int,
    actor: str = "SYSTEM_KIWOOM_STACK_RESTORE",
    symbols: list[str] | None = None,
) -> dict[str, Any]:
    """Gate PASS 시 feed → ensure-scope → resume → execution runner."""

    uba_id = int(user_broker_account_id)
    gates = evaluate_kiwoom_stack_restore_gates(
        session, user_broker_account_id=uba_id
    )
    if not gates["ok"]:
        return {
            "restored": False,
            "reason": "STACK_GATES_FAILED",
            "blockers": gates["blockers"],
            "gates": gates,
            "actor": actor,
        }

    detail: dict[str, Any] = {"gates": gates, "actor": actor}
    link_meta = (gates.get("checks") or {}).get("strategy_link") or {}
    strategy_id = link_meta.get("strategy_id")

    # 0) Live Outbox Worker — Upbit unattended restore와 동일 canonical 경로
    from stock_platform.order.live_outbox_worker_runtime import (
        live_outbox_worker_runtime,
    )

    worker_before = live_outbox_worker_runtime.status()
    detail["worker_before"] = {
        "enabled": worker_before.get("enabled"),
        "running": worker_before.get("running"),
    }
    if not bool(worker_before.get("enabled")):
        detail["worker"] = {
            "started": False,
            "reason": "LIVE_OUTBOX_WORKER_DISABLED",
        }
        return {
            "restored": False,
            "reason": "OUTBOX_WORKER_DISABLED",
            "detail": detail,
            "actor": actor,
        }
    if bool(worker_before.get("running")):
        detail["worker"] = {
            "started": True,
            "reason": "ALREADY_RUNNING",
            "idempotent": True,
        }
    else:
        detail["worker"] = live_outbox_worker_runtime.start()

    # 심볼: 명시 > deployment/definition/backtest/perf SoT (빈 목록이면 feed start 불가)
    feed_symbols = _resolve_kiwoom_stack_feed_symbols(
        session,
        user_broker_account_id=uba_id,
        strategy_id=int(strategy_id) if strategy_id is not None else None,
        symbols=symbols,
    )
    detail["feed_symbols"] = list(feed_symbols)

    # 1) Kiwoom market realtime WS (idempotent)
    # market_realtime_auto_start=false 여도 이 공식 restore 경로는 명시 start 호출.
    feed_ok_to_continue = False
    try:
        from stock_platform.trading.kiwoom_feed_recovery import (
            ensure_kiwoom_feed_running,
        )

        if not feed_symbols:
            detail["feed"] = {
                "started": False,
                "reason": "SYMBOLS_REQUIRED",
            }
            return {
                "restored": False,
                "reason": "FEED_START_FAILED",
                "detail": detail,
                "actor": actor,
            }

        feed_recover = await ensure_kiwoom_feed_running(
            session,
            user_broker_account_id=uba_id,
            symbols=feed_symbols,
            actor=actor,
        )
        detail["feed"] = feed_recover
        if feed_recover.get("hard_reconnect"):
            detail["feed"]["note"] = (
                "UNEXPECTED_HARD_RECONNECT_ON_STACK_ENSURE"
            )
        if not feed_recover.get("started") and not feed_recover.get(
            "already_running"
        ):
            return {
                "restored": False,
                "reason": "FEED_START_FAILED",
                "detail": detail,
                "actor": actor,
            }
        feed_ok_to_continue = True
    except Exception as exc:  # noqa: BLE001
        # feed ensure 예외여도 이미 REAL_FRESH면 runner/runtime 복구를 막지 않음
        feed_status = ""
        try:
            from stock_platform.trading.autotrading_health_service import (
                build_trading_health_snapshot,
            )

            snap = build_trading_health_snapshot(
                session, user_broker_account_id=uba_id
            )
            feed_status = str(
                (snap.get("components") or {}).get("feed") or ""
            ).upper()
        except Exception:  # noqa: BLE001
            feed_status = ""
        detail["feed"] = {
            "started": False,
            "error": type(exc).__name__,
            "error_message": str(exc)[:300],
            "health_feed": feed_status or None,
        }
        if feed_status in {
            "REAL_FRESH",
            "REAL_IDLE",
            "FRESH",
            "CONNECTED",
            "HEALTHY",
            "OK",
        }:
            logger.warning(
                "kiwoom_stack_feed_ensure_error_but_fresh_continue",
                uba_id=uba_id,
                error=type(exc).__name__,
                feed_status=feed_status,
            )
            # 이미 살아 있는 feed로 간주 — runner/runtime 복구 계속
            detail["feed"]["continued_despite_error"] = True
            detail["feed"]["already_running"] = True
            feed_ok_to_continue = True
        else:
            logger.warning(
                "kiwoom_stack_feed_failed",
                uba_id=uba_id,
                error=type(exc).__name__,
                feed_status=feed_status or None,
            )
            return {
                "restored": False,
                "reason": "FEED_START_ERROR",
                "error": type(exc).__name__,
                "detail": detail,
                "actor": actor,
            }

    if not feed_ok_to_continue:
        return {
            "restored": False,
            "reason": "FEED_START_FAILED",
            "detail": detail,
            "actor": actor,
        }

    # 2) canonical runtime — RUNNING 필수 (runner보다 선행)
    from stock_platform.strategy_deployment.runtime_bootstrap import (
        _build_scope_for_link,
    )
    from stock_platform.strategy_deployment.runtime_manager import (
        dynamic_strategy_runtime_manager,
    )
    from stock_platform.risk_engine.kill_switch_service import KillSwitchService
    from stock_platform.realtime.kiwoom_runtime_run_gates import (
        evaluate_kiwoom_runtime_run_gates,
    )
    from stock_platform.trading.upbit_24x7_control import runtime_status_for_uba

    runtime_running = False
    if strategy_id is None:
        detail["runtime"] = {
            "resumed": False,
            "reason": "STRATEGY_ID_MISSING",
        }
    else:
        link = session.scalar(
            select(AccountStrategyLinkEntity).where(
                AccountStrategyLinkEntity.user_broker_account_id == uba_id,
                AccountStrategyLinkEntity.strategy_id == int(strategy_id),
                AccountStrategyLinkEntity.is_active.is_(True),
            )
        )
        if link is None:
            detail["runtime"] = {
                "resumed": False,
                "reason": "LINK_NOT_FOUND",
            }
        else:
            try:
                rt_gates = evaluate_kiwoom_runtime_run_gates(
                    session,
                    user_broker_account_id=uba_id,
                    strategy_id=int(strategy_id),
                )
                detail["runtime_gates"] = rt_gates
                if not rt_gates.get("ok"):
                    detail["runtime"] = {
                        "resumed": False,
                        "reason": "RUNTIME_GATES_FAILED",
                        "blockers": rt_gates.get("blockers"),
                    }
                else:
                    kill_active = bool(KillSwitchService(session).is_active())
                    scope, _ = _build_scope_for_link(
                        session, link, kill_active=kill_active
                    )
                    entries = [
                        e
                        for e in dynamic_strategy_runtime_manager.list_entries(
                            user_broker_account_id=uba_id,
                            strategy_id=int(strategy_id),
                        )
                        if str(e.scope.broker_code or "").upper() == "KIWOOM"
                    ]
                    running = [
                        e
                        for e in entries
                        if e.status == RuntimeLifecycleStatus.RUNNING
                    ]
                    paused = [
                        e
                        for e in entries
                        if e.status == RuntimeLifecycleStatus.PAUSED
                    ]
                    if running:
                        detail["runtime"] = {
                            "resumed": True,
                            "reason": "ALREADY_RUNNING",
                            "idempotent": True,
                            "scope_key": running[0].scope.scope_key,
                        }
                        runtime_running = True
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
                        runtime_running = True
                    else:
                        # STOPPED/미등록 — desired RUNNING 이면 start=True 로 기동
                        await dynamic_strategy_runtime_manager.initialize_scoped(
                            scope, force=True, start=True
                        )
                        detail["runtime"] = {
                            "resumed": True,
                            "reason": "STARTED",
                            "scope_key": scope.scope_key,
                        }
                        runtime_running = True
            except Exception as exc:  # noqa: BLE001
                detail["runtime"] = {
                    "resumed": False,
                    "reason": "RUNTIME_ERROR",
                    "error": type(exc).__name__,
                }

    rt_status = runtime_status_for_uba(
        user_broker_account_id=uba_id,
        strategy_id=int(strategy_id) if strategy_id is not None else None,
        broker_code="KIWOOM",
    )
    detail["runtime_status"] = rt_status
    runtime_running = (
        runtime_running
        and str(rt_status.get("status") or "").upper() == "RUNNING"
    )

    # fail-closed: canonical runtime != RUNNING 이면 orphan runner 중지
    try:
        from stock_platform.realtime.runtime import (
            realtime_execution_runner_manager,
        )

        existing = realtime_execution_runner_manager.get(uba_id, "KIWOOM")
        runner_live = bool(
            existing is not None
            and (existing.status() or {}).get("running")
        )
        if runner_live and not runtime_running:
            await realtime_execution_runner_manager.stop_scope(uba_id, "KIWOOM")
            detail["runner_pre_stop"] = {
                "stopped": True,
                "reason": "CONTROL_STATE_MISMATCH_FAIL_CLOSED",
            }
    except Exception as exc:  # noqa: BLE001
        detail["runner_pre_stop"] = {
            "stopped": False,
            "error": type(exc).__name__,
        }

    # 3) realtime execution runner — runtime RUNNING 일 때만
    if not runtime_running:
        detail["runner"] = {
            "started": False,
            "reason": "RUNTIME_NOT_RUNNING",
        }
        from stock_platform.trading.execution_stack_reconciliation import (
            verify_stack_restored,
        )

        verify = verify_stack_restored(session, user_broker_account_id=uba_id)
        detail["verify"] = verify
        return {
            "restored": False,
            "reason": "RUNTIME_NOT_RUNNING",
            "detail": detail,
            "actor": actor,
            "upbit_untouched": True,
        }

    try:
        from stock_platform.api.v1.realtime_execution import (
            _start_live_for_uba,
        )

        runner = await _start_live_for_uba(uba_id)
        detail["runner"] = {
            "started": bool(
                runner.get("started") or runner.get("already_running")
            ),
            "idempotent": bool(runner.get("already_running")),
            "mode": runner.get("mode"),
            "user_broker_account_id": runner.get("user_broker_account_id")
            or uba_id,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "kiwoom_stack_runner_failed",
            uba_id=uba_id,
            error=type(exc).__name__,
        )
        detail["runner"] = {
            "started": False,
            "reason": "RUNNER_START_ERROR",
            "error": type(exc).__name__,
        }
        return {
            "restored": False,
            "reason": "RUNNER_START_FAILED",
            "detail": detail,
            "actor": actor,
        }

    from stock_platform.trading.execution_stack_reconciliation import (
        verify_stack_restored,
    )

    verify = verify_stack_restored(session, user_broker_account_id=uba_id)
    detail["verify"] = verify
    restored_ok = bool(verify.get("restore_succeeded"))
    if not restored_ok and bool(verify.get("core_restored")):
        restored_ok = bool(
            (detail.get("feed") or {}).get("started")
            and (detail.get("runner") or {}).get("started")
            and runtime_running
        )
    return {
        "restored": restored_ok,
        "reason": "OK" if restored_ok else "PARTIAL",
        "detail": detail,
        "actor": actor,
        "upbit_untouched": True,
    }


async def restore_all_active_unattended_kiwoom_leases(
    *,
    actor: str = "SYSTEM_UNATTENDED_STARTUP_RESTORE",
) -> dict[str, Any]:
    """Startup: ACTIVE KIWOOM lease 전수 → stack restore (REGULAR only).

    CLOSED/HOLIDAY 에서는 feed 강제 start 하지 않는다.
    """

    from stock_platform.database.session import get_session_factory
    from stock_platform.trading.live_unattended_entities import (
        LiveUnattendedAuthorizationEntity,
    )
    from stock_platform.trading.market_hours_authorization import (
        krx_market_hours_state,
    )

    sf = get_session_factory()
    session = sf()
    results: list[dict[str, Any]] = []
    try:
        mh = krx_market_hours_state(session)
        in_regular = bool(mh.get("in_regular_session"))
        if not in_regular:
            return {
                "ok": True,
                "skipped": True,
                "reason": "NOT_REGULAR_SESSION",
                "market_hours": mh,
                "count": 0,
                "results": [],
            }

        rows = list(
            session.scalars(
                select(LiveUnattendedAuthorizationEntity).where(
                    LiveUnattendedAuthorizationEntity.enabled.is_(True),
                    LiveUnattendedAuthorizationEntity.status_code
                    == STATUS_ACTIVE,
                )
            )
        )
        for row in rows:
            uba_id = int(row.user_broker_account_id)
            uba = session.get(UserBrokerAccount, uba_id)
            if uba is None or str(uba.broker_code or "").upper() != "KIWOOM":
                results.append(
                    {
                        "user_broker_account_id": uba_id,
                        "skipped": True,
                        "reason": "NOT_KIWOOM",
                    }
                )
                continue
            stack = await restore_kiwoom_trading_stack(
                session,
                user_broker_account_id=uba_id,
                actor=actor,
            )
            results.append(
                {
                    "user_broker_account_id": uba_id,
                    "stack_restore": stack,
                }
            )
            logger.info(
                "kiwoom_stack_restore_done",
                uba_id=uba_id,
                restored=bool(stack.get("restored")),
                reason=stack.get("reason"),
            )
        return {
            "ok": True,
            "count": len(results),
            "results": results,
            "market_hours": mh,
        }
    finally:
        session.close()
