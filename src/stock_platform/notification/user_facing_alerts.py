"""Telegram/웹 모니터링 알림 — 사용자 친화 한글 presentation.

원본 event_type/reason/actor 는 detail·audit에 보존한다.
Telegram/Inbox 표시용 title/message 만 변환한다.
"""

from __future__ import annotations

import time
from typing import Any

from stock_platform.notification.code_dictionary import translate
from stock_platform.notification.formatting import format_datetime_kst

# 정상 restart 연쇄 억제 (프로세스 로컬)
_STARTUP_SUPPRESS_UNTIL = 0.0
_STARTUP_WINDOW_SEC = 120.0


def mark_startup_transition_window(*, seconds: float = _STARTUP_WINDOW_SEC) -> None:
    """SYSTEM_STOP/START 전후 정상 ARM 전이 억제 창."""

    global _STARTUP_SUPPRESS_UNTIL
    _STARTUP_SUPPRESS_UNTIL = time.time() + max(5.0, float(seconds))


def _in_startup_window() -> bool:
    return time.time() < _STARTUP_SUPPRESS_UNTIL


def reason_ko(code: Any) -> str:
    raw = str(code or "").strip()
    if not raw:
        return "-"
    return translate(raw, group="alert_reason", default=raw)


def actor_ko(code: Any) -> str:
    raw = str(code or "").strip()
    if not raw:
        return "-"
    return translate(raw, group="alert_actor", default=raw)


def market_label_ko(
    *,
    broker_code: str | None = None,
    user_broker_account_id: int | None = None,
    include_uba_dev: bool = False,
) -> str:
    """시장 표시명. UBA 매직넘버 하드코딩 금지 — broker_code / DB 조회."""

    bc = str(broker_code or "").strip().upper()
    if not bc and user_broker_account_id is not None:
        try:
            from stock_platform.database.session import get_session_factory
            from stock_platform.trading.account_models import UserBrokerAccount

            session = get_session_factory()()
            try:
                row = session.get(UserBrokerAccount, int(user_broker_account_id))
                bc = str(getattr(row, "broker_code", "") or "").upper()
            finally:
                session.close()
        except Exception:  # noqa: BLE001
            bc = ""

    label = translate(bc, group="market_display", default="")
    if not label:
        if bc == "UPBIT":
            label = "업비트"
        elif bc == "KIWOOM":
            label = "키움증권"
        elif bc:
            label = bc
        else:
            label = "자동매매"

    if include_uba_dev and user_broker_account_id is not None:
        return f"{label} (UBA {int(user_broker_account_id)})"
    return label


def format_expires_kst(value: Any) -> str:
    """UTC ISO → 'YYYY-MM-DD HH:MM KST' (초 생략)."""

    full = format_datetime_kst(value)
    if not full or full == "-":
        return "-"
    # 'YYYY-MM-DD HH:MM:SS KST' → 'YYYY-MM-DD HH:MM KST'
    parts = full.rsplit(" ", 1)
    if len(parts) == 2 and parts[1] == "KST":
        body = parts[0]
        if body.count(":") >= 2:
            body = body.rsplit(":", 1)[0]
        return f"{body} KST"
    return full


def _uba_id(detail: dict[str, Any]) -> int | None:
    raw = detail.get("user_broker_account_id") or detail.get("uba_id")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def is_normal_startup_disarm(detail: dict[str, Any], message: str) -> bool:
    reason = str(detail.get("reason") or "").strip().lower()
    actor = str(detail.get("actor") or "").strip().upper()
    text = str(message or "").lower()
    if reason == "fail_closed_restart" and actor == "STARTUP":
        return True
    if "fail_closed_restart" in text and "startup" in text and "disarm" in text:
        return True
    return False


def is_normal_startup_arm_restore(detail: dict[str, Any], message: str) -> bool:
    actor = str(detail.get("actor") or "").strip().upper()
    if actor in {
        "SYSTEM_UNATTENDED_STARTUP_RESTORE",
        "MARKET_HOURS_ARM_RESTORE",
    }:
        return True
    text = str(message or "").upper()
    if "SYSTEM_UNATTENDED_STARTUP_RESTORE" in text:
        return True
    if "MARKET_HOURS_ARM_RESTORE" in text:
        return True
    return False


