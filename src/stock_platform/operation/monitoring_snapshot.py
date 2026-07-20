"""통합 모니터링 스냅샷 + Alert 평가 (STEP61).

자동매매 로직을 변경하지 않는다. 읽기 전용 집계 + 알림/감사만 수행.
"""

from __future__ import annotations

import time
from datetime import date, datetime, time as dt_time, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stock_platform.common.settings import get_settings
from stock_platform.common.ttl_cache import process_ttl_cache
from stock_platform.operation.db_pool_monitor import (
    build_database_monitoring,
)
from stock_platform.operation.exception_rate import (
    exception_rate_tracker,
)
from stock_platform.operation.resource_monitor import (
    build_resource_monitoring,
)
from stock_platform.operation.runtime_info import (
    build_system_identity,
)
from stock_platform.trading.account_models import PaperPosition
from stock_platform.trading.models import (
    OrderStatus,
    PaperOrder,
)


ZERO = Decimal("0")
_SNAPSHOT_TTL = 8.0
_ALERT_DEDUP_TTL = 300.0


def _safe(exc: Exception) -> str:
    text = str(exc)
    return text[:200] + ("..." if len(text) > 200 else "")


def _broker_monitoring() -> dict[str, Any]:
    settings = get_settings()
    payload: dict[str, Any] = {
        "use_mock": settings.kiwoom_use_mock,
        "live_order_enabled": settings.kiwoom_live_order_enabled,
        "account_configured": bool(
            settings.kiwoom_account_number.strip()
        ),
        "app_key_configured": bool(
            settings.kiwoom_app_key.strip()
        ),
        "login_status": (
            "CONFIGURED"
            if settings.kiwoom_app_key.strip()
            else "NOT_CONFIGURED"
        ),
        "order_api_status": (
            "MOCK"
            if settings.kiwoom_use_mock
            else (
                "LIVE"
                if settings.kiwoom_live_order_enabled
                else "REST_ONLY"
            )
        ),
        "market_api_status": (
            "CONFIGURED"
            if settings.kiwoom_app_key.strip()
            else "SKIPPED"
        ),
    }
    try:
        from stock_platform.broker.kiwoom.ws_manager import (
            kiwoom_order_websocket_manager,
        )
        from stock_platform.broker.recovery_runtime import (
            broker_recovery_manager,
        )

        ws = kiwoom_order_websocket_manager.status()
        recovery = broker_recovery_manager.status()
        connected = bool(ws.get("connected"))
        payload.update(
            {
                "broker_connected": connected,
                "websocket": ws,
                "last_heartbeat": ws.get("last_heartbeat")
                or ws.get("last_pong_at")
                or ws.get("connected_at"),
                "recovery": recovery,
                "status": "UP" if connected or settings.kiwoom_use_mock else "DOWN",
            }
        )
        # mock이면 WS 없이도 UP 취급
        if settings.kiwoom_use_mock:
            payload["status"] = "UP"
            payload["broker_connected"] = payload.get(
                "broker_connected", True
            )
    except Exception as exc:
        payload["status"] = "UNKNOWN"
        payload["message"] = _safe(exc)
    return payload


def _probe_scheduler_object(obj: Any) -> dict[str, Any]:
    """status() 또는 AsyncIOScheduler.running 폴백."""

    if hasattr(obj, "status") and callable(obj.status):
        raw = obj.status()
        return raw if isinstance(raw, dict) else {"raw": raw}

    task = getattr(obj, "_task", None)
    if task is not None:
        running = not task.done()
        return {"running": running, "enabled": True}

    inner = getattr(obj, "scheduler", None) or getattr(
        obj, "_scheduler", None
    )
    if inner is not None:
        jobs = []
        try:
            for job in inner.get_jobs():
                jobs.append(
                    {
                        "id": job.id,
                        "next_run": (
                            job.next_run_time.isoformat()
                            if job.next_run_time
                            else None
                        ),
                    }
                )
        except Exception:
            jobs = []
        return {
            "running": bool(getattr(inner, "running", False)),
            "enabled": True,
            "jobs": jobs,
            "next_run": jobs[0]["next_run"] if jobs else None,
        }
    return {"running": False, "message": "no status probe"}


