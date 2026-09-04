"""User-facing AUTO block reason labels (Korean)."""

from __future__ import annotations

from typing import Any

PRIMARY_REASON_TEXT_KO: dict[str, str] = {
    "KILL_SWITCH_ACTIVE": (
        "안전장치(Kill Switch)가 활성화되어 자동매매가 중지되었습니다."
    ),
    "ARM_EXPIRED": "자동주문 승인(ARM) 유효시간이 만료되었습니다.",
    "ARM_OFF": "자동주문 승인(ARM)이 꺼져 있습니다.",
    "ARM_OFF_OR_EXPIRED": "자동주문 승인(ARM)이 꺼져 있거나 만료되었습니다.",
    "LIVE_OFF": "실거래 사용 상태가 꺼져 있습니다.",
    "LIVE_NOT_APPROVED": "실거래(LIVE) 승인이 활성화되어 있지 않습니다.",
    "RUNTIME_COMPONENT_STOPPED": (
        "자동매매 실행 구성요소 일부가 중지되었습니다."
    ),
    "EXECUTION_STACK_DOWN": (
        "자동매매 실행 구성요소 일부가 중지되었습니다."
    ),
    "PARTIAL_RESTORE": "실행 스택이 불완전합니다 (일부 구성요소만 동작).",
    "FEED_STALE": (
        "실시간 시세 수신이 오래되어 안전을 위해 신규 매수를 중지했습니다."
    ),
    "AUTO_EXIT_QUOTE_STALE": (
        "청산용 시세가 오래되어 안전 확인이 필요합니다."
    ),
    "AUTO_ENTRY_QUOTE_STALE": (
        "매수용 시세가 오래되어 신규 매수를 중지했습니다."
    ),
    "BROKER_RECOVERY_CONFLICT": (
        "거래소 주문/잔고와 로컬 상태가 일치하지 않아 안전 확인이 필요합니다."
    ),
    "RECOVERY_CONFLICT": (
        "거래소 주문/잔고와 로컬 상태가 일치하지 않아 안전 확인이 필요합니다."
    ),
    "ACTIVATION_INACTIVE": "거래 세션(Activation)이 비활성입니다.",
    "NO_CANDIDATES": "현재 매수 후보가 없습니다.",
    "NO_GOLDEN_CROSS": "현재 매수 신호 조건이 충족되지 않았습니다.",
    "POSITION_MISMATCH": (
        "체결 후 포지션 검증에서 불일치가 감지되어 안전장치가 동작했습니다."
    ),
}


def primary_reason_text_ko(
    code: str | None, *, kill_reason: str | None = None
) -> str | None:
    if not code:
        return None
    u = str(code).upper()
    if u == "KILL_SWITCH_ACTIVE" and kill_reason:
        kr = str(kill_reason).upper()
        if "POSITION_MISMATCH" in kr or kr == "POSITION_MISMATCH":
            return PRIMARY_REASON_TEXT_KO["POSITION_MISMATCH"]
        if "POST_FILL" in kr:
            return (
                "체결 후 검증 실패로 안전장치(Kill Switch)가 활성화되었습니다."
            )
    return PRIMARY_REASON_TEXT_KO.get(u)


def secondary_reasons_label(codes: list[Any] | None) -> str:
    if not codes:
        return ""
    parts: list[str] = []
    for c in codes:
        text = primary_reason_text_ko(str(c)) or str(c)
        parts.append(text)
    return " · ".join(parts)
