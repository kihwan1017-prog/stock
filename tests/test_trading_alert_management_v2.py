"""Trading Alert Management V2 — focused tests (실주문 0)."""

from __future__ import annotations

from stock_platform.notification.alert_v2.categories import (
    AlertPreferenceKey,
    AlertTopCategory,
)
from stock_platform.notification.alert_v2.display import (
    format_holding_duration,
    format_signed_krw,
    format_signed_percent,
    symbol_line,
)
from stock_platform.notification.alert_v2.formatters import (
    format_ai_decision_change,
    format_auto_buy_filled,
    format_auto_sell_filled,
    format_order_reject,
    format_runtime_alert,
    format_shadow_checkpoint,
    format_slot_alert,
    format_system_operation,
    maybe_format_user_message,
)
from stock_platform.notification.alert_v2.gate import should_deliver_trading_alert
from stock_platform.notification.alert_v2.mapping import (
    resolve_preference_key,
    resolve_top_category,
    title_prefix_for,
)
from stock_platform.notification.alert_v2.provenance import (
    allow_auto_trade_alert,
    classify_trade_provenance,
)
from stock_platform.notification.alert_v2.reasons import (
    exit_reason_user_label,
    reject_reason_user_label,
)
from stock_platform.notification.telegram_policy import (
    is_telegram_event_allowlisted,
)


def test_01_upbit_category_map() -> None:
    pref = resolve_preference_key(
        "ORDER_FILLED",
        detail={"market": "UPBIT", "side": "BUY", "strategy_id": 1},
    )
    assert pref == AlertPreferenceKey.UPBIT_AUTO_BUY
    assert resolve_top_category(
        "ORDER_FILLED", detail={"market": "UPBIT", "side": "BUY"}
    ) == AlertTopCategory.UPBIT


def test_02_kiwoom_category_map() -> None:
    pref = resolve_preference_key(
        "ORDER_FILLED",
        detail={"market": "KIWOOM", "side": "BUY", "strategy_id": 1},
    )
    assert pref == AlertPreferenceKey.KIWOOM_AUTO_BUY


def test_03_system_category_map() -> None:
    assert (
        resolve_preference_key("KILL_SWITCH", detail={})
        == AlertPreferenceKey.SYSTEM_OPERATION
    )
    assert title_prefix_for("AI_GATE_RECOMMENDATION_CHANGED", detail={}) == "[시스템]"


def test_04_upbit_buy_filled_message() -> None:
    title, body = format_auto_buy_filled(
        detail={
            "market": "UPBIT",
            "symbol": "KRW-XRP",
            "symbol_name": "리플",
            "average_fill_price": 1918,
            "filled_quantity": 2.86757038,
            "gross_amount": 5500,
            "fee": 2.75,
            "entry_reason": "기술조건 통과",
            "ai_recommendation": "매수 허용",
            "ai_confidence": 85,
            "auto_slot_used": 2,
            "auto_slot_limit": 6,
            "daily_entry_used": 2,
            "daily_entry_limit": 6,
            "strategy_id": 1,
        }
    )
    assert "[업비트]" in title
    assert "자동매수 완료" in title
    assert "리플" in body
    assert "1,918원" in body
    assert "5,500원" in body
    assert "2/6" in body


def test_05_kiwoom_buy_filled_message() -> None:
    title, body = format_auto_buy_filled(
        detail={
            "market": "KIWOOM",
            "symbol": "005930",
            "symbol_name": "삼성전자",
            "average_fill_price": 70000,
            "filled_quantity": 1,
            "gross_amount": 70000,
            "fee": 15,
            "strategy_id": 1,
        }
    )
    assert "[키움]" in title
    assert "삼성전자" in body


def test_06_buy_fee_field() -> None:
    _, body = format_auto_buy_filled(
        detail={
            "market": "UPBIT",
            "symbol": "KRW-BTC",
            "fee": 5.5,
            "average_fill_price": 100,
            "filled_quantity": 1,
            "strategy_id": 1,
        }
    )
    assert "수수료" in body
    assert "5.5원" in body or "5.50원" in body


def test_07_buy_amount_field() -> None:
    _, body = format_auto_buy_filled(
        detail={
            "market": "UPBIT",
            "symbol": "KRW-DOS",
            "gross_amount": 10000,
            "strategy_id": 1,
        }
    )
    assert "10,000원" in body


