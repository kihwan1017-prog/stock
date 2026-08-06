"""STEP 8-7 — LIVE 주문 안전 게이트 Audit / Telegram 헬퍼."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

# 표준 reject/approve 이벤트 타입
LIVE_APPROVED = "LIVE_APPROVED"
LIVE_REJECTED = "LIVE_REJECTED"
ORDER_AMOUNT_REJECT = "ORDER_AMOUNT_REJECT"
ORDER_QTY_REJECT = "ORDER_QTY_REJECT"
DAILY_LIMIT_REJECT = "DAILY_LIMIT_REJECT"
LOSS_LIMIT_REJECT = "LOSS_LIMIT_REJECT"
DUPLICATE_ORDER_REJECT = "DUPLICATE_ORDER_REJECT"
MARKET_TIME_REJECT = "MARKET_TIME_REJECT"
BROKER_HEALTH_REJECT = "BROKER_HEALTH_REJECT"
LIVE_ORDER_SUBMITTED = "LIVE_ORDER_SUBMITTED"
# STEP 8-8 — ARM 이벤트 (ARM_ON/OFF 가 공식값, LIVE_ARM 은 호환 alias)
ARM_ON = "ARM_ON"
ARM_OFF = "ARM_OFF"
LIVE_ARM = ARM_ON
LIVE_DISARM = ARM_OFF
LIVE_ARM_EXPIRED = "LIVE_ARM_EXPIRED"
OPEN_ORDER_LIMIT = "OPEN_ORDER_LIMIT"
SLIPPAGE_REJECT = "SLIPPAGE_REJECT"
POSITION_MISMATCH = "POSITION_MISMATCH"
CASH_MISMATCH = "CASH_MISMATCH"
BROKER_DISCONNECTED = "BROKER_DISCONNECTED"
BROKER_RECOVERED = "BROKER_RECOVERED"
LOOP_DETECTED = "LOOP_DETECTED"
ANOMALY_ORDER_RATE = "ANOMALY_ORDER_RATE"
ARM_TOKEN_REJECT = "ARM_TOKEN_REJECT"


def emit_live_safety_audit(
    session: Session,
    *,
    event_type: str,
    actor: str,
    run_id: str | None,
    user_id: int | None,
    account_id: int | None,
    strategy_id: str | None,
    symbol: str | None = None,
    order_id: int | None = None,
    client_order_id: str | None = None,
    detail: dict[str, Any] | None = None,
    commit: bool = True,
) -> None:
    """민감정보 없이 Audit 기록. commit=False면 flush만."""

    from stock_platform.operation.audit_models import AuditEvent

    payload = dict(detail or {})
    # 식별자는 detail에도 중복 보관 (조회·보고서용)
    if user_id is not None:
        payload.setdefault("user_id", int(user_id))
    if account_id is not None:
        payload.setdefault("account_id", int(account_id))
        payload.setdefault("user_broker_account_id", int(account_id))
    if strategy_id:
        payload.setdefault("strategy_id", strategy_id)
    if run_id:
        payload.setdefault("run_id", run_id)

    # 토큰·계좌번호 원문 등 금지 키 제거
    for banned in (
        "token",
        "arm_token",
        "access_token",
        "refresh_token",
        "password",
        "account_number",
        "secret",
        "secret_key",
        "api_key",
        "api_secret",
        "access_key",
        "authorization",
        "Authorization",
    ):
        payload.pop(banned, None)

    entity = AuditEvent(
        event_type=event_type,
        actor=actor or "LIVE_SAFETY",
        request_id=None,
        run_id=run_id,
        strategy_id=strategy_id,
        account_hash=(
            f"UBA:{account_id}" if account_id is not None else None
        ),
        order_id=order_id,
        client_order_id=client_order_id,
        symbol=symbol,
        detail=payload,
        created_at=datetime.now(timezone.utc),
    )
    session.add(entity)
    session.flush()
    if commit:
        session.commit()


def emit_live_order_telegram(
    *,
    event_type: str,
    title: str,
    message: str,
    detail: dict[str, Any],
) -> None:
    """실주문/거절 Telegram — 실패해도 주문 경로를 깨지 않음."""

    safe_detail = {
        k: v
        for k, v in (detail or {}).items()
        if k.lower()
        not in {
            "token",
            "arm_token",
            "access_token",
            "refresh_token",
            "password",
            "secret",
            "secret_key",
            "api_key",
            "api_secret",
            "access_key",
            "authorization",
        }
    }

    try:
        from stock_platform.notification.events import (
            NotificationEventType,
        )
        from stock_platform.notification.publisher import (
            notification_publisher,
        )

        mapped = event_type
        if event_type in {
            LIVE_REJECTED,
            ORDER_AMOUNT_REJECT,
            ORDER_QTY_REJECT,
            DAILY_LIMIT_REJECT,
            LOSS_LIMIT_REJECT,
            DUPLICATE_ORDER_REJECT,
            MARKET_TIME_REJECT,
            BROKER_HEALTH_REJECT,
            OPEN_ORDER_LIMIT,
            SLIPPAGE_REJECT,
            ARM_TOKEN_REJECT,
            LOOP_DETECTED,
            ANOMALY_ORDER_RATE,
            LIVE_ARM_EXPIRED,
        }:
            mapped = NotificationEventType.ORDER_REJECTED.value
        elif event_type in {LIVE_ORDER_SUBMITTED, LIVE_APPROVED, LIVE_ARM}:
            mapped = NotificationEventType.ORDER_SUBMITTED.value
        elif event_type in {LIVE_DISARM}:
            mapped = NotificationEventType.MONITORING_ALERT.value
        elif event_type in {POSITION_MISMATCH, CASH_MISMATCH}:
            mapped = NotificationEventType.KILL_SWITCH.value
        elif event_type in {
            "POST_FILL_MISMATCH",
            "POST_FILL_VERIFY_EXPIRED",
            "POST_FILL_VERIFY_FAILED",
        }:
            mapped = NotificationEventType.KILL_SWITCH.value
        elif event_type in {
            "POST_FILL_BROKER_DOWN_DELAY",
            "POST_FILL_SNAPSHOT_STALE",
            "POST_FILL_RETRY_SCHEDULED",
        }:
            mapped = NotificationEventType.MONITORING_ALERT.value
        elif event_type in {"POST_FILL_VERIFIED", "POST_FILL_VERIFY_PENDING"}:
            mapped = NotificationEventType.MONITORING_ALERT.value
        elif event_type == BROKER_DISCONNECTED:
            mapped = NotificationEventType.BROKER_DISCONNECTED.value
        elif event_type == BROKER_RECOVERED:
            mapped = NotificationEventType.BROKER_RECONNECTED.value
        elif event_type in {"SCHEDULER_PAUSE", "SCHEDULER_RESUME"}:
            mapped = NotificationEventType.SCHEDULER_ERROR.value
        elif event_type in {"KILL_SWITCH", "KILL_SWITCH_ACTIVATE"}:
            mapped = NotificationEventType.KILL_SWITCH.value

        publisher = notification_publisher
        publisher.publish(
            event_type=mapped,
            title=title,
            message=message,
            detail=safe_detail,
            dispatch=True,
        )
    except Exception:  # noqa: BLE001
        pass