def _scheduler_monitoring() -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    failure_total = 0

    def _add(name: str, obj: Any) -> None:
        nonlocal failure_total
        try:
            raw = _probe_scheduler_object(obj)
            running = bool(
                raw.get("running")
                or raw.get("enabled")
                or raw.get("started")
            )
            failures = int(
                raw.get("failure_count")
                or raw.get("consecutive_failures")
                or 0
            )
            failure_total += failures
            items.append(
                {
                    "name": name,
                    "running": running,
                    "last_run": raw.get("last_run")
                    or raw.get("last_run_at")
                    or raw.get("last_finished_at"),
                    "next_run": raw.get("next_run")
                    or raw.get("next_run_at"),
                    "duration_seconds": raw.get(
                        "last_duration_seconds"
                    )
                    or raw.get("duration_seconds"),
                    "failure_count": failures,
                    "detail": {
                        k: raw[k]
                        for k in (
                            "enabled",
                            "interval_seconds",
                            "last_error",
                            "jobs",
                        )
                        if k in raw
                    },
                }
            )
        except Exception as exc:
            items.append(
                {
                    "name": name,
                    "running": False,
                    "failure_count": 1,
                    "message": _safe(exc),
                }
            )
            failure_total += 1

    try:
        from stock_platform.order.outbox_runtime import (
            order_outbox_scheduler,
        )
        from stock_platform.position.exit_monitor_scheduler import (
            position_exit_monitor_scheduler,
        )
        from stock_platform.risk_engine.daily_loss_scheduler import (
            daily_loss_monitor_scheduler,
        )
        from stock_platform.notification.telegram_polling import (
            telegram_ops_poller,
            telegram_ops_scheduler,
        )
        from stock_platform.realtime.session_runtime import (
            realtime_trading_scheduler,
        )
        from stock_platform.strategy_deployment.performance_monitor_scheduler import (
            deployment_performance_monitor_scheduler,
        )
        from stock_platform.strategy_deployment.pipeline_scheduler import (
            strategy_deployment_pipeline_scheduler,
        )
        from stock_platform.strategy_deployment.policy_scheduler import (
            strategy_approval_scheduler,
        )
        from stock_platform.strategy_deployment.reload_scheduler import (
            strategy_runtime_reload_scheduler,
        )

        _add("order_outbox", order_outbox_scheduler)
        _add("position_exit_monitor", position_exit_monitor_scheduler)
        _add("daily_loss_monitor", daily_loss_monitor_scheduler)
        _add("telegram_ops", telegram_ops_scheduler)
        # poller 자체 last_error 도 반영
        try:
            poll = telegram_ops_poller.status()
            if poll.get("last_error"):
                failure_total += 1
                for item in items:
                    if item["name"] == "telegram_ops":
                        item["failure_count"] = (
                            int(item.get("failure_count") or 0) + 1
                        )
                        item.setdefault("detail", {})[
                            "last_error"
                        ] = poll.get("last_error")
        except Exception:
            pass
        _add("realtime_trading", realtime_trading_scheduler)
        _add(
            "deployment_performance",
            deployment_performance_monitor_scheduler,
        )
        _add(
            "strategy_deployment_pipeline",
            strategy_deployment_pipeline_scheduler,
        )
        _add("strategy_approval", strategy_approval_scheduler)
        _add(
            "strategy_runtime_reload",
            strategy_runtime_reload_scheduler,
        )
    except Exception as exc:
        return {
            "status": "UNKNOWN",
            "message": _safe(exc),
            "schedulers": items,
            "failure_count": failure_total,
        }

    settings = get_settings()
    overall = "UP"
    if failure_total > 0:
        overall = "DEGRADED"
    if not settings.scheduler_enabled:
        overall = "DISABLED"

    return {
        "status": overall,
        "scheduler_enabled": settings.scheduler_enabled,
        "failure_count": failure_total,
        "schedulers": items,
    }


