"""사용자용 reason / reject 라벨 (raw code는 detail에 보존)."""

from __future__ import annotations

from typing import Any

from stock_platform.notification.code_dictionary import translate

# 추가 V2 매핑 (BUILTIN exit_reason 확장)
EXIT_REASON_KO: dict[str, str] = {
    "MA_DEAD_CROSS": "이동평균 데드크로스",
    "MA_DEAD_CROSS_EXIT": "이동평균 데드크로스",
    "DEAD_CROSS": "이동평균 데드크로스",
    "MA_EXIT": "이동평균 청산",
    "STOP_LOSS": "손절",
    "TAKE_PROFIT": "목표수익 도달",
    "TRAILING_STOP": "트레일링 스탑",
    "TIME_EXIT": "최대 보유시간 도달",
    "KILL_SWITCH": "안전장치 강제청산",
    "RECOVERY": "복구 처리",
    "MANUAL": "수동 매도",
    "STRATEGY_SIGNAL": "전략 신호",
    "RELATIVE_LOSS": "상대 손실",
    "UNKNOWN": "기타",
}

REJECT_REASON_KO: dict[str, str] = {
    "MAX_OPEN_POSITIONS_REACHED": "AUTO 포지션 한도 도달",
    "DAILY_ENTRY_LIMIT_REACHED": "오늘 신규진입 한도 도달",
    "AI_HOLD": "AI가 현재 매수를 보류",
    "AI_HOLD_CURRENTLY": "AI가 현재 매수를 보류",
    "STALE_MARKET_DATA": "시세 데이터가 오래됨",
    "LIVE_REQUIRED": "실거래 모드가 꺼져 있음",
    "ARM_REQUIRED": "자동주문 승인이 꺼져 있음",
    "KILL_SWITCH_ACTIVE": "안전장치가 활성화됨",
    "INSUFFICIENT_BALANCE": "잔고 부족",
    "ORDER_AMOUNT_REJECT": "주문금액 제한",
    "DUPLICATE_ORDER_REJECT": "중복 주문 차단",
    "MARKET_TIME_REJECT": "주문 가능 시간 아님",
    "BROKER_HEALTH_REJECT": "거래소 연결 이상",
}


def exit_reason_user_label(code: Any) -> str:
    raw = str(code or "").strip()
    if not raw:
        return "기타"
    key = raw.upper()
    if key in EXIT_REASON_KO:
        return EXIT_REASON_KO[key]
    # 부분 매칭
    for needle, label in EXIT_REASON_KO.items():
        if needle in key:
            return label
    via = translate(key, group="exit_reason", default="")
    if via and via != key:
        return via
    return raw


def reject_reason_user_label(code: Any) -> str:
    raw = str(code or "").strip()
    if not raw:
        return "사유 미상"
    key = raw.upper()
    if key in REJECT_REASON_KO:
        return REJECT_REASON_KO[key]
    via = translate(key, group="alert_reason", default="")
    if via and via != key:
        return via
    return raw
