"""사용자용 BUY/SELL/Runtime/AI/System 메시지 포맷터."""

from __future__ import annotations

from typing import Any

from stock_platform.notification.alert_v2.display import (
    format_holding_duration,
    format_qty_trim,
    format_signed_krw,
    format_signed_percent,
    symbol_line,
    to_decimal,
)
from stock_platform.notification.alert_v2.mapping import title_prefix_for
from stock_platform.notification.alert_v2.reasons import (
    exit_reason_user_label,
    reject_reason_user_label,
)
from stock_platform.notification.formatting import (
    format_datetime_kst,
    format_krw,
)


def _line(label: str, value: Any) -> str | None:
    if value is None or value == "" or value == "-":
        return None
    return f"{label}: {value}"


def _join(parts: list[str | None]) -> str:
    return "\n".join(p for p in parts if p)


def format_auto_buy_filled(
    *,
    event_type: str = "ORDER_FILLED",
    detail: dict[str, Any],
    partial: bool = False,
) -> tuple[str, str]:
    prefix = title_prefix_for(event_type, detail=detail)
    icon = "🟡" if partial else "🔵"
    head = "자동매수 부분체결" if partial else "자동매수 완료"
    title = f"{prefix} {icon} {head}"

    symbol = detail.get("symbol")
    name = detail.get("symbol_name") or detail.get("name")
    price = detail.get("average_fill_price") or detail.get("avg_fill_price") or detail.get("avg_price")
    qty = detail.get("filled_quantity") or detail.get("filled_qty")
    amount = detail.get("gross_amount") or detail.get("amount_krw") or detail.get("buy_amount")
    fee = detail.get("fee") or detail.get("paid_fee")
    reason = detail.get("entry_reason") or detail.get("technical_reason") or detail.get("signal_reason")
    ai = detail.get("ai_recommendation") or detail.get("ai_recommendation_ko")
    conf = detail.get("ai_confidence") or detail.get("confidence_pct")
    slot_used = detail.get("auto_slot_used")
    slot_limit = detail.get("auto_slot_limit")
    entry_used = detail.get("daily_entry_used")
    entry_limit = detail.get("daily_entry_limit")
    entry_mode = str(detail.get("daily_entry_limit_mode") or "LIMITED").upper()
    filled_at = detail.get("filled_at") or detail.get("ordered_at")

    reason_parts = []
    if reason:
        reason_parts.append(str(reason))
    if ai:
        reason_parts.append(f"AI {ai}")
    reason_text = " · ".join(reason_parts) if reason_parts else None

    slot_text = None
    if slot_used is not None and slot_limit is not None:
        slot_text = f"{slot_used}/{slot_limit}"
    entry_text = None
    if entry_mode == "UNLIMITED" and entry_used is not None:
        # UNLIMITED: "7건 / 제한 없음"
        entry_text = f"{entry_used}건 / 제한 없음"
    elif entry_used is not None and entry_limit is not None:
        entry_text = f"{entry_used}/{entry_limit}"

    body = _join(
        [
            _line("종목", symbol_line(symbol, name=name)),
            _line("매수가", format_krw(price) if to_decimal(price) is not None else None),
            _line(
                "수량",
                f"{format_qty_trim(qty)} {str(symbol or '').replace('KRW-', '')}".strip()
                if qty is not None
                else None,
            ),
            _line("매수금액", format_krw(amount) if to_decimal(amount) is not None else None),
            _line("수수료", format_krw(fee) if to_decimal(fee) is not None else None),
            "",
            _line("매수사유", reason_text),
            _line("AI 신뢰도", f"{conf}%" if conf is not None and str(conf).rstrip("%") else None),
            _line("AUTO 슬롯", slot_text),
            _line("오늘 신규진입", entry_text),
            "",
            _line("체결시간", format_datetime_kst(filled_at) if filled_at else None),
            _line("Order", detail.get("order_id")),
        ]
    )
    return title, body.strip()


