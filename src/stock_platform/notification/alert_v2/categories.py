"""Trading Alert Management V2 — categories & preference keys.

NOTIFICATION ONLY. Does not change trading / LIVE / risk.
"""

from __future__ import annotations

from enum import StrEnum


class AlertTopCategory(StrEnum):
    """사용자 대분류 3개."""

    UPBIT = "UPBIT"
    KIWOOM = "KIWOOM"
    SYSTEM = "SYSTEM"


class AlertPreferenceKey(StrEnum):
    UPBIT_RUNTIME = "UPBIT_RUNTIME"
    UPBIT_AUTO_BUY = "UPBIT_AUTO_BUY"
    UPBIT_AUTO_SELL = "UPBIT_AUTO_SELL"
    UPBIT_ORDER_EXCEPTION = "UPBIT_ORDER_EXCEPTION"

    KIWOOM_RUNTIME = "KIWOOM_RUNTIME"
    KIWOOM_AUTO_BUY = "KIWOOM_AUTO_BUY"
    KIWOOM_AUTO_SELL = "KIWOOM_AUTO_SELL"
    KIWOOM_ORDER_EXCEPTION = "KIWOOM_ORDER_EXCEPTION"

    UPBIT_AI_DECISION = "UPBIT_AI_DECISION"
    KIWOOM_AI_DECISION = "KIWOOM_AI_DECISION"
    AUTO_SLOT = "AUTO_SLOT"
    CANDIDATE_ANALYSIS = "CANDIDATE_ANALYSIS"
    SHADOW_ANALYSIS = "SHADOW_ANALYSIS"
    SYSTEM_OPERATION = "SYSTEM_OPERATION"


# Admin UI 표시 메타 (delivery-only)
PREFERENCE_CATALOG: list[dict[str, str]] = [
    {
        "key": AlertPreferenceKey.UPBIT_RUNTIME.value,
        "group": "UPBIT",
        "label": "업비트 자동매매 시작/중지",
        "description": "업비트 Runtime 시작·정상/비정상 중지·복구",
        "default_enabled": "true",
    },
    {
        "key": AlertPreferenceKey.UPBIT_AUTO_BUY.value,
        "group": "UPBIT",
        "label": "업비트 자동매수",
        "description": "AUTO 매수 체결(FILLED) 알림",
        "default_enabled": "true",
    },
    {
        "key": AlertPreferenceKey.UPBIT_AUTO_SELL.value,
        "group": "UPBIT",
        "label": "업비트 자동매도",
        "description": "AUTO 매도/청산 체결 알림 (손익 포함)",
        "default_enabled": "true",
    },
    {
        "key": AlertPreferenceKey.UPBIT_ORDER_EXCEPTION.value,
        "group": "UPBIT",
        "label": "업비트 주문/체결 이상",
        "description": "주문 거부·실패 등 이상 알림",
        "default_enabled": "true",
    },
    {
        "key": AlertPreferenceKey.KIWOOM_RUNTIME.value,
        "group": "KIWOOM",
        "label": "키움 자동매매 시작/중지",
        "description": "키움 Runtime 시작·중지·복구",
        "default_enabled": "true",
    },
    {
        "key": AlertPreferenceKey.KIWOOM_AUTO_BUY.value,
        "group": "KIWOOM",
        "label": "키움 자동매수",
        "description": "AUTO 매수 체결 알림",
        "default_enabled": "true",
    },
    {
        "key": AlertPreferenceKey.KIWOOM_AUTO_SELL.value,
        "group": "KIWOOM",
        "label": "키움 자동매도",
        "description": "AUTO 매도/청산 체결 알림",
        "default_enabled": "true",
    },
    {
        "key": AlertPreferenceKey.KIWOOM_ORDER_EXCEPTION.value,
        "group": "KIWOOM",
        "label": "키움 주문/체결 이상",
        "description": "주문 거부·실패 등 이상 알림",
        "default_enabled": "true",
    },
    {
        "key": AlertPreferenceKey.UPBIT_AI_DECISION.value,
        "group": "SYSTEM",
        "label": "UPBIT AI 매매 판단 변경",
        "description": "AI Gate 추천이 바뀔 때만",
        "default_enabled": "true",
    },
    {
        "key": AlertPreferenceKey.KIWOOM_AI_DECISION.value,
        "group": "SYSTEM",
        "label": "KIWOOM AI 매매 판단 변경",
        "description": "키움 AI Gate 추천 변경",
        "default_enabled": "true",
    },
    {
        "key": AlertPreferenceKey.AUTO_SLOT.value,
        "group": "SYSTEM",
        "label": "자동매매 슬롯",
        "description": "슬롯 등록/교체/해제 lifecycle",
        "default_enabled": "true",
    },
    {
        "key": AlertPreferenceKey.CANDIDATE_ANALYSIS.value,
        "group": "SYSTEM",
        "label": "후보 분석",
        "description": "의미 있는 후보 요약 (스캔 매 tick 제외)",
        "default_enabled": "false",
    },
    {
        "key": AlertPreferenceKey.SHADOW_ANALYSIS.value,
        "group": "SYSTEM",
        "label": "Shadow 분석",
        "description": "연구 Shadow checkpoint (실주문 아님)",
        "default_enabled": "false",
    },
    {
        "key": AlertPreferenceKey.SYSTEM_OPERATION.value,
        "group": "SYSTEM",
        "label": "시스템 중요 알림",
        "description": "Kill Switch·복구·시세·위험 등",
        "default_enabled": "true",
    },
]

USER_PREFIX = {
    AlertTopCategory.UPBIT: "[업비트]",
    AlertTopCategory.KIWOOM: "[키움]",
    AlertTopCategory.SYSTEM: "[시스템]",
}