def should_coalesce_startup_monitoring(
    *,
    event_type: str,
    detail: dict[str, Any] | None,
    message: str,
) -> tuple[bool, str | None]:
    """정상 restart ARM/DISARM 폭주 억제. 이상 DISARM/CRITICAL 은 억제하지 않음."""

    et = str(event_type or "").upper()
    if et in {"SYSTEM_START", "SYSTEM_STOP"}:
        mark_startup_transition_window()
        return False, None

    if et != "MONITORING_ALERT":
        return False, None

    d = dict(detail or {})
    kind = str(d.get("kind") or "").upper()
    # 한도/시장 edge 등은 유지
    if kind in {
        "DAILY_LIMIT_REACHED",
        "DAILY_LIMIT_AVAILABLE",
        "MARKET_CLOSED",
        "MARKET_OPEN_AND_READY",
    }:
        return False, None

    if is_normal_startup_disarm(d, message):
        # startup fail-closed disarm — SYSTEM_STOP/START 로 대표
        mark_startup_transition_window()
        return True, "STARTUP_NORMAL_DISARM_COALESCE"
    if is_normal_startup_arm_restore(d, message) and _in_startup_window():
        # 재시작 직후 자동 ARM 복구만 억제 (장중 MARKET_HOURS 복구는 표시)
        return True, "STARTUP_NORMAL_ARM_RESTORE_COALESCE"
    return False, None


def build_user_facing_copy(
    *,
    event_type: str,
    title: str,
    message: str,
    detail: dict[str, Any] | None,
) -> tuple[str, str, dict[str, Any]]:
    """(title, message, enriched_detail). 원본은 detail['_raw_*']에 보존."""

    et = str(event_type or "").upper()
    d = dict(detail or {})
    # audit/원본 보존
    d.setdefault("_raw_title", title)
    d.setdefault("_raw_message", message)
    d.setdefault("_raw_reason", d.get("reason"))
    d.setdefault("_raw_actor", d.get("actor"))

    uba = _uba_id(d)
    market = market_label_ko(
        broker_code=str(d.get("broker_code") or "") or None,
        user_broker_account_id=uba,
    )
    reason = str(d.get("reason") or "")
    actor = str(d.get("actor") or "")
    kind = str(d.get("kind") or "").upper()

    if et == "SYSTEM_STOP":
        return (
            "🔴 자동매매 서버 중지",
            (
                "서버 종료 절차를 진행하고 있습니다.\n"
                "자동매매는 안전을 위해 일시 해제됩니다."
            ),
            d,
        )

    if et == "SYSTEM_START":
        body_lines = [
            "서버가 정상적으로 시작되었습니다.",
            "자동매매 상태를 복구했습니다.",
            "",
        ]
        body_lines.extend(_startup_market_summary_lines())
        return ("🟢 자동매매 서버 시작", "\n".join(body_lines).rstrip(), d)

    if et == "MONITORING_ALERT" and kind == "DAILY_LIMIT_REACHED":
        count = d.get("entry_count")
        limit = d.get("entry_limit")
        return (
            "🟡 [업비트] 오늘 신규 매수 한도 도달",
            (
                f"일일 신규매수: {count} / {limit}\n"
                "신규 매수: 중지\n"
                "기존 포지션 매도/손절/익절: 계속 동작\n"
                "다음 집계: 내일 00:00 KST부터 새로 계산"
            ),
            d,
        )

    if et == "MONITORING_ALERT" and kind == "DAILY_LIMIT_AVAILABLE":
        count = d.get("entry_count")
        limit = d.get("entry_limit")
        return (
            "🟢 [업비트] 일일 신규매수 한도 갱신",
            (
                "일일 신규진입 한도가 갱신되었습니다.\n"
                "자동매매 분석 알림을 재개합니다.\n"
                f"현재: {count} / {limit}"
            ),
            d,
        )

    if et == "MONITORING_ALERT" and kind == "MARKET_CLOSED":
        return (
            "🟡 [키움증권] 정규장 종료",
            (
                "정규장이 종료되었습니다.\n"
                "분석 알림을 중지합니다.\n"
                "시스템/장애 알림은 계속됩니다."
            ),
            d,
        )

    if et == "MONITORING_ALERT" and kind == "MARKET_OPEN_AND_READY":
        return (
            "🟢 [키움증권] 정규장 자동매매 시작",
            (
                "정규장 자동매매가 시작되었습니다.\n"
                "분석 알림을 재개합니다."
            ),
            d,
        )

    text = str(message or "")
    text_l = text.lower()
    title_u = str(title or "").upper()

    is_disarm = (
        "disarm" in text_l
        or "DISARM" in title_u
        or d.get("new_arm") is False
    )
    is_arm = (
        (not is_disarm)
        and (
            "armed" in text_l
            or title_u in {"LIVE ARM", "ARM ON"}
            or d.get("new_arm") is True
            or d.get("arm_changed") is True
        )
    )

    if is_disarm:
        cause = reason_ko(reason) if reason else actor_ko(actor)
        if is_normal_startup_disarm(d, text):
            cause = reason_ko("fail_closed_restart")
        return (
            f"🟡 [{market}] 자동매매 안전 해제",
            (
                f"원인: {cause}\n"
                "신규 주문: 일시 중지\n"
                "기존 주문을 임의 취소한 것은 아닙니다."
            ),
            d,
        )

    if is_arm:
        expires = format_expires_kst(d.get("expires_at"))
        lines = [
            "LIVE: ON" if d.get("live", True) else "LIVE: 확인 필요",
            "ARM: ON",
            "자동매매: 정상",
        ]
        if expires != "-":
            lines.append(f"유효: {expires}까지")
        if str(d.get("broker_code") or "").upper() == "UPBIT" or market == "업비트":
            daily = _try_upbit_daily_line(uba)
            if daily:
                lines.extend(daily)
        return (
            f"🟢 [{market}] 자동매매 복구 완료",
            "\n".join(lines),
            d,
        )

    # 일반 MONITORING — reason/actor 한글화만
    if et == "MONITORING_ALERT":
        bits: list[str] = []
        if reason:
            bits.append(f"원인: {reason_ko(reason)}")
        if actor and actor.upper() not in {
            str(reason or "").upper(),
        }:
            bits.append(f"주체: {actor_ko(actor)}")
        # UTC raw 가 message에 있으면 KST 치환 시도는 최소화 — expires만
        body = "\n".join(bits) if bits else text
        # UBA NNNN 노출 완화
        if uba is not None:
            body = body.replace(f"UBA {uba}", market).replace(f"UBA{uba}", market)
        title_out = title
        if title_out.upper() in {"LIVE ARM", "LIVE DISARM", "MONITORING ALERT", "⚠️ 모니터링 알림"}:
            title_out = f"⚠️ [{market}] 모니터링 알림"
        return (title_out, body or text, d)

    return (title, message, d)


