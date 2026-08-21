"""Paper Shadow Telegram — 실주문 없음."""

from __future__ import annotations

from typing import Any

import structlog

from stock_platform.notification.events import NotificationEventType
from stock_platform.notification.publisher import notification_publisher

logger = structlog.get_logger(__name__)


def _ensure_event(name: str) -> str:
    try:
        return NotificationEventType[name].value
    except KeyError:
        return name


def publish_shadow_opened(shadow: dict[str, Any]) -> None:
    symbol = shadow.get("symbol")
    title = "Shadow 후보 추적 시작"
    message = f"종목 {symbol} Shadow 추적 시작 (실주문 아님)"
    notification_publisher.publish(
        event_type=_ensure_event("UPBIT_SCANNER_SHADOW_OPENED"),
        title=title,
        message=message,
        detail={
            "source": "upbit_opportunity_shadow_v1",
            "live_auto_start": False,
            "live_order": False,
            "orders_created": 0,
            "paper_shadow": True,
            "shadow_only": True,
            "shadow": shadow,
            "symbol": symbol,
            "rank": shadow.get("scanner_rank"),
            "scanner_score": shadow.get("scanner_score"),
            "recommendation": shadow.get("recommendation"),
            "confidence": shadow.get("confidence"),
            "entry_price": shadow.get("entry_price"),
            "assumed_amount_krw": shadow.get("assumed_amount_krw"),
        },
    )


def publish_shadow_result(shadow: dict[str, Any]) -> None:
    symbol = shadow.get("symbol")
    sl_tp = (
        f"SL={'HIT' if shadow.get('sl_hit') else 'no'} / "
        f"TP={'HIT' if shadow.get('tp_hit') else 'no'}"
    )
    ret60 = shadow.get("return_60m_pct")
    result = "FLAT"
    if ret60 is not None:
        if float(ret60) > 0:
            result = "POSITIVE"
        elif float(ret60) < 0:
            result = "NEGATIVE"
    title = f"UPBIT Shadow Result {symbol}"
    message = (
        f"[UPBIT Shadow Result]\n"
        f"Symbol: {symbol}\n"
        f"Entry: {shadow.get('entry_price')}\n"
        f"5m: {shadow.get('return_5m_pct')}\n"
        f"15m: {shadow.get('return_15m_pct')}\n"
        f"30m: {shadow.get('return_30m_pct')}\n"
        f"60m: {shadow.get('return_60m_pct')}\n"
        f"MFE: {shadow.get('mfe_pct')}\n"
        f"MAE: {shadow.get('mae_pct')}\n"
        f"SL/TP: {sl_tp}\n"
        f"Result: {result}\n"
        f"SHADOW ONLY\n"
        f"LIVE ORDER: NO"
    )
    notification_publisher.publish(
        event_type=_ensure_event("UPBIT_SCANNER_SHADOW_RESULT"),
        title=title,
        message=message,
        detail={
            "source": "upbit_opportunity_shadow_v1_result",
            "live_auto_start": False,
            "live_order": False,
            "orders_created": 0,
            "paper_shadow": True,
            "shadow_only": True,
            "shadow": shadow,
        },
    )


def publish_shadow_mismatch(
    shadow: dict[str, Any],
    *,
    diff: dict[str, Any],
) -> None:
    symbol = shadow.get("symbol")
    title = f"UPBIT Shadow Evaluation Mismatch {symbol}"
    message = (
        f"[UPBIT Shadow Evaluation Mismatch]\n"
        f"Symbol: {symbol}\n"
        f"Shadow ID: {shadow.get('shadow_id')}\n"
        f"Code: SHADOW_EVALUATION_MISMATCH\n"
        f"Auto reconcile: NO\n"
        f"SHADOW ONLY\n"
        f"LIVE ORDER: NO"
    )
    notification_publisher.publish(
        event_type=_ensure_event("UPBIT_SHADOW_EVALUATION_MISMATCH"),
        title=title,
        message=message,
        detail={
            "source": "upbit_shadow_mismatch_watch",
            "live_order": False,
            "orders_created": 0,
            "shadow_only": True,
            "auto_reconcile": False,
            "shadow": shadow,
            "diff": diff,
        },
    )


def publish_shadow_cohort_milestone(snapshot: dict[str, Any]) -> None:
    """SHADOW_COHORT_30_REVIEW_READY — 정책 변경 없이 1회 알림."""

    title = "UPBIT Shadow Cohort 30 Review Ready"
    message = (
        f"[UPBIT Shadow Cohort Milestone]\n"
        f"Code: SHADOW_COHORT_30_REVIEW_READY\n"
        f"VALID_COHORT_N: {snapshot.get('valid_cohort_n')}"
        f" / {snapshot.get('valid_cohort_threshold')}\n"
        f"NEW_POLICY_MATCH_N: {snapshot.get('new_policy_match_n')}"
        f" / {snapshot.get('new_policy_match_threshold')}\n"
        f"mismatch_count: {snapshot.get('mismatch_count')}\n"
        f"Policy: LAST_KNOWN_PRICE_AT_TARGET (b8b954f)\n"
        f"Auto reconcile: NO\n"
        f"Threshold/ranking/AI Gate unchanged\n"
        f"SHADOW ONLY\n"
        f"LIVE ORDER: NO"
    )
    notification_publisher.publish(
        event_type=_ensure_event("UPBIT_SHADOW_COHORT_30_REVIEW_READY"),
        title=title,
        message=message,
        detail={
            "source": "upbit_shadow_cohort_milestone_watch",
            "code": "SHADOW_COHORT_30_REVIEW_READY",
            "live_order": False,
            "orders_created": 0,
            "shadow_only": True,
            "auto_reconcile": False,
            "policy_unchanged": True,
            "snapshot": snapshot,
        },
    )
