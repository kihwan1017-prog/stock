"""Critical informational Telegram alerts — durable dedupe, REAL 비연동.

History #113 original_payload/dedupe 경로를 재사용한다.
거래 추천/주문 생성 없음.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from stock_platform.common.logger import logger
from stock_platform.common.settings import get_settings
from stock_platform.operation.news_intelligence_shadow.entities import (
    NewsIntelligenceShadowDecisionEntity,
)

EVENT_UPBIT_IMPORTANT_NOTICE = "UPBIT_IMPORTANT_NOTICE"
EVENT_KIWOOM_IMPORTANT_DISCLOSURE = "KIWOOM_IMPORTANT_DISCLOSURE"


def _already_delivered(
    session: Session,
    *,
    event_type: str,
    dedupe_key: str,
) -> bool:
    """channel_delivery_log SUCCESS + original_payload.dedupe_key (durable)."""

    if not dedupe_key:
        return False
    try:
        row = session.execute(
            text(
                """
                SELECT 1 AS ok
                FROM notification.channel_delivery_log
                WHERE event_type = :et
                  AND channel = 'TELEGRAM'
                  AND status = 'SUCCESS'
                  AND original_payload_json->>'dedupe_key' = :dk
                LIMIT 1
                """
            ),
            {"et": event_type, "dk": str(dedupe_key)},
        ).first()
        return row is not None
    except Exception:  # noqa: BLE001
        return False


def _telegram_enabled() -> bool:
    settings = get_settings()
    return bool(
        getattr(settings, "news_intelligence_telegram_enabled", True)
    )


def emit_upbit_important_notice(
    session: Session,
    *,
    row: NewsIntelligenceShadowDecisionEntity,
    detail: dict[str, Any],
) -> bool:
    if not _telegram_enabled():
        return False
    dedupe = f"UPBIT_IMPORTANT_NOTICE:{row.event_key}"
    if _already_delivered(
        session, event_type=EVENT_UPBIT_IMPORTANT_NOTICE, dedupe_key=dedupe
    ):
        return False
    category = str(detail.get("category") or row.category or "")
    title = str(detail.get("title") or row.title or "업비트 중요 공지")
    message = (
        f"[정보성] 업비트 중요 공지 감지\n"
        f"분류: {category or '-'}\n"
        f"제목: {title}\n"
        f"※ 자동매매 차단/허용 아님 · 주문 추천 아님"
    )
    payload = {
        "telegram_market": "UPBIT",
        "broker_code": "UPBIT",
        "market": "UPBIT",
        "dedupe_key": dedupe,
        "category": category,
        "url": detail.get("url"),
        "published_at": detail.get("published_at"),
        "shadow_decision_id": int(row.decision_id),
        "informational_only": True,
        "trade_recommendation": False,
        "real_buy_block": False,
        "alert_v2_formatted": True,
    }
    try:
        from stock_platform.notification.publisher import notification_publisher

        notification_publisher.publish(
            event_type=EVENT_UPBIT_IMPORTANT_NOTICE,
            title=f"[업비트] 중요 공지 · {category or 'NOTICE'}",
            message=message,
            detail=payload,
            dispatch=True,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "emit_upbit_important_notice_failed",
            error=str(exc)[:200],
        )
        return False


def emit_kiwoom_important_disclosure(
    session: Session,
    *,
    row: NewsIntelligenceShadowDecisionEntity,
    detail: dict[str, Any],
) -> bool:
    if not _telegram_enabled():
        return False
    dedupe = f"KIWOOM_IMPORTANT_DISCLOSURE:{row.event_key}"
    if _already_delivered(
        session,
        event_type=EVENT_KIWOOM_IMPORTANT_DISCLOSURE,
        dedupe_key=dedupe,
    ):
        return False
    symbol = str(detail.get("symbol") or row.symbol or "")
    report = str(detail.get("report_name") or row.title or "주요공시")
    message = (
        f"[정보성] 키움 TOP10 주요 공시 감지\n"
        f"종목: {symbol or '-'}\n"
        f"공시: {report}\n"
        f"※ Fresh Golden Cross 주문 차단/허용 아님 · 주문 추천 아님"
    )
    payload = {
        "telegram_market": "KIWOOM",
        "broker_code": "KIWOOM",
        "market": "KIWOOM",
        "dedupe_key": dedupe,
        "symbol": symbol,
        "receipt_no": detail.get("receipt_no"),
        "receipt_date": detail.get("receipt_date"),
        "shadow_decision_id": int(row.decision_id),
        "informational_only": True,
        "trade_recommendation": False,
        "real_fresh_golden_cross_block": False,
        "alert_v2_formatted": True,
    }
    try:
        from stock_platform.notification.publisher import notification_publisher

        notification_publisher.publish(
            event_type=EVENT_KIWOOM_IMPORTANT_DISCLOSURE,
            title=f"[키움] 중요 공시 · {symbol or 'DART'}",
            message=message,
            detail=payload,
            dispatch=True,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "emit_kiwoom_important_disclosure_failed",
            error=str(exc)[:200],
        )
        return False