def _ai_monitoring() -> dict[str, Any]:
    settings = get_settings()
    started = time.perf_counter()
    try:
        from stock_platform.operation.health_service import (
            check_ollama,
        )

        result = check_ollama()
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return {
            "status": result.get("status", "UNKNOWN"),
            "model": settings.ollama_model,
            "base_url": settings.ollama_base_url,
            "response_time_ms": round(elapsed_ms, 2),
            "timeout_seconds": settings.ollama_timeout_seconds,
            "queue_length": None,  # Ollama 공개 queue API 없음
            "model_count": result.get("model_count"),
            "recent_error": result.get("message"),
        }
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return {
            "status": "DOWN",
            "model": settings.ollama_model,
            "response_time_ms": round(elapsed_ms, 2),
            "timeout_seconds": settings.ollama_timeout_seconds,
            "queue_length": None,
            "recent_error": _safe(exc),
        }


def _telegram_monitoring() -> dict[str, Any]:
    settings = get_settings()
    payload: dict[str, Any] = {
        "enabled": settings.telegram_enabled,
        "ops_enabled": settings.telegram_ops_enabled,
        "bot_connected": False,
        "last_sent_at": None,
        "last_failed_at": None,
        "retry_count": 0,
        "status": "DISABLED",
    }
    try:
        from stock_platform.notification.runtime import (
            notification_service,
        )
        from stock_platform.notification.telegram_polling import (
            telegram_ops_poller,
        )

        status = notification_service.status()
        channels = status.get("channels") or {}
        channel_list = channels.get("channels")
        if not isinstance(channel_list, list):
            channel_list = (
                channels if isinstance(channels, list) else []
            )

        telegram_block: dict[str, Any] = {}
        for item in channel_list:
            if not isinstance(item, dict):
                continue
            blob = str(item).lower()
            if "telegram" in blob:
                telegram_block = item
                break

        poller = telegram_ops_poller.status()
        last_error = telegram_block.get("last_error") or poller.get(
            "last_error"
        )
        retry_count = int(
            telegram_block.get("retry_count")
            or telegram_block.get("consecutive_failures")
            or telegram_block.get("failure_count")
            or 0
        )
        payload.update(
            {
                "bot_connected": bool(
                    settings.telegram_enabled
                    and settings.telegram_bot_token.strip()
                    and not last_error
                ),
                "last_sent_at": telegram_block.get("last_sent_at"),
                "last_failed_at": (
                    None
                    if not last_error
                    else datetime.now(timezone.utc).isoformat()
                ),
                "last_error": last_error,
                "retry_count": retry_count,
                "poller": poller,
                "status": (
                    "UP"
                    if settings.telegram_enabled and not last_error
                    else (
                        "DISABLED"
                        if not settings.telegram_enabled
                        else "DEGRADED"
                    )
                ),
            }
        )
    except Exception as exc:
        payload["status"] = "UNKNOWN"
        payload["message"] = _safe(exc)
    return payload