def format_auto_sell_filled(
    *,
    event_type: str = "POSITION_CLOSED",
    detail: dict[str, Any],
    partial: bool = False,
) -> tuple[str, str]:
    prefix = title_prefix_for(event_type, detail=detail)
    icon = "🟡" if partial else "🔴"
    head = "자동매도 부분체결" if partial else "자동매도 완료"
    title = f"{prefix} {icon} {head}"

    symbol = detail.get("symbol")
    name = detail.get("symbol_name") or detail.get("name")
    buy_price = detail.get("entry_price") or detail.get("buy_price")
    sell_price = (
        detail.get("exit_price")
        or detail.get("average_fill_price")
        or detail.get("avg_fill_price")
        or detail.get("avg_price")
        or detail.get("sell_price")
    )
    qty = detail.get("filled_quantity") or detail.get("filled_qty")
    buy_amount = detail.get("buy_amount") or detail.get("entry_amount")
    sell_amount = detail.get("sell_amount") or detail.get("exit_amount") or detail.get("gross_amount")
    # 금액 미제공 시 가격×수량 fallback (PnL은 canonical 우선)
    bp = to_decimal(buy_price)
    sp = to_decimal(sell_price)
    q = to_decimal(qty)
    if buy_amount is None and bp is not None and q is not None:
        buy_amount = bp * q
    if sell_amount is None and sp is not None and q is not None:
        sell_amount = sp * q

    total_fee = detail.get("total_fee") or detail.get("fees") or detail.get("fee")
    net = detail.get("realized_pnl") or detail.get("net_pnl")
    pct = detail.get("realized_pnl_pct") or detail.get("pnl_rate") or detail.get("pnl_pct")
    exit_reason = exit_reason_user_label(
        detail.get("exit_reason") or detail.get("signal_reason")
    )
    hold = format_holding_duration(detail.get("holding_seconds"))
    buy_time = detail.get("entry_filled_at") or detail.get("buy_time") or detail.get("opened_at")
    sell_time = detail.get("exit_filled_at") or detail.get("sell_time") or detail.get("filled_at") or detail.get("closed_at")

    body = _join(
        [
            _line("종목", symbol_line(symbol, name=name)),
            "",
            _line("매수가", format_krw(buy_price) if to_decimal(buy_price) is not None else None),
            _line("매도가", format_krw(sell_price) if to_decimal(sell_price) is not None else None),
            _line(
                "수량",
                f"{format_qty_trim(qty)} {str(symbol or '').replace('KRW-', '')}".strip()
                if qty is not None
                else None,
            ),
            "",
            _line("매수금액", format_krw(buy_amount) if to_decimal(buy_amount) is not None else None),
            _line("매도금액", format_krw(sell_amount) if to_decimal(sell_amount) is not None else None),
            "",
            _line(
                "순손익",
                f"{format_signed_krw(net)} ({format_signed_percent(pct)})"
                if to_decimal(net) is not None
                else None,
            ),
            _line("총 수수료", format_krw(total_fee) if to_decimal(total_fee) is not None else None),
            "",
            _line("청산사유", exit_reason),
            _line("보유시간", hold if hold != "-" else None),
            "",
            _line("매수", format_datetime_kst(buy_time) if buy_time else None),
            _line("매도", format_datetime_kst(sell_time) if sell_time else None),
            _line("Order", detail.get("order_id")),
        ]
    )
    return title, body.strip()


def format_order_reject(*, event_type: str, detail: dict[str, Any]) -> tuple[str, str]:
    prefix = title_prefix_for(event_type, detail=detail)
    title = f"{prefix} 🔶 자동매수 주문 거부"
    reason = reject_reason_user_label(
        detail.get("reason") or detail.get("reject_code") or detail.get("code")
    )
    slot_used = detail.get("auto_slot_used")
    slot_limit = detail.get("auto_slot_limit")
    slot_text = (
        f"{slot_used}/{slot_limit}"
        if slot_used is not None and slot_limit is not None
        else None
    )
    body = _join(
        [
            _line("종목", symbol_line(detail.get("symbol"), name=detail.get("symbol_name"))),
            _line("사유", reason),
            _line("AUTO 슬롯", slot_text),
            "",
            "주문은 생성되지 않았습니다.",
            _line("상세코드", detail.get("reason") or detail.get("reject_code")),
        ]
    )
    return title, body.strip()


