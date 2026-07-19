"""알림 이벤트 타입 · 레벨 정의 (STEP54)."""

from __future__ import annotations

from enum import IntEnum, StrEnum


class NotificationEventType(StrEnum):
    SYSTEM_START = "SYSTEM_START"
    SYSTEM_STOP = "SYSTEM_STOP"
    ORDER_SUBMITTED = "ORDER_SUBMITTED"
    ORDER_FILLED = "ORDER_FILLED"
    ORDER_REJECTED = "ORDER_REJECTED"
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"
    TRAILING_STOP = "TRAILING_STOP"
    RELATIVE_LOSS = "RELATIVE_LOSS"
    KILL_SWITCH = "KILL_SWITCH"
    DAILY_LOSS = "DAILY_LOSS"
    AI_ANALYSIS_COMPLETE = "AI_ANALYSIS_COMPLETE"
    BACKTEST_COMPLETE = "BACKTEST_COMPLETE"
    BROKER_DISCONNECTED = "BROKER_DISCONNECTED"
    BROKER_RECONNECTED = "BROKER_RECONNECTED"
    DATABASE_ERROR = "DATABASE_ERROR"
    SCHEDULER_ERROR = "SCHEDULER_ERROR"


class NotificationLevel(IntEnum):
    """낮을수록 더 많은 이벤트를 보낸다 (INFO ⊃ WARN ⊃ CRITICAL)."""

    INFO = 10
    WARN = 20
    CRITICAL = 30


# 이벤트별 최소 레벨
EVENT_LEVELS: dict[str, NotificationLevel] = {
    NotificationEventType.SYSTEM_START: NotificationLevel.INFO,
    NotificationEventType.SYSTEM_STOP: NotificationLevel.INFO,
    NotificationEventType.ORDER_SUBMITTED: NotificationLevel.INFO,
    NotificationEventType.ORDER_FILLED: NotificationLevel.INFO,
    NotificationEventType.ORDER_REJECTED: NotificationLevel.WARN,
    NotificationEventType.STOP_LOSS: NotificationLevel.WARN,
    NotificationEventType.TAKE_PROFIT: NotificationLevel.INFO,
    NotificationEventType.TRAILING_STOP: NotificationLevel.WARN,
    NotificationEventType.RELATIVE_LOSS: NotificationLevel.WARN,
    NotificationEventType.KILL_SWITCH: NotificationLevel.CRITICAL,
    NotificationEventType.DAILY_LOSS: NotificationLevel.CRITICAL,
    NotificationEventType.AI_ANALYSIS_COMPLETE: NotificationLevel.INFO,
    NotificationEventType.BACKTEST_COMPLETE: NotificationLevel.INFO,
    NotificationEventType.BROKER_DISCONNECTED: NotificationLevel.CRITICAL,
    NotificationEventType.BROKER_RECONNECTED: NotificationLevel.INFO,
    NotificationEventType.DATABASE_ERROR: NotificationLevel.CRITICAL,
    NotificationEventType.SCHEDULER_ERROR: NotificationLevel.CRITICAL,
}


def parse_notification_level(raw: str) -> NotificationLevel:
    normalized = (raw or "INFO").strip().upper()
    mapping = {
        "INFO": NotificationLevel.INFO,
        "WARN": NotificationLevel.WARN,
        "WARNING": NotificationLevel.WARN,
        "CRITICAL": NotificationLevel.CRITICAL,
        "ERROR": NotificationLevel.CRITICAL,
    }
    return mapping.get(normalized, NotificationLevel.INFO)


def should_dispatch_event(
    event_type: str,
    configured_level: NotificationLevel,
) -> bool:
    """설정된 레벨 이상의 이벤트만 채널로 전달한다."""

    event_level = EVENT_LEVELS.get(
        event_type,
        NotificationLevel.INFO,
    )
    return event_level >= configured_level
