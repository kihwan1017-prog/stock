"""코드/enum → 한글 라벨. 내장 dict + 선택적 DB override."""

from __future__ import annotations

from typing import Any

# group → code → ko label
BUILTIN_KO: dict[str, dict[str, str]] = {
    "recommendation": {
        "ALLOW": "매수 허용",
        "REDUCE": "비중 축소",
        "HOLD": "대기",
        "BLOCK": "매매 차단",
        "SELL": "매도 권고",
    },
    "side": {
        "BUY": "매수",
        "SELL": "매도",
        "BUY_LONG": "매수",
        "SELL_SHORT": "매도",
    },
    "order_status": {
        "SUBMITTED": "제출",
        "ACCEPTED": "주문 접수",
        "FILLED": "체결 완료",
        "PARTIAL_FILLED": "부분 체결",
        "CANCELLED": "주문 취소",
        "REJECTED": "주문 거부",
        "PENDING": "대기",
    },
    "order_type": {
        "LIMIT": "지정가",
        "MARKET": "시장가",
        "BEST": "최유리",
        "PRICE": "지정가",
    },
    "runtime": {
        "RUNNING": "실행 중",
        "PAUSED": "일시정지",
        "STOPPED": "중지",
        "ERROR": "오류",
        "CREATED": "생성됨",
    },
    "on_off": {
        "ON": "켜짐",
        "OFF": "꺼짐",
        "TRUE": "켜짐",
        "FALSE": "꺼짐",
        "ACTIVE": "활성",
        "INACTIVE": "비활성",
        "EXPIRED": "만료",
    },
    "mode": {
        "LIVE": "실거래",
        "PAPER": "모의거래",
        "SHADOW": "섀도우",
        "DRY_RUN": "드라이런",
    },
    "exit_reason": {
        "TAKE_PROFIT": "익절",
        "STOP_LOSS": "손절",
        "TRAILING_STOP": "트레일링 스탑",
        "RELATIVE_LOSS": "상대 손실",
        "MANUAL": "수동 청산",
        "KILL_SWITCH": "Kill Switch",
    },
    "slot_status": {
        "WAITING_SIGNAL": "매수 신호 대기",
        "ENTRY_PENDING": "주문 준비",
        "OPEN": "보유 중",
        "EXIT_PENDING": "청산 진행",
        "COOLDOWN": "재진입 대기",
        "EMPTY": "비어 있음",
        "IDLE": "대기",
    },
    "broker": {
        "UPBIT": "업비트",
        "KIWOOM": "키움",
        "PAPER": "모의",
    },
    # Telegram/웹 사용자 표시용 시장명
    "market_display": {
        "UPBIT": "업비트",
        "KIWOOM": "키움증권",
        "PAPER": "모의",
    },
    "alert_reason": {
        "FAIL_CLOSED_RESTART": "서버 재시작에 따른 안전 해제",
        "STARTUP": "서버 시작 절차",
        "SYSTEM_UNATTENDED_STARTUP_RESTORE": "서버 재시작 후 자동 복구",
        "MARKET_HOURS_ARM_RESTORE": "장 운영시간 자동 복구",
        "DAILY_ENTRY_LIMIT_REACHED": "오늘 신규 매수 한도 도달",
        "RUNTIME_STOPPED": "자동매매 실행 중지",
        "MARKET_CLOSED": "정규장 종료",
        "MANUAL": "운영자 수동 조작",
        "EXPIRED": "세션 만료",
    },
    "alert_actor": {
        "STARTUP": "서버 시작 절차",
        "SYSTEM_UNATTENDED_STARTUP_RESTORE": "서버 재시작 후 자동 복구",
        "MARKET_HOURS_ARM_RESTORE": "장 운영시간 자동 복구",
        "SYSTEM": "시스템",
        "ADMIN": "관리자",
        "OPERATOR": "운영자",
    },
    "severity": {
        "INFO": "안내",
        "SUCCESS": "성공",
        "WARNING": "경고",
        "WARN": "경고",
        "CRITICAL": "긴급",
        "TRADE": "거래",
        "SYSTEM": "시스템",
        "RISK": "리스크",
        "AI": "AI",
        "PORTFOLIO": "포트폴리오",
        "RECOVERY": "복구",
        "DEBUG": "디버그",
    },
}

_db_override: dict[tuple[str, str, str], str] = {}


def set_db_overrides(rows: list[dict[str, Any]]) -> None:
    """캐시 갱신 시 호출. locale 기본 ko-KR."""

    global _db_override
    next_map: dict[tuple[str, str, str], str] = {}
    for row in rows:
        group = str(row.get("code_group") or "").strip()
        code = str(row.get("code") or "").strip().upper()
        locale = str(row.get("locale") or "ko-KR").strip()
        label = str(row.get("label") or "").strip()
        if group and code and label:
            next_map[(group, code, locale)] = label
    _db_override = next_map


def translate(
    code: Any,
    *,
    group: str,
    locale: str = "ko-KR",
    default: str | None = None,
) -> str:
    raw = str(code or "").strip()
    if not raw:
        return default or "-"
    key = raw.upper()
    hit = _db_override.get((group, key, locale))
    if hit:
        return hit
    builtin = BUILTIN_KO.get(group, {}).get(key)
    if builtin:
        return builtin
    return default or raw


def broker_ko(code: Any) -> str:
    return translate(code, group="broker")


def side_ko(code: Any) -> str:
    return translate(code, group="side")


def recommendation_ko(code: Any) -> str:
    return translate(code, group="recommendation")