def format_runtime_alert(*, event_type: str, detail: dict[str, Any]) -> tuple[str, str]:
    prefix = title_prefix_for(event_type, detail={**detail, "alert_kind": detail.get("runtime_kind") or "RUNTIME_START"})
    kind = str(detail.get("runtime_kind") or "").upper()
    if kind in {"STARTED", "RUNTIME_START", "START"}:
        title = f"{prefix} 🟢 자동매매 시작"
        body = _join(
            [
                _line("상태", detail.get("status_label") or "정상"),
                _line("실시간 시세", detail.get("feed_label") or detail.get("feed")),
                _line("자동매매", detail.get("ready_label") or detail.get("auto_trading_ready")),
                _line("시간", format_datetime_kst(detail.get("at")) if detail.get("at") else None),
            ]
        )
    elif kind in {"STOPPED_UNEXPECTED", "UNEXPECTED_STOP"}:
        title = f"{prefix} 🔴 자동매매 비정상 중지"
        body = "내용: Runtime이 예상하지 않게 중지되었습니다.\n자동주문 상태를 확인하세요."
    elif kind in {"RECOVERED", "RUNTIME_RECOVERED"}:
        title = f"{prefix} 🟢 자동매매 자동복구 완료"
        body = _line("시간", format_datetime_kst(detail.get("at")) if detail.get("at") else "복구가 완료되었습니다.") or "복구가 완료되었습니다."
    else:
        title = f"{prefix} ⚪ 자동매매 중지"
        body = "내용: 정상적으로 종료되었습니다."
    return title, body.strip()


def format_ai_decision_change(*, event_type: str, detail: dict[str, Any]) -> tuple[str, str]:
    market = str(detail.get("market") or detail.get("broker_code") or "UPBIT").upper()
    market_label = "UPBIT" if market != "KIWOOM" else "KIWOOM"
    title = f"[시스템] 🤖 {market_label} AI 매매 판단 변경"
    body = _join(
        [
            _line(
                "종목",
                symbol_line(detail.get("symbol"), name=detail.get("symbol_name")),
            ),
            _line(
                "이전 판단",
                detail.get("previous_recommendation_ko")
                or detail.get("previous_recommendation"),
            ),
            _line(
                "현재 판단",
                detail.get("new_recommendation_ko") or detail.get("new_recommendation"),
            ),
            _line("신뢰도", f"{detail.get('confidence_pct')}%" if detail.get("confidence_pct") is not None else None),
            _line("분석시각", format_datetime_kst(detail.get("analyzed_at")) if detail.get("analyzed_at") else None),
        ]
    )
    return title, body.strip()


def format_slot_alert(*, event_type: str, detail: dict[str, Any]) -> tuple[str, str]:
    title = "[시스템] 📌 자동매매 슬롯 등록"
    slot = detail.get("slot_no") or detail.get("auto_slot_used")
    limit = detail.get("auto_slot_limit") or detail.get("slot_limit")
    slot_text = f"{slot}/{limit}" if slot is not None and limit is not None else slot
    body = _join(
        [
            _line("시장", detail.get("market") or detail.get("broker_code") or "UPBIT"),
            _line("슬롯", slot_text),
            _line("종목", symbol_line(detail.get("symbol"), name=detail.get("symbol_name"))),
            _line("상태", detail.get("status_ko") or detail.get("status") or "매수 대기"),
        ]
    )
    return title, body.strip()