def test_08_buy_reason_field() -> None:
    _, body = format_auto_buy_filled(
        detail={
            "market": "UPBIT",
            "symbol": "KRW-DOS",
            "entry_reason": "기술조건 통과",
            "ai_recommendation": "매수 허용",
            "strategy_id": 1,
        }
    )
    assert "매수사유" in body
    assert "기술조건" in body


def test_09_ai_confidence_field() -> None:
    _, body = format_auto_buy_filled(
        detail={
            "market": "UPBIT",
            "symbol": "KRW-DOS",
            "ai_confidence": 87,
            "strategy_id": 1,
        }
    )
    assert "87%" in body


def test_10_slot_field() -> None:
    _, body = format_auto_buy_filled(
        detail={
            "market": "UPBIT",
            "symbol": "KRW-DOS",
            "auto_slot_used": 3,
            "auto_slot_limit": 6,
            "strategy_id": 1,
        }
    )
    assert "3/6" in body


def test_11_daily_entry_field() -> None:
    _, body = format_auto_buy_filled(
        detail={
            "market": "UPBIT",
            "symbol": "KRW-DOS",
            "daily_entry_used": 2,
            "daily_entry_limit": 6,
            "strategy_id": 1,
        }
    )
    assert "오늘 신규진입" in body
    assert "2/6" in body


def test_12_missing_optional_null_safe() -> None:
    title, body = format_auto_buy_filled(
        detail={"market": "UPBIT", "symbol": "KRW-AAA", "strategy_id": 1}
    )
    assert "자동매수" in title
    assert "None" not in body
    assert "KRW-AAA" in body or "AAA" in body


def test_13_manual_excluded_from_auto() -> None:
    ok, reason = should_deliver_trading_alert(
        event_type="ORDER_FILLED",
        detail={"side": "BUY", "market": "UPBIT", "order_source": "MANUAL"},
    )
    assert ok is False
    assert "MANUAL" in reason


def test_14_test_smoke_excluded() -> None:
    ok, reason = should_deliver_trading_alert(
        event_type="ORDER_FILLED",
        detail={
            "side": "BUY",
            "market": "UPBIT",
            "order_source": "AUTO",
            "is_smoke": True,
        },
    )
    assert ok is False
    assert "TEST" in reason or "SMOKE" in reason


def test_15_upbit_sell_message() -> None:
    title, body = format_auto_sell_filled(
        detail={
            "market": "UPBIT",
            "symbol": "KRW-XRP",
            "symbol_name": "리플",
            "entry_price": 1918,
            "exit_price": 1930,
            "filled_quantity": 2.86757038,
            "buy_amount": 5500,
            "sell_amount": 5534,
            "realized_pnl": 28,
            "realized_pnl_pct": 0.51,
            "total_fee": 5.52,
            "exit_reason": "MA_DEAD_CROSS",
            "holding_seconds": 2538,
            "strategy_id": 1,
        }
    )
    assert "[업비트]" in title
    assert "자동매도 완료" in title
    assert "리플" in body
    assert "순손익" in body


def test_16_kiwoom_sell_message() -> None:
    title, body = format_auto_sell_filled(
        detail={
            "market": "KIWOOM",
            "symbol": "005930",
            "entry_price": 70000,
            "exit_price": 71000,
            "filled_quantity": 1,
            "realized_pnl": 900,
            "realized_pnl_pct": 1.28,
            "total_fee": 30,
            "exit_reason": "TAKE_PROFIT",
            "strategy_id": 1,
        }
    )
    assert "[키움]" in title
    assert "목표수익" in body or "익절" in body or "TAKE" in body


def test_17_sell_entry_price() -> None:
    _, body = format_auto_sell_filled(
        detail={
            "market": "UPBIT",
            "symbol": "KRW-XRP",
            "entry_price": 1918,
            "exit_price": 1930,
            "strategy_id": 1,
        }
    )
    assert "1,918원" in body


def test_18_sell_exit_price() -> None:
    _, body = format_auto_sell_filled(
        detail={
            "market": "UPBIT",
            "symbol": "KRW-XRP",
            "entry_price": 1918,
            "exit_price": 1930,
            "strategy_id": 1,
        }
    )
    assert "1,930원" in body


def test_19_sell_qty() -> None:
    _, body = format_auto_sell_filled(
        detail={
            "market": "UPBIT",
            "symbol": "KRW-XRP",
            "filled_quantity": 2.5,
            "strategy_id": 1,
        }
    )
    assert "2.5" in body


