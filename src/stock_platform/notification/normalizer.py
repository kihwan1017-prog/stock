"""이벤트 detail → 템플릿 변수 정규화 (구조화 이벤트, LLM 없음)."""

from __future__ import annotations

from typing import Any

from stock_platform.notification.code_dictionary import (
    broker_ko,
    recommendation_ko,
    side_ko,
    translate,
)
from stock_platform.notification.formatting import (
    format_datetime_kst,
    format_krw,
    format_number,
    format_percent,
    format_quantity,
    format_symbol,
)
from stock_platform.notification.masking import mask_sensitive


EVENT_CATEGORY: dict[str, str] = {
    "SYSTEM_START": "SYSTEM",
    "SYSTEM_STOP": "SYSTEM",
    "SYSTEM_RESTART": "SYSTEM",
    "ORDER_SUBMITTED": "TRADE",
    "ORDER_FILLED": "TRADE",
    "ORDER_PARTIAL_FILLED": "TRADE",
    "ORDER_CANCELLED": "TRADE",
    "ORDER_REJECTED": "TRADE",
    "STOP_LOSS": "TRADE",
    "TAKE_PROFIT": "TRADE",
    "TRAILING_STOP": "TRADE",
    "RELATIVE_LOSS": "TRADE",
    "KILL_SWITCH": "CRITICAL",
    "DAILY_LOSS": "RISK",
    "AI_ANALYSIS_COMPLETE": "AI",
    "AI_GATE_RECOMMENDATION_CHANGED": "AI",
    "AI_TIMEOUT": "AI",
    "UPBIT_SCANNER_CANDIDATE": "PORTFOLIO",
    "UPBIT_SCANNER_SHADOW_OPENED": "PORTFOLIO",
    "UPBIT_SCANNER_SHADOW_RESULT": "PORTFOLIO",
    "UPBIT_SCANNER_FAILURE": "WARNING",
    "UPBIT_SHADOW_EVALUATION_MISMATCH": "WARNING",
    "UPBIT_SHADOW_COHORT_30_REVIEW_READY": "PORTFOLIO",
    "BACKTEST_COMPLETE": "INFO",
    "BROKER_DISCONNECTED": "CRITICAL",
    "BROKER_RECONNECTED": "SYSTEM",
    "BROKER_CONNECTED": "SYSTEM",
    "BROKER_TIMEOUT": "CRITICAL",
    "DATABASE_ERROR": "CRITICAL",
    "SCHEDULER_STARTED": "SYSTEM",
    "SCHEDULER_PAUSED": "WARNING",
    "SCHEDULER_ERROR": "CRITICAL",
    "RUNTIME_STARTED": "SYSTEM",
    "RUNTIME_PAUSED": "WARNING",
    "RECOVERY_STARTED": "RECOVERY",
    "RECOVERY_FAILED": "CRITICAL",
    "RECOVERY_CONFLICT": "RECOVERY",
    "RECONCILIATION_MISMATCH": "CRITICAL",
    "SUBMISSION_UNKNOWN": "CRITICAL",
    "TELEGRAM_FAILURE": "WARNING",
    "MONITORING_ALERT": "WARNING",
    "TEST_NOTIFICATION": "DEBUG",
}


def event_category(event_type: str) -> str:
    return EVENT_CATEGORY.get(str(event_type or "").upper(), "INFO")


