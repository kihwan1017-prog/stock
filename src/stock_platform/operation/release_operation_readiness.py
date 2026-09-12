"""Release v1.2 운영 준비 — Configuration / Health / Fail-Closed / Lifecycle.

실주문·LIVE 활성화·OAuth 재시도 없음. 조회·검증 전용.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from stock_platform.common.settings import get_settings
from stock_platform.operation.db_pool_monitor import measure_db_latency_ms
from stock_platform.operation.resource_monitor import build_resource_monitoring
from stock_platform.operation.runtime_info import build_system_identity


_LAST_STARTUP_VALIDATION: dict[str, Any] | None = None


def get_last_startup_validation() -> dict[str, Any] | None:
    return _LAST_STARTUP_VALIDATION


def _ok(detail: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"status": "PASS", **(detail or {})}


def _warn(code: str, detail: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"status": "WARN", "code": code, **(detail or {})}


def _fail(code: str, detail: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"status": "FAIL", "code": code, **(detail or {})}


def _safe(exc: Exception) -> str:
    msg = str(exc)
    return msg[:200] + ("..." if len(msg) > 200 else "")


def validate_environment() -> dict[str, Any]:
    settings = get_settings()
    detail = {
        "app_env": settings.app_env,
        "is_production": settings.is_production_env,
        "jwt_secret_configured": bool(settings.jwt_secret.strip()),
        "admin_api_key_configured": bool(
            getattr(settings, "admin_api_key", "") or ""
        ),
    }
    if not settings.jwt_secret.strip():
        return _fail("JWT_SECRET_MISSING", detail)
    return _ok(detail)


def validate_credential(session: Session) -> dict[str, Any]:
    """Credential vault 존재·검증 상태만 확인 (복호화 남용 금지)."""

    try:
        from stock_platform.broker.credential_vault_service import (
            BrokerCredentialVaultService,
        )
        from stock_platform.trading.account_models import UserBrokerAccount

        ubas = list(
            session.scalars(
                select(UserBrokerAccount).where(
                    UserBrokerAccount.is_active.is_(True),
                    UserBrokerAccount.deleted_at.is_(None),
                ).limit(50)
            )
        )
        vault = BrokerCredentialVaultService(session)
        verified = 0
        missing = 0
        for uba in ubas:
            try:
                st = vault.status(int(uba.user_broker_account_id))
                if str(getattr(st, "verification_status", "") or "") == "VERIFIED":
                    verified += 1
                else:
                    missing += 1
            except Exception:  # noqa: BLE001
                missing += 1
        detail = {
            "active_uba_checked": len(ubas),
            "verified": verified,
            "unverified_or_error": missing,
        }
        if ubas and verified == 0:
            return _warn("NO_VERIFIED_CREDENTIAL", detail)
        return _ok(detail)
    except Exception as exc:  # noqa: BLE001
        return _warn("CREDENTIAL_CHECK_FAILED", {"message": _safe(exc)})


def validate_runtime() -> dict[str, Any]:
    settings = get_settings()
    try:
        from stock_platform.realtime.runtime import (
            realtime_execution_runner,
            realtime_strategy_runner,
        )
        from stock_platform.strategy_deployment.runtime_manager import (
            dynamic_strategy_runtime_manager,
        )

        exec_st = realtime_execution_runner.status()
        strat_st = realtime_strategy_runner.status()
        mgr_st = dynamic_strategy_runtime_manager.status()
        detail = {
            "execution": exec_st,
            "strategy": strat_st,
            "dynamic_manager": {
                "running_count": (
                    mgr_st.get("running_count")
                    if isinstance(mgr_st, dict)
                    else None
                ),
                "keys": list((mgr_st.get("scopes") or mgr_st.get("items") or {})
                             if isinstance(mgr_st, dict)
                             else [])[:20],
            },
            "auto_flags": {
                "paper": bool(
                    getattr(settings, "realtime_paper_auto_start_enabled", False)
                ),
                "mock": bool(
                    getattr(
                        settings, "realtime_kiwoom_mock_auto_start_enabled", False
                    )
                ),
                "upbit_shadow": bool(
                    getattr(
                        settings, "realtime_upbit_shadow_auto_start_enabled", False
                    )
                ),
                "live": bool(
                    getattr(settings, "realtime_live_auto_start_enabled", False)
                ),
            },
        }
        return _ok(detail)
    except Exception as exc:  # noqa: BLE001
        return _warn("RUNTIME_CHECK_FAILED", {"message": _safe(exc)})


def validate_scheduler() -> dict[str, Any]:
    settings = get_settings()
    try:
        from stock_platform.realtime.session_runtime import (
            realtime_trading_scheduler,
        )

        jobs: list[str] = []
        status: dict[str, Any] = {}
        running = False
        try:
            if hasattr(realtime_trading_scheduler, "status"):
                status = realtime_trading_scheduler.status() or {}
            if isinstance(status, dict):
                running = bool(status.get("running", False))
                raw_jobs = (
                    status.get("jobs")
                    or status.get("job_ids")
                    or status.get("registered_jobs")
                    or []
                )
                if isinstance(raw_jobs, list):
                    jobs = [str(j) for j in raw_jobs]
                elif isinstance(raw_jobs, dict):
                    jobs = list(raw_jobs.keys())
            # APScheduler 내부 접근 (RealtimeTradingScheduler)
            aps = getattr(realtime_trading_scheduler, "_scheduler", None) or getattr(
                realtime_trading_scheduler, "scheduler", None
            )
            if aps is not None and hasattr(aps, "get_jobs"):
                aps_jobs = list(aps.get_jobs())
                jobs = [str(j.id) for j in aps_jobs]
                running = bool(getattr(aps, "running", running))
            elif hasattr(realtime_trading_scheduler, "registered_job_ids"):
                jobs = sorted(realtime_trading_scheduler.registered_job_ids())
        except Exception as exc:  # noqa: BLE001
            status = {"error": _safe(exc)}
        dup = len(jobs) - len(set(jobs)) if jobs else 0
        detail = {
            "scheduler_enabled": bool(settings.scheduler_enabled),
            "running": running,
            "job_count": len(jobs),
            "duplicate_job_count": dup,
            "scheduler_status": status if isinstance(status, dict) else {},
        }
        if dup > 0:
            return _fail("DUPLICATE_SCHEDULER_JOBS", detail)
        return _ok(detail)
    except Exception as exc:  # noqa: BLE001
        return _warn("SCHEDULER_CHECK_FAILED", {"message": _safe(exc)})


def validate_broker() -> dict[str, Any]:
    settings = get_settings()
    detail = {
        "kiwoom_use_mock": bool(settings.kiwoom_use_mock),
        "kiwoom_live_order_enabled": bool(settings.kiwoom_live_order_enabled),
        "upbit_live_order_enabled": bool(settings.upbit_live_order_enabled),
        "global_live_order_enabled": bool(settings.global_live_order_enabled),
        "kiwoom_app_key_configured": bool(settings.kiwoom_app_key.strip()),
        "upbit_base_url": bool(settings.upbit_base_url.strip()),
    }
    # v1.2 운영 준비: LIVE 실주문 Flag 는 OFF 가 정상
    if settings.kiwoom_live_order_enabled or settings.upbit_live_order_enabled:
        return _warn("LIVE_ORDER_FLAG_ON", detail)
    if settings.kiwoom_live_order_enabled and settings.kiwoom_use_mock:
        return _fail("LIVE_MOCK_CONFLICT", detail)
    return _ok(detail)


def validate_database(session: Session) -> dict[str, Any]:
    status, latency_ms, error = measure_db_latency_ms()
    detail: dict[str, Any] = {
        "db_status": status,
        "latency_ms": latency_ms,
    }
    if status != "UP":
        return _fail("DATABASE_DOWN", {**detail, "message": error})
    try:
        from stock_platform.operation.startup_runtime_policy import (
            migration_at_head,
        )

        at_head = migration_at_head(session)
        detail["migration_at_head"] = at_head
        if not at_head:
            return _warn("MIGRATION_NOT_AT_HEAD", detail)
    except Exception as exc:  # noqa: BLE001
        detail["migration_check"] = _safe(exc)
    return _ok(detail)


def validate_recovery() -> dict[str, Any]:
    try:
        from stock_platform.broker.recovery_runtime import broker_recovery_manager
        from stock_platform.broker.recovery_scheduler import (
            broker_recovery_scheduler,
        )

        mgr = {}
        sch = {}
        try:
            mgr = broker_recovery_manager.status()
        except Exception as exc:  # noqa: BLE001
            mgr = {"error": _safe(exc)}
        try:
            sch = broker_recovery_scheduler.status()
        except Exception as exc:  # noqa: BLE001
            sch = {"error": _safe(exc)}
        return _ok({"manager": mgr, "scheduler": sch})
    except Exception as exc:  # noqa: BLE001
        return _warn("RECOVERY_CHECK_FAILED", {"message": _safe(exc)})


def validate_dashboard() -> dict[str, Any]:
    """Dashboard 서비스 import·기본 슬라이스 가능 여부."""

    try:
        from stock_platform.operation.ops_monitoring.service import (
            OpsMonitoringDashboardService,
        )
        from stock_platform.realtime.dashboard_service import (
            RealtimeDashboardService,
        )

        return _ok(
            {
                "ops_monitoring": OpsMonitoringDashboardService.__name__,
                "realtime_dashboard": RealtimeDashboardService.__name__,
            }
        )
    except Exception as exc:  # noqa: BLE001
        return _fail("DASHBOARD_IMPORT_FAILED", {"message": _safe(exc)})


def validate_telegram() -> dict[str, Any]:
    settings = get_settings()
    enabled = bool(settings.telegram_enabled or settings.telegram_ops_enabled)
    token = bool(settings.telegram_bot_token.strip())
    chat = bool(settings.telegram_chat_id.strip())
    detail = {
        "telegram_enabled": bool(settings.telegram_enabled),
        "telegram_ops_enabled": bool(settings.telegram_ops_enabled),
        "token_configured": token,
        "chat_configured": chat,
    }
    if enabled and not (token and chat):
        return _warn("TELEGRAM_INCOMPLETE", detail)
    if not enabled:
        return _ok({**detail, "note": "DISABLED"})
    return _ok(detail)


def validate_notification() -> dict[str, Any]:
    try:
        from stock_platform.notification.models import NotificationSendStatus

        return _ok(
            {
                "notification_module": True,
                "send_status_enum": NotificationSendStatus.__name__,
            }
        )
    except Exception as exc:  # noqa: BLE001
        return _warn("NOTIFICATION_CHECK_FAILED", {"message": _safe(exc)})


def evaluate_fail_closed(session: Session | None = None) -> dict[str, Any]:
    """LIVE/Paper/Mock/Upbit/Kill/Pause/Credential/Unlock/Flag 최종 점검."""

    settings = get_settings()
    from stock_platform.broker.live_config_gate import (
        evaluate_live_flag_consistency,
    )

    cfg = evaluate_live_flag_consistency()
    gates: dict[str, Any] = {
        "live_flags": {
            "global": bool(settings.global_live_order_enabled),
            "kiwoom": bool(settings.kiwoom_live_order_enabled),
            "upbit": bool(settings.upbit_live_order_enabled),
            "consistency": {
                "status": cfg.status,
                "code": cfg.code,
                "allowed": cfg.allowed,
            },
        },
        "paper": {
            "account_id": int(
                getattr(settings, "realtime_paper_account_id", 0) or 0
            ),
            "auto_start": bool(
                getattr(settings, "realtime_paper_auto_start_enabled", False)
            ),
        },
        "mock": {
            "kiwoom_use_mock": bool(settings.kiwoom_use_mock),
            "auto_start": bool(
                getattr(
                    settings, "realtime_kiwoom_mock_auto_start_enabled", False
                )
            ),
        },
        "upbit": {
            "shadow_auto_start": bool(
                getattr(
                    settings, "realtime_upbit_shadow_auto_start_enabled", False
                )
            ),
            "shadow_mode": bool(
                getattr(settings, "live_shadow_mode_enabled", False)
            ),
            "dry_run": bool(
                getattr(settings, "live_order_dry_run_enabled", False)
            ),
            "live_order_enabled": bool(settings.upbit_live_order_enabled),
        },
        "submit_mutate_allowed": False,
    }

    blockers: list[str] = []
    if settings.kiwoom_live_order_enabled or settings.upbit_live_order_enabled:
        blockers.append("LIVE_ORDER_FLAG_ON")
    if cfg.status == "CRITICAL":
        blockers.append(cfg.code)

    kill_active = False
    pause_note: dict[str, Any] = {}
    if session is not None:
        try:
            from stock_platform.risk_engine.kill_switch_models import (
                KillSwitchStatus,
            )
            from stock_platform.risk_engine.kill_switch_service import (
                KillSwitchService,
            )

            kill = KillSwitchService(session).get_state()
            kill_active = kill.status == KillSwitchStatus.ACTIVE
            gates["kill_switch"] = {
                "active": kill_active,
                "status": str(kill.status),
            }
            if kill_active:
                blockers.append("KILL_SWITCH_ACTIVE")
        except Exception as exc:  # noqa: BLE001
            gates["kill_switch"] = {"error": _safe(exc)}
            blockers.append("KILL_SWITCH_CHECK_FAILED")

        try:
            from stock_platform.trading.trading_scheduler_control import (
                get_trading_scheduler_control_meta,
            )

            snap = get_trading_scheduler_control_meta()
            pause_note = snap if isinstance(snap, dict) else {"raw": str(snap)}
            gates["pause"] = pause_note
        except Exception as exc:  # noqa: BLE001
            gates["pause"] = {"error": _safe(exc)}

        try:
            from stock_platform.operation.live_health_gate import (
                evaluate_live_order_health,
            )

            gates["live_health"] = evaluate_live_order_health(session)
            if not gates["live_health"].get("live_orders_allowed", True):
                blockers.append("LIVE_HEALTH_CRITICAL")
        except Exception as exc:  # noqa: BLE001
            gates["live_health"] = {"error": _safe(exc)}

    # Unlock: LIVE ARM 은 재시작 후 OFF 기대
    gates["unlock"] = {
        "live_auto_start": bool(
            getattr(settings, "realtime_live_auto_start_enabled", False)
        ),
        "note": "LIVE unlock/ARM must stay OFF for v1.2 ops readiness",
    }

    # v1.2: 실주문 경로 완전 차단이 성공 조건
    live_submit_blocked = not (
        settings.kiwoom_live_order_enabled or settings.upbit_live_order_enabled
    )
    ready = live_submit_blocked and cfg.status != "CRITICAL"
    return {
        "ready_for_ops_without_live": ready,
        "live_submit_blocked": live_submit_blocked,
        "blockers": blockers,
        "gates": gates,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def validate_release_lifecycle() -> dict[str, Any]:
    """Startup/Shutdown/Restart/Recovery/GracefulStop/Restore 훅 존재 검증."""

    checks: dict[str, Any] = {}
    try:
        from stock_platform.api.lifecycle import ApplicationLifecycle

        lifecycle = ApplicationLifecycle()
        checks["startup"] = {
            "status": "PASS",
            "has_startup": callable(lifecycle.startup),
            "has_shutdown": callable(lifecycle.shutdown),
            "started": bool(lifecycle.started),
        }
    except Exception as exc:  # noqa: BLE001
        checks["startup"] = {"status": "FAIL", "message": _safe(exc)}

    try:
        from stock_platform.realtime.live_runtime_control import (
            stop_live_market_feeds,
        )
        from stock_platform.realtime.integrated_runtime_lifecycle import (
            on_market_close,
            on_market_open,
        )

        checks["graceful_stop"] = {
            "status": "PASS",
            "market_open": callable(on_market_open),
            "market_close": callable(on_market_close),
            "stop_feeds": callable(stop_live_market_feeds),
        }
    except Exception as exc:  # noqa: BLE001
        checks["graceful_stop"] = {"status": "WARN", "message": _safe(exc)}

    try:
        from stock_platform.broker.recovery_runtime import broker_recovery_manager
        from stock_platform.operation.startup_runtime_policy import (
            RuntimeStartupPolicy,
        )

        checks["recovery_restart"] = {
            "status": "PASS",
            "startup_policy": RuntimeStartupPolicy.__name__,
            "recovery_manager": type(broker_recovery_manager).__name__,
        }
    except Exception as exc:  # noqa: BLE001
        checks["recovery_restart"] = {
            "status": "WARN",
            "message": _safe(exc),
        }

    try:
        from stock_platform.realtime.manager import realtime_manager

        checks["connection_restore"] = {
            "status": "PASS",
            "realtime_manager": type(realtime_manager).__name__,
            "has_status": hasattr(realtime_manager, "status"),
        }
    except Exception as exc:  # noqa: BLE001
        checks["connection_restore"] = {
            "status": "WARN",
            "message": _safe(exc),
        }

    fails = [
        k for k, v in checks.items() if str(v.get("status")) == "FAIL"
    ]
    return {
        "status": "FAIL" if fails else "PASS",
        "failed": fails,
        "checks": checks,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def run_startup_configuration_validation(
    session: Session | None = None,
) -> dict[str, Any]:
    """Startup 시 Configuration Validation 전체 실행."""

    global _LAST_STARTUP_VALIDATION

    own_session = False
    if session is None:
        from stock_platform.database.session import get_session_factory

        session = get_session_factory()()
        own_session = True

    try:
        checks = {
            "environment": validate_environment(),
            "credential": validate_credential(session),
            "runtime": validate_runtime(),
            "scheduler": validate_scheduler(),
            "broker": validate_broker(),
            "database": validate_database(session),
            "recovery": validate_recovery(),
            "dashboard": validate_dashboard(),
            "telegram": validate_telegram(),
            "notification": validate_notification(),
        }
        fail_closed = evaluate_fail_closed(session)
        lifecycle = validate_release_lifecycle()

        fails = [
            name
            for name, row in checks.items()
            if str(row.get("status")) == "FAIL"
        ]
        warns = [
            name
            for name, row in checks.items()
            if str(row.get("status")) == "WARN"
        ]
        overall = "PASS"
        if fails:
            overall = "FAIL"
        elif warns or not fail_closed.get("ready_for_ops_without_live"):
            overall = "WARN"

        result = {
            "overall": overall,
            "release": "v1.2",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "checks": checks,
            "fail_closed": fail_closed,
            "lifecycle": lifecycle,
            "fail_count": len(fails),
            "warn_count": len(warns),
            "failed_checks": fails,
            "warned_checks": warns,
            "identity": build_system_identity(),
        }
        _LAST_STARTUP_VALIDATION = result
        return result
    finally:
        if own_session and session is not None:
            session.close()


def build_operation_health() -> dict[str, Any]:
    """강화 Health — API/Dashboard/Runtime/Scheduler/Recovery/Broker/..."""

    components: dict[str, Any] = {}
    settings = get_settings()

    # API
    components["api"] = {
        "status": "UP",
        "identity": build_system_identity(),
    }

    # Database / Connection
    db_status, latency_ms, error = measure_db_latency_ms()
    components["database"] = {
        "status": db_status,
        "response_time_ms": latency_ms,
        **({"message": error} if error else {}),
    }
    components["connection"] = {
        "status": db_status,
        "database": db_status,
        "latency_ms": latency_ms,
    }

    # Dashboard
    dash = validate_dashboard()
    components["dashboard"] = {
        "status": "UP" if dash.get("status") == "PASS" else "DOWN",
        **{k: v for k, v in dash.items() if k != "status"},
    }

    # Runtime
    try:
        from stock_platform.realtime.runtime import (
            realtime_execution_runner,
            realtime_strategy_runner,
        )

        components["runtime"] = {
            "status": "UP",
            "execution": realtime_execution_runner.status(),
            "strategy": realtime_strategy_runner.status(),
        }
    except Exception as exc:  # noqa: BLE001
        components["runtime"] = {"status": "DOWN", "message": _safe(exc)}

    # Scheduler
    sch = validate_scheduler()
    components["scheduler"] = {
        "status": (
            "UP"
            if sch.get("status") == "PASS"
            else ("DEGRADED" if sch.get("status") == "WARN" else "DOWN")
        ),
        **{k: v for k, v in sch.items() if k != "status"},
    }

    # Recovery
    rec = validate_recovery()
    components["recovery"] = {
        "status": "UP" if rec.get("status") == "PASS" else "DEGRADED",
        **{k: v for k, v in rec.items() if k != "status"},
    }

    # Broker
    br = validate_broker()
    components["broker"] = {
        "status": (
            "UP"
            if br.get("status") == "PASS"
            else ("DEGRADED" if br.get("status") == "WARN" else "CRITICAL")
        ),
        **{k: v for k, v in br.items() if k != "status"},
    }

    # Outbox / Worker / Queue
    try:
        from stock_platform.order.outbox_entities import OrderOutbox
        from stock_platform.order.outbox_models import OutboxStatus
        from stock_platform.order.outbox_runtime import order_outbox_scheduler
        from stock_platform.database.session import get_session_factory

        session = get_session_factory()()
        try:
            pending = int(
                session.scalar(
                    select(func.count())
                    .select_from(OrderOutbox)
                    .where(
                        OrderOutbox.status_code.in_(
                            [
                                OutboxStatus.PENDING.value,
                                OutboxStatus.PROCESSING.value,
                            ]
                        )
                    )
                )
                or 0
            )
            components["outbox"] = {
                "status": "UP",
                "pending_or_processing": pending,
            }
        finally:
            session.close()

        try:
            task = getattr(order_outbox_scheduler, "_task", None)
            running = task is not None and not task.done()
            components["worker"] = {
                "status": "UP",
                "outbox_scheduler_running": running,
            }
        except Exception as exc:  # noqa: BLE001
            components["worker"] = {
                "status": "DEGRADED",
                "message": _safe(exc),
            }
    except Exception as exc:  # noqa: BLE001
        components["outbox"] = {"status": "UNKNOWN", "message": _safe(exc)}
        components["worker"] = {"status": "UNKNOWN", "message": _safe(exc)}

    try:
        from stock_platform.realtime.persistence import (
            market_data_persistence_worker,
        )

        components["queue"] = {
            "status": "UP",
            **market_data_persistence_worker.status(),
        }
    except Exception as exc:  # noqa: BLE001
        components["queue"] = {"status": "UNKNOWN", "message": _safe(exc)}

    try:
        from stock_platform.trading.upbit_24x7_control import (
            build_24x7_ops_health,
        )

        components["upbit_24x7"] = build_24x7_ops_health()
    except Exception as exc:  # noqa: BLE001
        components["upbit_24x7"] = {
            "status": "UNKNOWN",
            "message": _safe(exc),
        }

    # WebSocket
    try:
        from stock_platform.broker.kiwoom.ws_manager import (
            kiwoom_order_websocket_manager,
        )
        from stock_platform.realtime.manager import realtime_manager

        ws_kiwoom = kiwoom_order_websocket_manager.status()
        # sync 접근: clients dict
        clients = getattr(realtime_manager, "_clients", {}) or {}
        ws_clients = {
            str(k): (v.status() if hasattr(v, "status") else {})
            for k, v in list(clients.items())[:10]
        }
        components["websocket"] = {
            "status": "UP",
            "kiwoom_order_ws": ws_kiwoom,
            "market_clients": ws_clients,
        }
    except Exception as exc:  # noqa: BLE001
        components["websocket"] = {
            "status": "UNKNOWN",
            "message": _safe(exc),
        }

    components["live_order_flags"] = {
        "status": (
            "UP"
            if not (
                settings.kiwoom_live_order_enabled
                or settings.upbit_live_order_enabled
            )
            else "DEGRADED"
        ),
        "kiwoom_live_order_enabled": settings.kiwoom_live_order_enabled,
        "upbit_live_order_enabled": settings.upbit_live_order_enabled,
        "submit_allowed": False,
    }

    last = get_last_startup_validation()
    if last:
        components["release_startup_validation"] = {
            "status": (
                "UP"
                if last.get("overall") == "PASS"
                else (
                    "DEGRADED"
                    if last.get("overall") == "WARN"
                    else "DOWN"
                )
            ),
            "overall": last.get("overall"),
            "checked_at": last.get("checked_at"),
            "fail_count": last.get("fail_count"),
            "warn_count": last.get("warn_count"),
        }

    overall = "UP"
    for item in components.values():
        st = str(item.get("status", "")).upper()
        if st == "CRITICAL":
            overall = "CRITICAL"
            break
        if st in {"DOWN", "ERROR", "FAILED"}:
            if overall != "CRITICAL":
                overall = "DEGRADED"
        if st == "DEGRADED" and overall == "UP":
            overall = "DEGRADED"

    return {
        "status": overall,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "components": components,
    }


def build_operation_dashboard_slice(session: Session) -> dict[str, Any]:
    """운영 Dashboard — 필수 지표만."""

    resources = build_resource_monitoring()
    health = build_operation_health()
    fail_closed = evaluate_fail_closed(session)

    pending = 0
    fill_today = 0
    try:
        from stock_platform.order.outbox_entities import OrderOutbox
        from stock_platform.order.outbox_models import OutboxStatus

        pending = int(
            session.scalar(
                select(func.count())
                .select_from(OrderOutbox)
                .where(
                    OrderOutbox.status_code.in_(
                        [
                            OutboxStatus.PENDING.value,
                            OutboxStatus.PROCESSING.value,
                        ]
                    )
                )
            )
            or 0
        )
    except Exception:  # noqa: BLE001
        pending = -1

    try:
        fill_today = int(
            session.execute(
                text(
                    """
                    SELECT count(*) FROM trading.trading_order
                    WHERE status_code IN ('FILLED', 'PARTIALLY_FILLED')
                      AND updated_at >= date_trunc('day', NOW() AT TIME ZONE 'Asia/Seoul')
                           AT TIME ZONE 'Asia/Seoul'
                    """
                )
            ).scalar()
            or 0
        )
    except Exception:  # noqa: BLE001
        fill_today = -1

    position_count = 0
    try:
        from stock_platform.broker.account_models import (
            BrokerPositionSnapshotEntity,
        )

        position_count = int(
            session.scalar(select(func.count()).select_from(BrokerPositionSnapshotEntity))
            or 0
        )
    except Exception:  # noqa: BLE001
        position_count = -1

    errors: list[str] = list(fail_closed.get("blockers") or [])
    comps = health.get("components") or {}
    for name, row in comps.items():
        if str(row.get("status", "")).upper() in {
            "DOWN",
            "CRITICAL",
            "ERROR",
        }:
            errors.append(f"{name.upper()}_{row.get('status')}")

    return {
        "release": "v1.2",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "runtime": comps.get("runtime"),
        "worker": comps.get("worker"),
        "recovery": comps.get("recovery"),
        "scheduler": comps.get("scheduler"),
        "broker": comps.get("broker"),
        "queue": comps.get("queue"),
        "fill": {"today_count": fill_today},
        "pending": {"outbox_pending_or_processing": pending},
        "position": {"snapshot_count": position_count},
        "pnl": {"note": "see ops risk / positions endpoints"},
        "memory": resources.get("memory"),
        "cpu": resources.get("cpu"),
        "error": {"codes": errors[:30], "count": len(errors)},
        "fail_closed": fail_closed,
        "health_status": health.get("status"),
        "startup_validation": get_last_startup_validation(),
    }


def build_release_readiness_report(session: Session) -> dict[str, Any]:
    """Admin/Health 용 통합 Release Readiness 리포트."""

    validation = run_startup_configuration_validation(session)
    ops = build_operation_dashboard_slice(session)
    return {
        "release": "v1.2",
        "operation_ready": (
            validation.get("overall") in {"PASS", "WARN"}
            and bool(validation.get("fail_closed", {}).get("live_submit_blocked"))
            and str(validation.get("lifecycle", {}).get("status")) == "PASS"
        ),
        "validation": validation,
        "operations": ops,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
