"""Portfolio WAITING_SIGNAL 교체 Telegram 알림 (상태 변화 1회)."""

from __future__ import annotations

from typing import Any

import structlog

from stock_platform.notification.events import NotificationEventType
from stock_platform.notification.publisher import notification_publisher

logger = structlog.get_logger(__name__)

EVENT_SLOT_REPLACED = "UPBIT_PORTFOLIO_CANDIDATE_REPLACED"


def publish_slot_replacement_alert(
    *,
    user_broker_account_id: int,
    old_symbol: str,
    new_symbol: str,
    old_score: float | None,
    new_score: float | None,
    reason: str | None,
    reason_display: str,
    slot_no: int,
    scanner_run_id: str,
) -> dict[str, Any]:
    """🔄 자동매매 후보 교체 — REAL 주문 없음."""

    event_type = str(
        getattr(
            NotificationEventType,
            "UPBIT_PORTFOLIO_CANDIDATE_REPLACED",
            EVENT_SLOT_REPLACED,
        )
    )
    old_s = f"{float(old_score):.2f}" if old_score is not None else "-"
    new_s = f"{float(new_score):.2f}" if new_score is not None else "-"
    title = "🔄 자동매매 후보 교체"
    message = (
        f"기존 종목: {old_symbol}\n"
        f"신규 종목: {new_symbol}\n"
        f"기존 점수: {old_s}\n"
        f"신규 점수: {new_s}\n"
        f"사유: {reason_display}\n"
        f"슬롯: {slot_no}\n"
        f"REAL ORDER: NO"
    )
    detail = {
        "source": "upbit_portfolio_slot_replacement_v1",
        "user_broker_account_id": int(user_broker_account_id),
        "old_symbol": old_symbol,
        "new_symbol": new_symbol,
        "old_score": old_score,
        "new_score": new_score,
        "reason": reason,
        "reason_ko": reason_display,
        "slot_no": int(slot_no),
        "scanner_run_id": scanner_run_id,
        "live_order": False,
        "orders_created": 0,
        "symbol_display": new_symbol,
        "old_symbol_display": old_symbol,
        "new_symbol_display": new_symbol,
        "scanner_score": new_score,
        "old_scanner_score": old_score,
    }
    try:
        notification_publisher.publish(
            event_type=event_type,
            title=title,
            message=message,
            detail=detail,
        )
        return {"ok": True, "event_type": event_type, "emitted": 1}
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "portfolio_slot_replacement_notify_failed",
            error=type(exc).__name__,
        )
        return {"ok": False, "reason": type(exc).__name__}


def publish_slot_assigned_alert(
    *,
    user_broker_account_id: int,
    symbol: str,
    slot_no: int,
    scanner_score: float | None,
    recommendation: str | None,
    confidence: float | None,
    selection_id: int | None,
    scanner_run_id: str,
) -> dict[str, Any]:
    """🎯 실제 Portfolio 슬롯 등록 — ownership FREE 통과 후만 호출."""

    event_type = str(
        getattr(
            NotificationEventType,
            "UPBIT_PORTFOLIO_SLOT_ASSIGNED",
            "UPBIT_PORTFOLIO_SLOT_ASSIGNED",
        )
    )
    score_s = (
        f"{float(scanner_score):.2f}" if scanner_score is not None else "-"
    )
    title = "🎯 자동매매 슬롯 등록"
    message = (
        f"종목: {symbol}\n"
        f"슬롯: {slot_no}\n"
        f"점수: {score_s}\n"
        f"AI: {recommendation or '-'}\n"
        f"상태: 매수조건 감시 중"
    )
    detail = {
        "source": "upbit_portfolio_slot_assigned_v1",
        "user_broker_account_id": int(user_broker_account_id),
        "symbol": symbol,
        "symbol_display": symbol,
        "slot_no": int(slot_no),
        "scanner_score": scanner_score,
        "recommendation": recommendation,
        "ai_recommendation": recommendation,
        "confidence": confidence,
        "selection_id": selection_id,
        "scanner_run_id": scanner_run_id,
        "live_order": False,
        "orders_created": 0,
        "real_portfolio_candidate": True,
        "status": "WAITING_SIGNAL",
    }
    try:
        notification_publisher.publish(
            event_type=event_type,
            title=title,
            message=message,
            detail=detail,
        )
        return {"ok": True, "event_type": event_type, "emitted": 1}
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "portfolio_slot_assigned_notify_failed",
            error=type(exc).__name__,
        )
        return {"ok": False, "reason": type(exc).__name__}