def normalize_variables(
    *,
    event_type: str,
    title: str,
    message: str,
    detail: dict[str, Any] | None,
) -> dict[str, Any]:
    """템플릿 변수 dict. 원본 detail은 별도 보존."""

    raw = dict(detail or {})
    safe = mask_sensitive(raw)
    broker = (
        safe.get("broker_code")
        or safe.get("broker")
        or safe.get("exchange_code")
        or ""
    )
    side = safe.get("side") or safe.get("signal_action") or safe.get("action") or ""
    symbol = safe.get("symbol") or safe.get("market") or ""
    status = safe.get("status") or safe.get("order_status") or ""
    prev = (
        safe.get("previous_recommendation")
        or safe.get("prev_recommendation")
        or safe.get("from")
        or ""
    )
    new = (
        safe.get("new_recommendation")
        or safe.get("recommendation")
        or safe.get("to")
        or ""
    )
    amount = (
        safe.get("amount_krw")
        or safe.get("filled_amount")
        or safe.get("notional")
        or safe.get("order_amount")
    )
    price = (
        safe.get("avg_price")
        or safe.get("fill_price")
        or safe.get("price")
        or safe.get("signal_price")
    )
    qty = (
        safe.get("filled_qty")
        or safe.get("quantity")
        or safe.get("qty")
        or safe.get("executed_qty")
    )
    confidence = safe.get("confidence") or safe.get("confidence_pct")
    reason = (
        safe.get("reason_ko")
        or safe.get("reason")
        or safe.get("reason_code")
        or safe.get("block_reason")
        or ""
    )
    strategy = (
        safe.get("strategy_name")
        or safe.get("strategy_code")
        or safe.get("strategy")
        or ""
    )
    account = (
        safe.get("account_display")
        or safe.get("uba_label")
        or (
            f"UBA{safe['user_broker_account_id']}"
            if safe.get("user_broker_account_id")
            else ""
        )
        or broker_ko(broker)
    )
    position_status = (
        safe.get("position_status")
        or safe.get("slot_status")
        or ""
    )
    created = (
        safe.get("created_at")
        or safe.get("sent_at")
        or safe.get("generated_at")
        or safe.get("filled_at")
    )

    vars_: dict[str, Any] = {
        "event_type": str(event_type or "").upper(),
        "title": title or "",
        "message": message or "",
        "broker": str(broker).upper() if broker else "-",
        "broker_ko": broker_ko(broker) if broker else "-",
        "side": str(side).upper() if side else "-",
        "side_ko": side_ko(side) if side else "-",
        "symbol": str(symbol).upper() if symbol else "-",
        "symbol_display": format_symbol(
            symbol, name=safe.get("symbol_name") or safe.get("name")
        ),
        "status": str(status).upper() if status else "-",
        "status_ko": translate(status, group="order_status") if status else "-",
        "position_status_ko": translate(position_status, group="slot_status")
        if position_status
        else translate("OPEN", group="slot_status"),
        "price_display": format_krw(price) if price is not None else "-",
        "avg_price": format_krw(price) if price is not None else "-",
        "amount_krw": format_krw(amount) if amount is not None else "-",
        "quantity": format_quantity(qty) if qty is not None else "-",
        "filled_qty": format_quantity(qty) if qty is not None else "-",
        "reason": str(reason) if reason else "-",
        "reason_ko": str(reason) if reason else "-",
        "strategy_name": str(strategy) if strategy else "-",
        "account_display": str(account) if account else "-",
        "previous_recommendation_ko": recommendation_ko(prev) if prev else "-",
        "new_recommendation_ko": recommendation_ko(new) if new else "-",
        "confidence_pct": format_percent(confidence)
        if confidence is not None
        else "-",
        "rank": format_number(safe.get("rank")) if safe.get("rank") is not None else "-",
        "score": format_number(safe.get("score"))
        if safe.get("score") is not None
        else "-",
        "ai_recommendation_ko": recommendation_ko(
            safe.get("ai_recommendation") or new or ""
        ),
        "current_value": str(safe.get("current_value") or safe.get("current") or "-"),
        "limit_value": str(safe.get("limit_value") or safe.get("limit") or "-"),
        "created_at_kst": format_datetime_kst(created),
        "expires_at_kst": format_datetime_kst(
            safe.get("expires_at") or safe.get("arm_expires_at")
        ),
        "uba_id": str(safe.get("user_broker_account_id") or safe.get("uba_id") or "-"),
        "order_id": str(safe.get("order_id") or "-"),
        "strategy_id": str(safe.get("strategy_id") or "-"),
        "runtime_status_ko": translate(
            safe.get("runtime_status") or safe.get("status"),
            group="runtime",
        ),
    }
    return vars_
