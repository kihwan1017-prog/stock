"""Focused tests — Korean notification template platform (실주문 0)."""

from __future__ import annotations

from stock_platform.notification.code_dictionary import (
    recommendation_ko,
    side_ko,
    translate,
)
from stock_platform.notification.formatting import (
    format_datetime_kst,
    format_krw,
    format_percent,
    format_symbol,
)
from stock_platform.notification.masking import mask_sensitive
from stock_platform.notification.models import NotificationMessage
from stock_platform.notification.template_pipeline import (
    preview_template,
    render_notification,
    should_suppress_state_event,
)
from stock_platform.notification.template_renderer import (
    extract_placeholders,
    render_template,
)
from stock_platform.notification.telegram_sender import (
    TelegramNotificationSender,
)


def test_krw_and_percent_and_symbol() -> None:
    assert format_krw(10000) == "10,000원"
    assert format_percent(0.95) in {"95%", "95.0%"}
    assert format_symbol("KRW-XRP") == "XRP"
    assert format_symbol("034310", name="NICE") == "034310 (NICE)"


def test_datetime_kst() -> None:
    out = format_datetime_kst("2026-08-21T05:00:00+00:00")
    assert "KST" in out
    assert "2026-08-21" in out


def test_enum_translation() -> None:
    assert side_ko("BUY") == "매수"
    assert recommendation_ko("HOLD") == "대기"
    assert translate("FILLED", group="order_status") == "체결 완료"


def test_missing_variable_does_not_fail() -> None:
    text, missing = render_template(
        "종목: {symbol_display} / {unknown_field}",
        {"symbol_display": "XRP"},
    )
    assert "XRP" in text
    assert "-" in text
    assert "unknown_field" in missing


def test_order_fill_korean_render() -> None:
    rendered = render_notification(
        event_type="ORDER_FILLED",
        title="raw",
        message="raw",
        detail={
            "broker_code": "UPBIT",
            "symbol": "KRW-ETH",
            "side": "BUY",
            "amount_krw": 24000,
            "avg_price": 5320000,
            "filled_qty": 0.00451,
            "strategy_name": "전체시장 포트폴리오",
            "position_status": "OPEN",
        },
        channel="TELEGRAM",
    )
    assert rendered.suppressed is False
    assert "업비트" in rendered.title or "매수" in rendered.title
    assert "ETH" in rendered.body
    assert "24,000원" in rendered.body
    assert "전체시장 포트폴리오" in rendered.body
    assert "json" not in rendered.body.lower()
    assert rendered.original_payload["symbol"] == "KRW-ETH"


def test_ai_change_and_suppress_unchanged() -> None:
    changed = render_notification(
        event_type="AI_GATE_RECOMMENDATION_CHANGED",
        title="x",
        message="y",
        detail={
            "symbol": "KRW-XRP",
            "previous_recommendation": "HOLD",
            "new_recommendation": "ALLOW",
            "confidence": 0.95,
        },
    )
    assert "대기" in changed.body
    assert "매수 허용" in changed.body

    suppressed, reason = should_suppress_state_event(
        event_type="AI_GATE_RECOMMENDATION_CHANGED",
        variables={
            "previous_recommendation_ko": "대기",
            "new_recommendation_ko": "대기",
            "symbol": "XRP",
            "uba_id": "1380",
        },
        detail={},
    )
    assert suppressed is True
    assert reason == "AI_RECOMMENDATION_UNCHANGED"


def test_kill_and_risk_fallback_builtin() -> None:
    kill = render_notification(
        event_type="KILL_SWITCH",
        title="k",
        message="m",
        detail={"broker_code": "KIWOOM", "reason": "포지션 정합성 불일치"},
    )
    assert "Kill Switch" in kill.title
    assert "신규 주문" in kill.body

    risk = render_notification(
        event_type="DAILY_LOSS",
        title="d",
        message="m",
        detail={
            "broker_code": "UPBIT",
            "current_value": "30%",
            "limit_value": "30%",
            "reason": "전체 노출 한도 도달",
        },
    )
    assert "일일 손실" in risk.title


def test_unknown_event_generic_fallback() -> None:
    out = render_notification(
        event_type="TOTALLY_UNKNOWN_EVENT",
        title="hello",
        message="요약 정보",
        detail={},
    )
    assert "시스템 알림" in out.title
    assert "TOTALLY_UNKNOWN_EVENT" in out.body


def test_sensitive_masking() -> None:
    masked = mask_sensitive(
        {"symbol": "KRW-XRP", "access_token": "secret", "nested": {"bot_token": "x"}}
    )
    assert masked["access_token"] == "***"
    assert masked["nested"]["bot_token"] == "***"
    assert masked["symbol"] == "KRW-XRP"


def test_telegram_formatter_no_raw_json_by_default() -> None:
    msg = NotificationMessage(
        title="raw-title",
        message="raw-body",
        detail={"secret_key": "abc", "symbol": "KRW-XRP"},
        rendered_title="✅ 업비트 매수 체결",
        rendered_body="종목: XRP\n체결금액: 10,000원",
        include_raw_json=False,
        original_payload={"symbol": "KRW-XRP"},
    )
    text = TelegramNotificationSender._format_message(msg)
    assert "업비트 매수 체결" in text
    assert "10,000원" in text
    assert "<pre>" not in text
    assert "secret" not in text


