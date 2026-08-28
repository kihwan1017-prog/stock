"""User-facing friendly reasons for persisted reject codes — coverage SoT."""

from __future__ import annotations

from typing import Any

# canonical reason_code → 사용자 문구 (raw code는 상세보기)
USER_REASON_MAP: dict[str, str] = {
    "SIGNAL_EMIT_SUPPRESSED": (
        "같은 후보/신호에서 이미 진입 신호가 처리되어 추가 주문을 만들지 않았습니다."
    ),
    "PENDING_ENTRY_LIMIT": (
        "다른 종목의 매수 주문이 처리 중이어서 이번 진입은 대기/제외되었습니다."
    ),
    "NO_WAITING_SIGNAL_SLOT": "해당 종목의 관찰(WAITING) 슬롯이 없습니다.",
    "MANUAL_SYMBOL_EXCLUDED": "수동 보유 종목으로 자동 매수 대상에서 제외되었습니다.",
    "SYMBOL_OWNERSHIP_BLOCKED": "종목 소유권 정책으로 자동 매수가 차단되었습니다.",
    "SYMBOL_OWNERSHIP_UNKNOWN": "종목 소유권을 확인할 수 없어 매수를 보류했습니다.",
    "POLICY_DISABLED": "포트폴리오 자동매매 정책이 비활성화되어 있습니다.",
    "ENTRY_PAUSED": "진입이 일시 중지된 상태입니다.",
    "SYMBOL_REQUIRED": "종목 정보가 없어 진입을 처리할 수 없습니다.",
    "PORTFOLIO_DAILY_ENTRY_LIMIT": "일일 REAL AUTO BUY 한도에 도달했습니다.",
    "WAITING_REVALIDATION_REQUIRED": "WAITING 재검증 게이트를 통과하지 못했습니다.",
    "ALLOCATION_SKIPPED": "자금/리스크 배분 결과 주문 금액이 0입니다.",
    "PORTFOLIO_PENDING_ENTRY_LIMIT": (
        "다른 종목의 매수 주문이 처리 중이어서 이번 진입은 대기/제외되었습니다."
    ),
    "PORTFOLIO_NO_WAITING_SIGNAL_SLOT": "해당 종목의 관찰(WAITING) 슬롯이 없습니다.",
    "PORTFOLIO_PORTFOLIO_DAILY_ENTRY_LIMIT": "일일 REAL AUTO BUY 한도에 도달했습니다.",
    "PORTFOLIO_ALLOCATION_SKIPPED": "자금/리스크 배분 결과 주문 금액이 0입니다.",
    "PORTFOLIO_WAITING_REVALIDATION_REQUIRED": "WAITING 재검증 게이트를 통과하지 못했습니다.",
    "PORTFOLIO_POLICY_DISABLED": "포트폴리오 자동매매 정책이 비활성화되어 있습니다.",
    "PORTFOLIO_ENTRY_PAUSED": "진입이 일시 중지된 상태입니다.",
    "FULL_MARKET_ASSIGNMENT_BLOCKED": "Full-market 배정 정책으로 진입이 차단되었습니다.",
    "FULL_MARKET_GATE_FAILED": "Full-market 게이트 오류로 진입을 처리하지 못했습니다.",
    "ACCOUNT_PAUSED": "계좌 거래가 일시 중지되어 있습니다.",
    "ACCOUNT_PAUSE_CHECK_FAILED": "계좌 일시중지 상태를 확인하지 못해 매수를 보류했습니다.",
    "KILL_SWITCH_UNAVAILABLE": "Kill Switch 상태를 확인하지 못해 매수를 보류했습니다.",
    "GLOBAL_KILL_SWITCH_ACTIVE": "Kill Switch가 활성화되어 매수가 차단되었습니다.",
    "RISK_ENGINE_BLOCKED": "리스크 엔진에서 매수가 차단되었습니다.",
    "AI_GATE_EXCEPTION": "AI 게이트 오류로 매수를 보류했습니다.",
    "AI_GATE_REDUCE_ZERO_AMOUNT": "AI 게이트 축소 결과 주문 금액이 0입니다.",
    "AI_GATE_REDUCE_ZERO_QTY": "AI 게이트 축소 결과 주문 수량이 0입니다.",
    "ORDER_PERSIST_FAILED": "주문 저장에 실패했습니다 (시스템).",
    "ORDER_OUTBOX_ENQUEUE_FAILED": "주문 Outbox 등록에 실패했습니다 (시스템).",
    "BROKER_SUBMIT_FAILED": "거래소 주문 전송에 실패했습니다 (시스템).",
    "DATA_TRUST_BLOCK": "데이터 신뢰 구간이 유효하지 않아 매수를 보류했습니다.",
    "FEED_STALE": "시세 데이터가 오래되어 매수를 보류했습니다.",
    "RUN_GATE_FAILED": "런타임 실행 게이트에서 매수가 차단되었습니다.",
}


def normalize_portfolio_reason(reason: str | None) -> str:
    """PORTFOLIO_ prefix 제거 후 canonical code."""
    r = str(reason or "").strip()
    if r.startswith("PORTFOLIO_"):
        return r[len("PORTFOLIO_") :]
    return r


def friendly_reason(reason_code: str | None) -> str | None:
    if not reason_code:
        return None
    code = str(reason_code).strip()
    if code in USER_REASON_MAP:
        return USER_REASON_MAP[code]
    bare = normalize_portfolio_reason(code)
    if bare in USER_REASON_MAP:
        return USER_REASON_MAP[bare]
    if code.startswith("FULL_MARKET_"):
        sub = code[len("FULL_MARKET_") :]
        return USER_REASON_MAP.get(sub) or f"Full-market 정책({sub})으로 진입이 차단되었습니다."
    return None


def user_reason_coverage(*, observed_codes: set[str]) -> dict[str, Any]:
    """unique observed/canonical reason 기준 coverage — 140% 방지."""
    if not observed_codes:
        return {
            "USER_REASON_COVERAGE_PERCENT": 100.0,
            "MISSING_USER_REASON_CODES": [],
            "OBSERVED_COUNT": 0,
            "MAPPED_COUNT": 0,
        }
    missing: list[str] = []
    mapped = 0
    for code in sorted(observed_codes):
        if friendly_reason(code):
            mapped += 1
        else:
            missing.append(code)
    pct = round(100.0 * mapped / len(observed_codes), 1)
    return {
        "USER_REASON_COVERAGE_PERCENT": pct,
        "MISSING_USER_REASON_CODES": missing,
        "OBSERVED_COUNT": len(observed_codes),
        "MAPPED_COUNT": mapped,
    }
