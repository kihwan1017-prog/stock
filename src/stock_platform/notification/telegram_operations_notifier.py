"""STEP 10-4 — Telegram 운영 알림 포맷 (Publisher 재사용)."""

from __future__ import annotations

from typing import Any

from stock_platform.notification.events import (
    NotificationEventType,
    NotificationLevel,
)
from stock_platform.notification.publisher import notification_publisher


def _health_emoji(status: str | None) -> str:
    s = str(status or "").upper()
    if s in {"HEALTHY", "OK", "RUNNING", "CONNECTED", "OFF", "INACTIVE"}:
        return "🟢"
    if s in {"WARNING", "DEGRADED", "PAUSED", "STALE", "ON"}:
        return "🟡"
    if s in {"ERROR", "CRITICAL", "FAILED", "BLOCKED", "ACTIVE"}:
        return "🔴"
    return "⚪"


async def notify_operational_event(
    *,
    event_type: str,
    title: str,
    message: str,
    detail: dict[str, Any] | None = None,
    level: NotificationLevel = NotificationLevel.INFO,
) -> None:
    """도메인 → Telegram (NotificationPublisher 경로, 토큰 미포함)."""

    await notification_publisher.publish_async(
        event_type=event_type,
        title=title,
        message=message,
        detail={**(detail or {}), "source": "telegram_ops_center"},
        level=level,
    )


async def notify_order_event(
    *,
    status: str,
    order_id: int | None = None,
    market: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    mapping = {
        "SUBMITTED": (
            NotificationEventType.ORDER_SUBMITTED,
            NotificationLevel.INFO,
        ),
        "FILLED": (
            NotificationEventType.ORDER_FILLED,
            NotificationLevel.INFO,
        ),
        "PARTIAL": (
            NotificationEventType.ORDER_PARTIAL_FILLED,
            NotificationLevel.INFO,
        ),
        "PARTIALLY_FILLED": (
            NotificationEventType.ORDER_PARTIAL_FILLED,
            NotificationLevel.INFO,
        ),
        "CANCELLED": (
            NotificationEventType.ORDER_CANCELLED,
            NotificationLevel.WARN,
        ),
        "REJECTED": (
            NotificationEventType.ORDER_REJECTED,
            NotificationLevel.WARN,
        ),
    }
    key = status.upper()
    event_type, level = mapping.get(
        key,
        (NotificationEventType.MONITORING_ALERT, NotificationLevel.INFO),
    )
    msg = f"Order {status}"
    if order_id is not None:
        msg += f" #{order_id}"
    if market:
        msg += f" {market}"
    await notify_operational_event(
        event_type=str(event_type),
        title=f"Order {status}",
        message=msg,
        detail={
            "order_id": order_id,
            "market": market,
            **(detail or {}),
        },
        level=level,
    )


def format_dashboard_summary_html(summary: dict[str, Any]) -> str:
    """STEP 10-3 Summary → Telegram HTML."""

    system = summary.get("system") or {}
    safety = summary.get("safety") or {}
    runtime = summary.get("runtime") or {}
    sched = (runtime.get("scheduler") or {}) if isinstance(runtime, dict) else {}
    broker = summary.get("broker") or {}
    live = (safety.get("live") or {}).get("status", "OFF")
    arm = (safety.get("arm") or {}).get("status", "OFF")

    lines = [
        "━━━━━━━━━━━━━━",
        "<b>SYSTEM</b>",
        f"{_health_emoji(system.get('api_status'))} API",
        f"{_health_emoji((system.get('database') or {}).get('status'))} DB",
    ]
    recovery = (runtime.get("recovery") or {}) if isinstance(runtime, dict) else {}
    lines.append(
        f"{_health_emoji(recovery.get('actual_state'))} Recovery"
    )
    lines.append(
        f"{_health_emoji(sched.get('actual_state'))} Scheduler"
    )
    lines.extend(
        [
            "━━━━━━━━━━━━━━",
            "<b>Trading</b>",
            f"LIVE {live}",
            f"ARM {arm}",
            "━━━━━━━━━━━━━━",
            "<b>Broker</b>",
        ]
    )
    for code, row in broker.items():
        if not isinstance(row, dict):
            continue
        health = row.get("health") or row.get("status")
        lines.append(f"{code}\n{_health_emoji(health)} {health}")
    lines.append("━━━━━━━━━━━━━━")
    return "\n".join(lines)