def _order_monitoring(session: Session) -> dict[str, Any]:
    today = date.today()
    start = datetime.combine(today, dt_time.min).replace(
        tzinfo=timezone.utc
    )
    try:
        rows = session.execute(
            select(PaperOrder.status_code, func.count())
            .where(PaperOrder.created_at >= start)
            .group_by(PaperOrder.status_code)
        ).all()
        counts = {str(status): int(count) for status, count in rows}
        filled = counts.get(OrderStatus.FILLED.value, 0)
        # 평균 체결시간 근사: updated_at - created_at (FILLED)
        avg_fill_seconds = None
        avg_row = session.execute(
            select(
                func.avg(
                    func.extract(
                        "epoch",
                        PaperOrder.updated_at
                        - PaperOrder.created_at,
                    )
                )
            ).where(
                PaperOrder.created_at >= start,
                PaperOrder.status_code
                == OrderStatus.FILLED.value,
            )
        ).scalar()
        if avg_row is not None:
            avg_fill_seconds = round(float(avg_row), 2)

        total = sum(counts.values())
        return {
            "status": "UP",
            "today_orders": total,
            "filled": filled,
            "partially_filled": counts.get(
                OrderStatus.PARTIALLY_FILLED.value, 0
            ),
            "open_unfilled": (
                counts.get(OrderStatus.CREATED.value, 0)
                + counts.get(OrderStatus.ACCEPTED.value, 0)
                + counts.get(
                    OrderStatus.PARTIALLY_FILLED.value, 0
                )
            ),
            "rejected": counts.get(OrderStatus.REJECTED.value, 0),
            "cancelled": counts.get(
                OrderStatus.CANCELLED.value, 0
            ),
            "avg_fill_seconds": avg_fill_seconds,
            "by_status": counts,
        }
    except Exception as exc:
        return {"status": "UNKNOWN", "message": _safe(exc)}


def _position_monitoring(session: Session) -> dict[str, Any]:
    try:
        positions = list(
            session.scalars(
                select(PaperPosition).where(
                    PaperPosition.quantity > 0
                )
            )
        )
        symbol_count = len(positions)
        # 평가손익: 시세 조회 없이 cost 기반 0 (성능). 상세는 risk dashboard 사용
        costs: list[Decimal] = []
        for pos in positions:
            cost = (
                Decimal(pos.quantity)
                * Decimal(pos.average_entry_price)
            )
            costs.append(cost)
        total_cost = sum(costs, ZERO)
        return {
            "status": "UP",
            "symbol_count": symbol_count,
            "total_cost_basis": float(total_cost),
            "unrealized_pnl": None,
            "total_return_rate": None,
            "max_loss": None,
            "max_profit": None,
            "note": (
                "PnL mark-to-market는 /dashboard/risk · "
                "admin-summary 사용 (모니터링은 경량)"
            ),
        }
    except Exception as exc:
        return {"status": "UNKNOWN", "message": _safe(exc)}


def _risk_monitoring(session: Session) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kill_switch": None,
        "daily_loss": None,
        "stop_loss_count": 0,
        "take_profit_count": 0,
        "trailing_stop_count": 0,
        "status": "UP",
    }
    try:
        from stock_platform.risk_engine.kill_switch_service import (
            KillSwitchService,
        )
        from stock_platform.risk_engine.daily_loss_runtime import (
            daily_loss_monitor_manager,
        )
        from stock_platform.notification.history import (
            notification_history,
        )
        from stock_platform.notification.events import (
            NotificationEventType,
        )

        kill = KillSwitchService(session).get_state()
        payload["kill_switch"] = {
            "status": getattr(
                kill.status, "value", str(kill.status)
            ),
            "reason": kill.reason,
            "activated_at": (
                kill.activated_at.isoformat()
                if kill.activated_at
                else None
            ),
        }
        daily = daily_loss_monitor_manager.status()
        payload["daily_loss"] = daily

        today = date.today()
        for record in notification_history.recent(limit=200):
            created = getattr(record, "created_at", None)
            if created is None:
                continue
            created_utc = (
                created
                if created.tzinfo
                else created.replace(tzinfo=timezone.utc)
            )
            if created_utc.astimezone(timezone.utc).date() != today:
                continue
            et = str(getattr(record, "event_type", ""))
            if et == NotificationEventType.STOP_LOSS:
                payload["stop_loss_count"] += 1
            elif et == NotificationEventType.TAKE_PROFIT:
                payload["take_profit_count"] += 1
            elif et == NotificationEventType.TRAILING_STOP:
                payload["trailing_stop_count"] += 1

        if str(payload["kill_switch"]["status"]).upper() == "ACTIVE":
            payload["status"] = "CRITICAL"
    except Exception as exc:
        payload["status"] = "UNKNOWN"
        payload["message"] = _safe(exc)
    return payload