def format_shadow_checkpoint(*, event_type: str, detail: dict[str, Any]) -> tuple[str, str]:
    title = "[시스템] 🧪 Exit Shadow 중간 결과"
    body = _join(
        [
            _line("표본", detail.get("checkpoint") or detail.get("n_label")),
            _line("현재 1위", detail.get("top_variant") or detail.get("variant")),
            _line("PF", detail.get("profit_factor") or detail.get("pf")),
            _line("순손익", format_signed_krw(detail.get("net_pnl")) if detail.get("net_pnl") is not None else None),
            _line("MA 대비", format_signed_krw(detail.get("vs_ma")) if detail.get("vs_ma") is not None else None),
            "",
            "※ 실제 매도에는 적용되지 않습니다.",
        ]
    )
    return title, body.strip()


def format_system_operation(*, event_type: str, detail: dict[str, Any]) -> tuple[str, str]:
    sev = str(detail.get("severity") or "WARNING").upper()
    icon = {"CRITICAL": "🔴", "WARNING": "⚠️", "INFO": "ℹ️", "RECOVERED": "🟢"}.get(sev, "⚠️")
    label = detail.get("title_ko") or detail.get("alert_title") or event_type
    title = f"[시스템] {icon} {label}"
    body = _join(
        [
            _line("시장", detail.get("market") or detail.get("broker_code")),
            _line("유형", detail.get("alert_type") or detail.get("subtype")),
            _line("내용", detail.get("message_ko") or detail.get("summary")),
            _line("자동매매 중단 여부", detail.get("trading_halted_label")),
        ]
    )
    return title, (body or str(detail.get("summary") or "")).strip()


def maybe_format_user_message(
    *,
    event_type: str,
    title: str,
    message: str,
    detail: dict[str, Any] | None,
) -> tuple[str, str]:
    """V2 포맷 적용 가능하면 (title, message) 교체. 아니면 원본 유지."""

    d = dict(detail or {})
    et = str(event_type or "").upper()
    side = str(d.get("side") or d.get("side_code") or "").upper()
    # 이미 V2로 포맷된 경우
    if d.get("alert_v2_formatted"):
        return title, message

    try:
        if et in {"ORDER_FILLED", "ORDER_PARTIAL_FILLED"} and side == "BUY":
            return format_auto_buy_filled(
                event_type=et,
                detail=d,
                partial=et == "ORDER_PARTIAL_FILLED",
            )
        if et == "ORDER_FILLED" and side == "SELL":
            return format_auto_sell_filled(event_type=et, detail=d, partial=False)
        if et == "POSITION_CLOSED" or et in {
            "STOP_LOSS",
            "TAKE_PROFIT",
            "TRAILING_STOP",
            "MA_EXIT",
            "MA_DEAD_CROSS",
            "MA_DEAD_CROSS_EXIT",
        }:
            return format_auto_sell_filled(event_type=et, detail=d)
        if et == "ORDER_REJECTED":
            return format_order_reject(event_type=et, detail=d)
        if et == "AI_GATE_RECOMMENDATION_CHANGED":
            return format_ai_decision_change(event_type=et, detail=d)
        if et in {"UPBIT_PORTFOLIO_SLOT_ASSIGNED", "UPBIT_PORTFOLIO_CANDIDATE_REPLACED"}:
            return format_slot_alert(event_type=et, detail=d)
        if et in {
            "UPBIT_SCANNER_SHADOW_RESULT",
            "UPBIT_SHADOW_COHORT_30_REVIEW_READY",
        } and d.get("shadow_checkpoint"):
            return format_shadow_checkpoint(event_type=et, detail=d)
        if et == "UPBIT_AUTO_LONG_HOLD":
            from stock_platform.operation.upbit_long_hold_watch.service import (
                format_long_hold_alert,
            )

            return format_long_hold_alert(d)
        if d.get("runtime_kind"):
            return format_runtime_alert(event_type=et, detail=d)
    except Exception:  # noqa: BLE001 — fail-open keep original
        return title, message
    return title, message