def test_toss_short_channel() -> None:
    out = render_notification(
        event_type="ORDER_FILLED",
        title="t",
        message="m",
        detail={
            "broker_code": "UPBIT",
            "symbol": "KRW-XRP",
            "side": "BUY",
            "amount_krw": 10000,
            "avg_price": 1605,
        },
        channel="TOSS",
    )
    # Toss uses short template as body
    assert "XRP" in out.body
    assert "\n종목:" not in out.body or "·" in out.body


def test_preview_and_placeholders() -> None:
    prev = preview_template(
        title_template="✅ {broker_ko} {side_ko} 체결",
        body_template="종목: {symbol_display}\n체결금액: {amount_krw}",
        event_type="ORDER_FILLED",
        sample_detail={
            "broker_code": "UPBIT",
            "side": "BUY",
            "symbol": "KRW-XRP",
            "amount_krw": 10000,
        },
    )
    assert "업비트" in prev["title"]
    assert "XRP" in prev["body"]
    assert "broker_ko" in extract_placeholders(prev["title"] + prev["body"] + "{broker_ko}")


def test_disabled_db_template_falls_back_builtin() -> None:
    out = render_notification(
        event_type="ORDER_FILLED",
        title="t",
        message="m",
        detail={"broker_code": "UPBIT", "symbol": "KRW-XRP", "side": "BUY"},
        db_template={
            "enabled": False,
            "title_template": "DISABLED",
            "body_template": "DISABLED",
        },
    )
    assert "DISABLED" not in out.title
    assert out.source == "builtin"


def test_llm_not_imported_in_pipeline() -> None:
    import stock_platform.notification.template_pipeline as mod

    src = open(mod.__file__, encoding="utf-8").read().lower()
    assert "openai" not in src
    assert "ollama" not in src
    assert "chatcompletion" not in src


def test_nested_candidate_payload_displays_fields() -> None:
    rendered = render_notification(
        event_type="UPBIT_SCANNER_CANDIDATE",
        title="raw",
        message="raw",
        detail={
            "source": "upbit_opportunity_scanner_v0",
            "candidate": {
                "symbol": "KRW-PEPE",
                "rank": 1,
                "score": 76.97345,
                "recommendation": "ALLOW",
                "confidence": 0.95,
            },
            "slot_no": 3,
        },
    )
    assert "PEPE" in rendered.body
    assert "76.97" in rendered.body
    assert "매수 허용" in rendered.body
    assert "95%" in rendered.body
    assert "포지션 슬롯: 3" in rendered.body
    assert rendered.original_payload["candidate"]["symbol"] == "KRW-PEPE"
    assert "json" not in rendered.body.lower()


def test_summary_candidates_list_and_optional_rank_suppress() -> None:
    rendered = render_notification(
        event_type="UPBIT_SCANNER_CANDIDATE",
        title="raw",
        message="raw",
        detail={
            "source": "upbit_opportunity_scanner_v0_summary",
            "candidates": [
                {
                    "symbol": "KRW-GRVT",
                    "rank": 1,
                    "score": 80.26,
                    "recommendation": "HOLD",
                    "confidence": 0.95,
                },
                {
                    "symbol": "KRW-DOS",
                    "score": 61.01,
                    "recommendation": "HOLD",
                    "confidence": 0.85,
                },
            ],
        },
    )
    assert "GRVT" in rendered.body
    assert "후보 목록" in rendered.body
    assert "대기" in rendered.body
    # rank 없는 두 번째 후보도 목록에 포함
    assert "DOS" in rendered.body


def test_optional_rank_missing_line_suppressed() -> None:
    rendered = render_notification(
        event_type="UPBIT_SCANNER_CANDIDATE",
        title="t",
        message="m",
        detail={
            "candidate": {
                "symbol": "KRW-XRP",
                "score": 55.5,
                "recommendation": "ALLOW",
                "confidence": 0.8,
            }
        },
    )
    assert "종목: XRP" in rendered.body
    assert "순위:" not in rendered.body
    assert "포지션 슬롯:" not in rendered.body


def test_required_symbol_missing_diagnostic() -> None:
    rendered = render_notification(
        event_type="UPBIT_SCANNER_CANDIDATE",
        title="t",
        message="m",
        detail={"source": "broken"},
    )
    assert rendered.diagnostic_code == "TEMPLATE_REQUIRED_FIELD_MISSING"
    assert "symbol_display" in rendered.required_missing
    assert "불러오지 못했습니다" in rendered.body
    assert rendered.body.count("종목: -") == 0


def test_contract_audit_no_high_priority_fail() -> None:
    from stock_platform.notification.contract_audit import (
        summarize_contract_audit,
    )

    summary = summarize_contract_audit()
    assert summary["by_status"].get("INVALID_TEMPLATE_VARIABLE", 0) == 0
    assert summary["high_priority_fail"] == []