def evaluate_alert_rules(
    snapshot: dict[str, Any],
    *,
    session: Session | None = None,
    dispatch: bool = True,
) -> list[dict[str, Any]]:
    """스냅샷 기반 Alert 생성 → Audit(+선택 Notification)."""

    from stock_platform.notification.events import (
        NotificationEventType,
    )
    from stock_platform.notification.publisher import (
        notification_publisher,
    )
    from stock_platform.operation.audit_repository import (
        AuditEventRepository,
    )

    fired: list[dict[str, Any]] = []

    def _fire(
        rule_id: str,
        *,
        event_type: str,
        title: str,
        message: str,
        severity: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        dedup_key = f"alert:{rule_id}"
        if process_ttl_cache.get(dedup_key) is not None:
            return
        process_ttl_cache.set(
            dedup_key, True, ttl_seconds=_ALERT_DEDUP_TTL
        )
        body = {
            "rule_id": rule_id,
            "severity": severity,
            "title": title,
            "message": message,
            "detail": detail or {},
            "fired_at": datetime.now(timezone.utc).isoformat(),
        }
        fired.append(body)

        if session is not None:
            AuditEventRepository(session).create(
                event_type=f"MONITORING_ALERT:{rule_id}",
                actor="system:monitoring",
                request_id=None,
                run_id=None,
                strategy_id=None,
                account_hash=None,
                order_id=None,
                client_order_id=None,
                symbol=None,
                detail=body,
                created_at=datetime.now(timezone.utc),
            )

        if dispatch:
            try:
                notification_publisher.publish(
                    event_type=event_type,
                    title=title,
                    message=message,
                    detail=body,
                )
            except Exception:
                pass

    db = snapshot.get("database") or {}
    if str(db.get("status", "")).upper() == "DOWN":
        _fire(
            "DB_DOWN",
            event_type=NotificationEventType.DATABASE_ERROR,
            title="DB Down",
            message="Database health check failed",
            severity="CRITICAL",
            detail=db,
        )

    broker = snapshot.get("broker") or {}
    if (
        str(broker.get("status", "")).upper() == "DOWN"
        and not bool(broker.get("use_mock"))
    ):
        _fire(
            "BROKER_DISCONNECT",
            event_type=NotificationEventType.BROKER_DISCONNECTED,
            title="Broker Disconnect",
            message="Broker websocket/API appears disconnected",
            severity="CRITICAL",
            detail={
                "broker_connected": broker.get("broker_connected"),
            },
        )

    sched = snapshot.get("scheduler") or {}
    if int(sched.get("failure_count") or 0) > 0:
        _fire(
            "SCHEDULER_FAILURE",
            event_type=NotificationEventType.SCHEDULER_ERROR,
            title="Scheduler Failure",
            message=f"Scheduler failure_count={sched.get('failure_count')}",
            severity="CRITICAL",
            detail={"failure_count": sched.get("failure_count")},
        )

    ai = snapshot.get("ai") or {}
    timeout_s = float(ai.get("timeout_seconds") or 120)
    resp_ms = ai.get("response_time_ms")
    if str(ai.get("status", "")).upper() == "DOWN" or (
        resp_ms is not None and float(resp_ms) > timeout_s * 1000
    ):
        _fire(
            "AI_TIMEOUT",
            event_type=NotificationEventType.AI_TIMEOUT,
            title="AI Timeout / Down",
            message="Ollama status DOWN or response exceeded timeout",
            severity="WARN",
            detail=ai,
        )

    tg = snapshot.get("telegram") or {}
    if (
        bool(tg.get("enabled"))
        and str(tg.get("status", "")).upper() == "DEGRADED"
    ):
        _fire(
            "TELEGRAM_FAILURE",
            event_type=NotificationEventType.TELEGRAM_FAILURE,
            title="Telegram Failure",
            message=str(tg.get("last_error") or "telegram degraded"),
            severity="WARN",
            detail=tg,
        )

    risk = snapshot.get("risk") or {}
    kill = risk.get("kill_switch") or {}
    if str(kill.get("status", "")).upper() == "ACTIVE":
        _fire(
            "KILL_SWITCH_ACTIVATED",
            event_type=NotificationEventType.KILL_SWITCH,
            title="Kill Switch Activated",
            message=str(kill.get("reason") or "kill switch active"),
            severity="CRITICAL",
            detail=kill,
        )

    daily = risk.get("daily_loss") or {}
    last_snap = daily.get("last_snapshot")
    snap_dict: dict[str, Any] = {}
    if isinstance(last_snap, dict):
        snap_dict = last_snap
    elif last_snap is not None:
        snap_dict = {
            "triggered": getattr(last_snap, "triggered", None),
            "status": getattr(
                getattr(last_snap, "status", None),
                "value",
                getattr(last_snap, "status", None),
            ),
        }
    if (
        snap_dict.get("triggered")
        or str(snap_dict.get("status", "")).upper()
        in {"TRIGGERED", "BREACHED", "ACTIVE"}
    ):
        _fire(
            "DAILY_LOSS_TRIGGER",
            event_type=NotificationEventType.DAILY_LOSS,
            title="Daily Loss Trigger",
            message="Daily loss monitor triggered",
            severity="CRITICAL",
            detail={"daily_loss": str(daily)[:500]},
        )

    exc_snap = snapshot.get("exception_rate") or {}
    if float(exc_snap.get("rate_per_minute") or 0) >= 5.0:
        _fire(
            "EXCEPTION_RATE_HIGH",
            event_type=NotificationEventType.MONITORING_ALERT,
            title="Exception Rate High",
            message=(
                f"exception rate_per_minute="
                f"{exc_snap.get('rate_per_minute')}"
            ),
            severity="WARN",
            detail=exc_snap,
        )

    return fired


async def build_monitoring_overview(
    session: Session,
    *,
    evaluate_alerts: bool = True,
    use_cache: bool = True,
) -> dict[str, Any]:
    cache_key = "monitoring:overview"
    if use_cache:
        cached = process_ttl_cache.get(cache_key)
        if cached is not None:
            return cached

    snapshot: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "system": build_system_identity(),
        "database": build_database_monitoring(),
        "broker": _broker_monitoring(),
        "scheduler": _scheduler_monitoring(),
        "ai": _ai_monitoring(),
        "telegram": _telegram_monitoring(),
        "orders": _order_monitoring(session),
        "positions": _position_monitoring(session),
        "risk": _risk_monitoring(session),
        "resources": build_resource_monitoring(),
        "exception_rate": exception_rate_tracker.snapshot(),
    }

    alerts: list[dict[str, Any]] = []
    if evaluate_alerts:
        alerts = evaluate_alert_rules(
            snapshot,
            session=session,
            dispatch=True,
        )
    snapshot["alerts"] = {
        "fired_now": alerts,
        "rules": [
            "DB_DOWN",
            "BROKER_DISCONNECT",
            "SCHEDULER_FAILURE",
            "AI_TIMEOUT",
            "TELEGRAM_FAILURE",
            "DAILY_LOSS_TRIGGER",
            "KILL_SWITCH_ACTIVATED",
            "EXCEPTION_RATE_HIGH",
        ],
        "dedup_seconds": _ALERT_DEDUP_TTL,
    }

    # 전체 상태
    overall = "UP"
    for key in ("database", "broker", "scheduler", "risk"):
        st = str((snapshot.get(key) or {}).get("status", "")).upper()
        if st in {"DOWN", "CRITICAL", "ERROR", "FAILED"}:
            overall = "CRITICAL" if st == "CRITICAL" else "DEGRADED"
            if overall == "CRITICAL":
                break
        elif st == "DEGRADED" and overall == "UP":
            overall = "DEGRADED"
    snapshot["status"] = overall

    process_ttl_cache.set(
        cache_key, snapshot, ttl_seconds=_SNAPSHOT_TTL
    )
    return snapshot