def _startup_market_summary_lines() -> list[str]:
    """SYSTEM_START 본문용 — 실패해도 빈 목록."""

    lines: list[str] = []
    try:
        from stock_platform.database.session import get_session_factory
        from stock_platform.trading.account_models import UserBrokerAccount
        from sqlalchemy import select

        session = get_session_factory()()
        try:
            rows = list(
                session.scalars(
                    select(UserBrokerAccount).where(
                        UserBrokerAccount.broker_code.in_(("UPBIT", "KIWOOM"))
                    )
                )
            )
            # LIVE/ARM 우선 정렬
            rows.sort(
                key=lambda r: (
                    0 if bool(r.live_order_enabled) else 1,
                    str(r.broker_code or ""),
                    int(r.user_broker_account_id),
                )
            )
            seen_broker: set[str] = set()
            for row in rows:
                bc = str(row.broker_code or "").upper()
                if bc in seen_broker:
                    continue
                seen_broker.add(bc)
                label = market_label_ko(broker_code=bc)
                live = "ON" if row.live_order_enabled else "OFF"
                arm = "ON" if row.live_armed else "OFF"
                status = "정상" if (row.live_order_enabled and row.live_armed) else "대기"
                lines.append(f"{label}: {status} (LIVE {live} · ARM {arm})")
                if bc == "UPBIT":
                    lines.extend(
                        _try_upbit_daily_line(int(row.user_broker_account_id))
                    )
        finally:
            session.close()
    except Exception:  # noqa: BLE001
        return ["시스템: 복구 절차 완료"]
    if not lines:
        lines.append("시스템: 정상")
    else:
        lines.append("시스템: 정상")
    return lines


def _try_upbit_daily_line(uba_id: int | None) -> list[str]:
    if uba_id is None:
        return []
    try:
        from stock_platform.database.session import get_session_factory
        from stock_platform.operation.upbit_full_market.portfolio_daily_entry_admission import (
            resolve_portfolio_daily_entry_limit,
        )
        from stock_platform.operation.upbit_full_market.portfolio_daily_entry_count import (
            summarize_portfolio_daily_entries,
        )

        session = get_session_factory()()
        try:
            limit = resolve_portfolio_daily_entry_limit(session, int(uba_id))
            usage = summarize_portfolio_daily_entries(
                session, int(uba_id), daily_limit=limit
            )
            count = int(usage.get("entry_count") or 0)
            lim = int(usage.get("entry_limit") or limit)
            rem = max(0, lim - count)
            return [
                f"오늘 신규매수: {count} / {lim}",
                f"추가 가능: {rem}건",
            ]
        finally:
            session.close()
    except Exception:  # noqa: BLE001
        return []
