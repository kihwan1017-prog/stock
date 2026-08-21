"""내장 ko-KR 템플릿 시드 — DB 없을 때 fallback + 초기 seed."""

from __future__ import annotations

from typing import Any

# channel: TELEGRAM (multiline) / TOSS (short) / COMMON
BUILTIN_TEMPLATES: list[dict[str, Any]] = [
    {
        "event_type": "ORDER_SUBMITTED",
        "category": "TRADE",
        "severity": "INFO",
        "title_template": "📤 {broker_ko} 주문 제출",
        "body_template": (
            "종목: {symbol_display}\n"
            "구분: {side_ko}\n"
            "수량: {quantity}\n"
            "주문가격: {price_display}\n"
            "전략: {strategy_name}"
        ),
        "short_body_template": "{symbol_display} {side_ko} 제출 · {price_display}",
    },
    {
        "event_type": "PORTFOLIO_BULLISH_STATE_ENTRY",
        "category": "TRADE",
        "severity": "INFO",
        "title_template": "📈 자동매매 매수 조건 충족",
        "body_template": (
            "종목: {symbol_display}\n"
            "Scanner 점수: {scanner_score}\n"
            "AI: {ai_recommendation_ko}\n"
            "추세: short MA > long MA\n"
            "RSI: {rsi14}\n"
            "주문 예정금액: {approved_amount_krw}"
        ),
        "short_body_template": "{symbol_display} 매수조건 충족 · {approved_amount_krw}",
    },
    {
        "event_type": "ORDER_FILLED",
        "category": "TRADE",
        "severity": "SUCCESS",
        "title_template": "✅ {broker_ko} {side_ko} 체결",
        "body_template": (
            "종목: {symbol_display}\n"
            "체결금액: {amount_krw}\n"
            "체결가: {avg_price}\n"
            "수량: {filled_qty}\n"
            "전략: {strategy_name}\n"
            "상태: {position_status_ko}"
        ),
        "short_body_template": "{symbol_display} {amount_krw} {side_ko} 완료 · {avg_price}",
    },
    {
        "event_type": "ORDER_PARTIAL_FILLED",
        "category": "TRADE",
        "severity": "INFO",
        "title_template": "🔸 {broker_ko} 부분 체결",
        "body_template": (
            "종목: {symbol_display}\n"
            "구분: {side_ko}\n"
            "체결수량: {filled_qty}\n"
            "체결가: {avg_price}"
        ),
        "short_body_template": "{symbol_display} 부분체결 {filled_qty}",
    },
    {
        "event_type": "ORDER_CANCELLED",
        "category": "TRADE",
        "severity": "WARNING",
        "title_template": "⚪ 주문 취소",
        "body_template": (
            "종목: {symbol_display}\n"
            "구분: {side_ko}\n"
            "사유: {reason_ko}"
        ),
        "short_body_template": "{symbol_display} 주문 취소",
    },
    {
        "event_type": "ORDER_REJECTED",
        "category": "TRADE",
        "severity": "WARNING",
        "title_template": "❌ 주문 거부",
        "body_template": (
            "종목: {symbol_display}\n"
            "구분: {side_ko}\n"
            "사유: {reason_ko}\n"
            "계좌: {account_display}"
        ),
        "short_body_template": "{symbol_display} 주문 거부 · {reason_ko}",
    },
    {
        "event_type": "TAKE_PROFIT",
        "category": "TRADE",
        "severity": "SUCCESS",
        "title_template": "✅ 익절 체결",
        "body_template": (
            "종목: {symbol_display}\n"
            "체결금액: {amount_krw}\n"
            "체결가: {avg_price}"
        ),
        "short_body_template": "{symbol_display} 익절 · {amount_krw}",
    },
    {
        "event_type": "STOP_LOSS",
        "category": "TRADE",
        "severity": "WARNING",
        "title_template": "⚠️ 손절 체결",
        "body_template": (
            "종목: {symbol_display}\n"
            "체결금액: {amount_krw}\n"
            "체결가: {avg_price}"
        ),
        "short_body_template": "{symbol_display} 손절 · {amount_krw}",
    },
    {
        "event_type": "TRAILING_STOP",
        "category": "TRADE",
        "severity": "WARNING",
        "title_template": "⚠️ 트레일링 스탑",
        "body_template": (
            "종목: {symbol_display}\n"
            "체결금액: {amount_krw}\n"
            "체결가: {avg_price}"
        ),
        "short_body_template": "{symbol_display} 트레일링 스탑",
    },
    {
        "event_type": "AI_GATE_RECOMMENDATION_CHANGED",
        "category": "AI",
        "severity": "INFO",
        "title_template": "📊 AI 매매 판단 변경",
        "body_template": (
            "종목: {symbol_display}\n"
            "이전: {previous_recommendation_ko}\n"
            "현재: {new_recommendation_ko}\n"
            "신뢰도: {confidence_pct}"
        ),
        "short_body_template": (
            "{symbol_display} {previous_recommendation_ko} → {new_recommendation_ko}"
        ),
    },
    {
        "event_type": "UPBIT_SCANNER_CANDIDATE",
        "category": "PORTFOLIO",
        "severity": "INFO",
        "title_template": "🔎 자동매매 후보 선정",
        "body_template": (
            "종목: {symbol_display}\n"
            "순위: {rank}\n"
            "Scanner 점수: {scanner_score}\n"
            "AI: {ai_recommendation_ko}\n"
            "신뢰도: {confidence_pct}\n"
            "포지션 슬롯: {slot_no}\n"
            "{candidates_summary}"
        ),
        "short_body_template": "후보 {symbol_display} · AI {ai_recommendation_ko}",
    },
    {
        "event_type": "KILL_SWITCH",
        "category": "CRITICAL",
        "severity": "CRITICAL",
        "title_template": "🚨 Kill Switch 작동",
        "body_template": (
            "계좌: {account_display}\n"
            "원인: {reason_ko}\n"
            "시각: {created_at_kst}\n"
            "\n"
            "신규 주문이 차단되었습니다."
        ),
        "short_body_template": "Kill Switch · {account_display} · {reason_ko}",
    },
    {
        "event_type": "DAILY_LOSS",
        "category": "RISK",
        "severity": "CRITICAL",
        "title_template": "⚠️ 일일 손실 한도",
        "body_template": (
            "계좌: {account_display}\n"
            "원인: {reason_ko}\n"
            "현재: {current_value}\n"
            "한도: {limit_value}"
        ),
        "short_body_template": "일일손실 한도 · {account_display}",
    },
    {
        "event_type": "RECOVERY_STARTED",
        "category": "RECOVERY",
        "severity": "INFO",
        "title_template": "🔄 계좌 복구 시작",
        "body_template": "계좌: {account_display}\n사유: {reason_ko}",
        "short_body_template": "복구 시작 · {account_display}",
    },
    {
        "event_type": "RECOVERY_FAILED",
        "category": "CRITICAL",
        "severity": "CRITICAL",
        "title_template": "🚨 계좌 복구 실패",
        "body_template": "계좌: {account_display}\n사유: {reason_ko}",
        "short_body_template": "복구 실패 · {account_display}",
    },
    {
        "event_type": "RECOVERY_CONFLICT",
        "category": "RECOVERY",
        "severity": "WARNING",
        "title_template": "⚠️ 주문/포지션 정합성 확인 필요",
        "body_template": (
            "계좌: {account_display}\n"
            "원인: {reason_ko}\n"
            "상세는 관리자 화면에서 확인하세요."
        ),
        "short_body_template": "정합성 충돌 · {account_display}",
    },
    {
        "event_type": "RECONCILIATION_MISMATCH",
        "category": "CRITICAL",
        "severity": "CRITICAL",
        "title_template": "🚨 포지션 정합성 불일치",
        "body_template": (
            "계좌: {account_display}\n"
            "종목: {symbol_display}\n"
            "원인: {reason_ko}"
        ),
        "short_body_template": "정합성 불일치 · {symbol_display}",
    },
    {
        "event_type": "SYSTEM_START",
        "category": "SYSTEM",
        "severity": "INFO",
        "title_template": "🟢 자동매매 서버 시작",
        "body_template": "{message}",
        "short_body_template": "서버 시작",
    },
    {
        "event_type": "SYSTEM_STOP",
        "category": "SYSTEM",
        "severity": "WARNING",
        "title_template": "🔴 자동매매 서버 중지",
        "body_template": "{message}",
        "short_body_template": "서버 중지",
    },
    {
        "event_type": "RUNTIME_STARTED",
        "category": "SYSTEM",
        "severity": "INFO",
        "title_template": "🟢 전략 Runtime 시작",
        "body_template": "계좌: {account_display}\n상태: {runtime_status_ko}",
        "short_body_template": "Runtime 시작",
    },
    {
        "event_type": "RUNTIME_PAUSED",
        "category": "SYSTEM",
        "severity": "WARNING",
        "title_template": "🟡 전략 Runtime 일시정지",
        "body_template": "계좌: {account_display}\n사유: {reason_ko}",
        "short_body_template": "Runtime 일시정지",
    },
    {
        "event_type": "SCHEDULER_STARTED",
        "category": "SYSTEM",
        "severity": "INFO",
        "title_template": "🟢 스케줄러 시작",
        "body_template": "{message}",
        "short_body_template": "스케줄러 시작",
    },
    {
        "event_type": "SCHEDULER_PAUSED",
        "category": "SYSTEM",
        "severity": "WARNING",
        "title_template": "🟡 스케줄러 일시정지",
        "body_template": "{message}",
        "short_body_template": "스케줄러 일시정지",
    },
    {
        "event_type": "SCHEDULER_ERROR",
        "category": "CRITICAL",
        "severity": "CRITICAL",
        "title_template": "🚨 스케줄러 오류",
        "body_template": "사유: {reason_ko}\n{message}",
        "short_body_template": "스케줄러 오류",
    },
    {
        "event_type": "BROKER_DISCONNECTED",
        "category": "CRITICAL",
        "severity": "CRITICAL",
        "title_template": "🚨 브로커 연결 끊김",
        "body_template": "브로커: {broker_ko}\n계좌: {account_display}\n사유: {reason_ko}",
        "short_body_template": "{broker_ko} 연결 끊김",
    },
    {
        "event_type": "BROKER_RECONNECTED",
        "category": "SYSTEM",
        "severity": "SUCCESS",
        "title_template": "✅ 브로커 재연결",
        "body_template": "브로커: {broker_ko}\n계좌: {account_display}",
        "short_body_template": "{broker_ko} 재연결",
    },
    {
        "event_type": "DATABASE_ERROR",
        "category": "CRITICAL",
        "severity": "CRITICAL",
        "title_template": "🚨 데이터베이스 오류",
        "body_template": "{message}",
        "short_body_template": "DB 오류",
    },
    {
        "event_type": "MONITORING_ALERT",
        "category": "WARNING",
        "severity": "WARNING",
        "title_template": "⚠️ 모니터링 알림",
        "body_template": "{message}\n사유: {reason_ko}",
        "short_body_template": "모니터링 · {reason_ko}",
    },
    {
        "event_type": "SAME_SYMBOL_MANUAL_AUTO_CONFLICT",
        "category": "WARNING",
        "severity": "WARNING",
        "title_template": "⚠️ 자동/일반매매 충돌",
        "body_template": (
            "종목: {symbol_display}\n"
            "사유: {reason_ko}\n"
            "해당 종목 자동매매를 일시 중지합니다."
        ),
        "short_body_template": "충돌 · {symbol_display}",
    },
    {
        "event_type": "AUTO_SYMBOL_EXCLUDED_MANUAL_POSITION",
        "category": "PORTFOLIO",
        "severity": "INFO",
        "title_template": "ℹ️ 자동매매 후보 제외",
        "body_template": (
            "종목: {symbol_display}\n"
            "사유: {reason_ko}"
        ),
        "short_body_template": "제외 · {symbol_display}",
    },
    {
        "event_type": "TEST_NOTIFICATION",
        "category": "DEBUG",
        "severity": "INFO",
        "title_template": "🧪 알림 전송 테스트",
        "body_template": "{message}\n이 메시지는 테스트용입니다. 실주문이 아닙니다.",
        "short_body_template": "알림 테스트",
    },
    {
        "event_type": "GENERIC",
        "category": "INFO",
        "severity": "INFO",
        "title_template": "ℹ️ 시스템 알림",
        "body_template": "유형: {event_type}\n내용: {message}",
        "short_body_template": "{event_type}",
    },
]


def builtin_template_for(event_type: str) -> dict[str, Any]:
    et = str(event_type or "").upper()
    for row in BUILTIN_TEMPLATES:
        if row["event_type"] == et:
            return row
    return next(r for r in BUILTIN_TEMPLATES if r["event_type"] == "GENERIC")