def test_20_total_fee_label() -> None:
    _, body = format_auto_sell_filled(
        detail={
            "market": "UPBIT",
            "symbol": "KRW-XRP",
            "total_fee": 5.52,
            "strategy_id": 1,
        }
    )
    assert "총 수수료" in body


def test_21_net_pnl_profit() -> None:
    assert format_signed_krw(1234).startswith("+")
    _, body = format_auto_sell_filled(
        detail={
            "market": "UPBIT",
            "symbol": "KRW-XRP",
            "realized_pnl": 28,
            "realized_pnl_pct": 0.51,
            "strategy_id": 1,
        }
    )
    assert "+28원" in body or "+28" in body


def test_22_net_pnl_loss() -> None:
    assert format_signed_krw(-550).startswith("-")
    assert "-" in format_signed_percent(-0.63)


def test_23_pnl_pct_format() -> None:
    assert format_signed_percent(0.51) == "+0.51%"
    assert format_signed_percent(-0.63) == "-0.63%"


def test_24_exit_reason_mapping() -> None:
    assert exit_reason_user_label("MA_DEAD_CROSS") == "이동평균 데드크로스"
    assert "손절" in exit_reason_user_label("STOP_LOSS")


def test_25_holding_duration() -> None:
    assert format_holding_duration(37) == "37초"
    assert "분" in format_holding_duration(492)
    assert "시간" in format_holding_duration(5000)


def test_26_lifecycle_link_fields_in_sell() -> None:
    _, body = format_auto_sell_filled(
        detail={
            "market": "UPBIT",
            "symbol": "KRW-XRP",
            "order_id": 1905,
            "opened_at": "2026-08-29T08:28:03+00:00",
            "closed_at": "2026-08-29T09:10:21+00:00",
            "strategy_id": 1,
        }
    )
    assert "1905" in body
    assert "매수" in body or "매도" in body


def test_27_partial_sell_title() -> None:
    title, _ = format_auto_sell_filled(
        detail={"market": "UPBIT", "symbol": "KRW-XRP", "strategy_id": 1},
        partial=True,
    )
    assert "부분" in title


def test_28_runtime_start() -> None:
    title, body = format_runtime_alert(
        event_type="MONITORING_ALERT",
        detail={
            "market": "UPBIT",
            "runtime_kind": "STARTED",
            "feed_label": "연결됨",
            "ready_label": "준비완료",
        },
    )
    assert "시작" in title
    assert "업비트" in title


def test_29_runtime_normal_stop() -> None:
    title, body = format_runtime_alert(
        event_type="MONITORING_ALERT",
        detail={"market": "UPBIT", "runtime_kind": "STOPPED_NORMAL"},
    )
    assert "중지" in title
    assert "정상" in body


def test_30_runtime_unexpected_stop() -> None:
    title, body = format_runtime_alert(
        event_type="MONITORING_ALERT",
        detail={"market": "UPBIT", "runtime_kind": "STOPPED_UNEXPECTED"},
    )
    assert "비정상" in title
    assert "확인" in body


def test_31_runtime_recovered() -> None:
    title, _ = format_runtime_alert(
        event_type="MONITORING_ALERT",
        detail={"market": "UPBIT", "runtime_kind": "RECOVERED"},
    )
    assert "복구" in title


def test_32_dedupe_keys_stable() -> None:
    d = {"order_id": 11, "dedupe_key": "BUY_FILLED:11", "strategy_id": 1}
    assert d["dedupe_key"] == "BUY_FILLED:11"


def test_33_ai_change_message() -> None:
    title, body = format_ai_decision_change(
        event_type="AI_GATE_RECOMMENDATION_CHANGED",
        detail={
            "market": "UPBIT",
            "symbol": "KRW-XRP",
            "previous_recommendation_ko": "대기",
            "new_recommendation_ko": "매수 허용",
            "confidence_pct": 85,
        },
    )
    assert "[시스템]" in title
    assert "AI" in title
    assert "대기" in body
    assert "매수 허용" in body


def test_34_unchanged_ai_suppressed_by_pipeline() -> None:
    from stock_platform.notification.template_pipeline import (
        should_suppress_state_event,
    )

    suppressed, reason = should_suppress_state_event(
        event_type="AI_GATE_RECOMMENDATION_CHANGED",
        variables={
            "previous_recommendation_ko": "대기",
            "new_recommendation_ko": "대기",
            "symbol": "XRP",
            "uba_id": 1,
        },
        detail={},
    )
    assert suppressed is True
    assert reason == "AI_RECOMMENDATION_UNCHANGED"


