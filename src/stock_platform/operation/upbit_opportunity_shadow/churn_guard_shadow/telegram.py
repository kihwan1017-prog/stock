"""Telegram alert for Churn Guard Shadow — Korean UX + durable dedupe."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from stock_platform.common.logger import logger
from stock_platform.operation.upbit_opportunity_shadow.churn_guard_shadow.constants import (
    CLASSIFICATION_LABEL_KO,
    EVENT_TYPE_TELEGRAM,
    SEVERITY_LABEL_KO,
)
from stock_platform.operation.upbit_opportunity_shadow.churn_guard_shadow.entities import (
    UpbitChurnGuardShadowEpisodeEntity,
)


def _already_delivered(session: Session, *, dedupe_key: str) -> bool:
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
            {"et": EVENT_TYPE_TELEGRAM, "dk": str(dedupe_key)},
        ).first()
        return row is not None
    except Exception:  # noqa: BLE001
        return False


def format_churn_message(episode: UpbitChurnGuardShadowEpisodeEntity) -> tuple[str, str]:
    sym = str(episode.symbol or "")
    short = sym.replace("KRW-", "") if sym.startswith("KRW-") else sym
    sev = str(episode.severity or "INFO")
    sev_ko = SEVERITY_LABEL_KO.get(sev, sev)
    cls = str(episode.primary_classification or "UNKNOWN")
    cls_ko = CLASSIFICATION_LABEL_KO.get(cls, cls)
    net = float(episode.net_pnl or 0)
    reentry = episode.min_reentry_seconds
    reentry_s = (
        f"{int(float(reentry))}초" if reentry is not None else "—"
    )
    icon = "ℹ️" if sev == "INFO" else ("⚠️" if sev == "WARNING" else "🚨")
    title = f"[업비트] {icon} 반복매매 이상 감지"
    message = (
        f"{title}\n"
        f"\n"
        f"종목: {short}\n"
        f"상태: {sev_ko}\n"
        f"유형: {cls_ko}\n"
        f"\n"
        f"최근 반복거래: {int(episode.round_trip_count or 0)}회\n"
        f"연속 손실: {int(episode.consecutive_loss_count or 0)}회\n"
        f"누적 순손익: {net:,.0f}원\n"
        f"최근 재진입 간격: {reentry_s}\n"
        f"주요 매도사유: {episode.dominant_exit_reason or '—'}\n"
        f"\n"
        f"현재 조치:\n"
        f"관찰 중 (자동매매 정책 변경 없음)"
    )
    return title, message


def emit_churn_guard_alert(
    session: Session,
    *,
    episode: UpbitChurnGuardShadowEpisodeEntity,
    force: bool = False,
) -> bool:
    dedupe = (
        episode.telegram_dedupe_key
        or f"CHURN:{int(episode.user_broker_account_id)}:{episode.symbol}:{int(episode.event_id)}:{episode.severity}"
    )
    if not force and _already_delivered(session, dedupe_key=dedupe):
        return False
    title, message = format_churn_message(episode)
    payload = {
        "telegram_market": "UPBIT",
        "broker_code": "UPBIT",
        "market": "UPBIT",
        "dedupe_key": dedupe,
        "user_broker_account_id": int(episode.user_broker_account_id),
        "symbol": episode.symbol,
        "severity": episode.severity,
        "primary_classification": episode.primary_classification,
        "event_id": int(episode.event_id),
        "shadow_only": True,
        "informational_only": True,
        "real_buy_block": False,
        "kill_switch": False,
        "alert_v2_formatted": True,
        "notice_ko": "감시/경고 전용 · 자동매매 차단 없음",
    }
    try:
        from stock_platform.notification.publisher import notification_publisher

        notification_publisher.publish(
            event_type=EVENT_TYPE_TELEGRAM,
            title=title,
            message=message,
            detail=payload,
            dispatch=True,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("emit_churn_guard_alert_failed", error=str(exc)[:200])
        return False
