"""사용자 친화 reason 문구 — UI projection only (가벼운 모듈, heavy import 금지)."""

from __future__ import annotations

REASON_KO: dict[str, str] = {
    "SHORT_MA_NOT_ABOVE_LONG_MA": (
        "단기 이동평균이 장기 이동평균보다 낮아 매수 신호를 기다리는 중입니다."
    ),
    "MARKET_CLOSED": "현재 국내 주식시장은 장 마감 상태입니다.",
    "FEED_DOWN": "실시간 시세 수신이 중단되었습니다.",
    "NO_CANDIDATE": "현재 조건을 충족하는 매수 후보가 없습니다.",
    "WAITING": "진입 대기(WAITING) 슬롯에서 재검증을 진행 중입니다.",
    "KILL_SWITCH": "긴급 정지(Kill Switch)가 켜져 신규 주문이 차단됩니다.",
    "ACCOUNT_PAUSED": "계좌가 일시정지 상태입니다.",
    "STALE_PRE_RESTORE_WAITING": (
        "시세 복구 직후 대기 슬롯 검증이 필요해 신규 진입이 보류되었습니다."
    ),
    "DAILY_LOSS_LIMIT": "일일 손실 한도에 도달해 신규 진입이 제한됩니다.",
}


def friendly_reason(code: str | None) -> str:
    if not code:
        return "특이 사유 없음"
    key = str(code).strip().upper()
    return REASON_KO.get(key, f"현재 상태 코드: {code}")