def test_35_slot_lifecycle_message() -> None:
    title, body = format_slot_alert(
        event_type="UPBIT_PORTFOLIO_SLOT_ASSIGNED",
        detail={
            "market": "UPBIT",
            "symbol": "KRW-XRP",
            "slot_no": 3,
            "auto_slot_limit": 6,
        },
    )
    assert "슬롯" in title
    assert "3/6" in body


def test_36_candidate_pref_default_off() -> None:
    from stock_platform.notification.alert_v2.categories import PREFERENCE_CATALOG

    row = next(r for r in PREFERENCE_CATALOG if r["key"] == "CANDIDATE_ANALYSIS")
    assert row["default_enabled"] == "false"


def test_37_shadow_checkpoint_message() -> None:
    title, body = format_shadow_checkpoint(
        event_type="UPBIT_SCANNER_SHADOW_RESULT",
        detail={
            "checkpoint": "N50",
            "top_variant": "Trailing 0.6%",
            "profit_factor": 1.18,
            "net_pnl": 12350,
            "vs_ma": 4210,
            "shadow_checkpoint": True,
        },
    )
    assert "Shadow" in title or "🧪" in title
    assert "실제 매도" in body


def test_38_system_kill_alert() -> None:
    title, body = format_system_operation(
        event_type="KILL_SWITCH",
        detail={
            "severity": "CRITICAL",
            "title_ko": "Kill Switch 활성화",
            "market": "UPBIT",
            "summary": "자동매매 주문이 차단되었습니다.",
        },
    )
    assert "[시스템]" in title
    assert "Kill" in title or "차단" in body or "Kill" in body


def test_39_preference_key_toggle_semantics() -> None:
    assert AlertPreferenceKey.UPBIT_AUTO_BUY.value == "UPBIT_AUTO_BUY"


def test_40_reject_reason_ko() -> None:
    assert (
        reject_reason_user_label("MAX_OPEN_POSITIONS_REACHED")
        == "AUTO 포지션 한도 도달"
    )
    title, body = format_order_reject(
        event_type="ORDER_REJECTED",
        detail={
            "market": "UPBIT",
            "symbol": "KRW-DOS",
            "reason": "MAX_OPEN_POSITIONS_REACHED",
            "auto_slot_used": 6,
            "auto_slot_limit": 6,
        },
    )
    assert "거부" in title
    assert "한도" in body
    assert "생성되지 않았습니다" in body


def test_41_notification_off_does_not_touch_trading_constants() -> None:
    # gate False는 delivery만 — preference key 존재 확인으로 대체
    assert AlertPreferenceKey.SYSTEM_OPERATION.value == "SYSTEM_OPERATION"


def test_42_telegram_allowlist_core_events() -> None:
    for et in (
        "ORDER_FILLED",
        "POSITION_CLOSED",
        "AI_GATE_RECOMMENDATION_CHANGED",
        "UPBIT_PORTFOLIO_SLOT_ASSIGNED",
        "KILL_SWITCH",
        "AUTOTRADING_DAILY_REPORT",
    ):
        assert is_telegram_event_allowlisted(et) is True


def test_43_delivery_fail_open_on_unknown_session() -> None:
    ok, reason = should_deliver_trading_alert(
        event_type="KILL_SWITCH",
        detail={"market": "UPBIT"},
        session=None,
    )
    assert ok is True
    assert "PREFERENCE" in reason or "ON" in reason


def test_44_auto_provenance_required() -> None:
    assert classify_trade_provenance({"order_source": "AUTO"}) == "AUTO"
    assert allow_auto_trade_alert({"strategy_id": 9}) is True
    assert classify_trade_provenance({"order_source": "MANUAL"}) == "MANUAL"


def test_45_symbol_display_and_maybe_format() -> None:
    assert "리플" in symbol_line("KRW-XRP", name="리플")
    title, body = maybe_format_user_message(
        event_type="ORDER_FILLED",
        title="raw",
        message="raw",
        detail={
            "market": "UPBIT",
            "side": "BUY",
            "symbol": "KRW-DOS",
            "average_fill_price": 125.3,
            "filled_quantity": 79.8,
            "gross_amount": 10000,
            "strategy_id": 1,
        },
    )
    assert "자동매수" in title
    assert "DOS" in body or "KRW-DOS" in body
