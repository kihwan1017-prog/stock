"""이벤트 detail → 템플릿 변수 정규화 (구조화 이벤트, LLM 없음).

nested candidate/order/slot 등을 canonical field로 평탄화한다.
값이 없으면 '-'를 미리 넣지 않고 None을 두어 optional line 억제를 가능하게 한다.
"""

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
    "PORTFOLIO_BULLISH_STATE_ENTRY": "TRADE",
    "KILL_SWITCH": "CRITICAL",
    "DAILY_LOSS": "RISK",
    "AI_ANALYSIS_COMPLETE": "AI",
    "AI_GATE_RECOMMENDATION_CHANGED": "AI",
    "AI_TIMEOUT": "AI",
    "UPBIT_SCANNER_CANDIDATE": "PORTFOLIO",
    "UPBIT_SCANNER_SHADOW_OPENED": "PORTFOLIO",
    "UPBIT_SCANNER_SHADOW_RESULT": "PORTFOLIO",
    "UPBIT_PORTFOLIO_SLOT_ASSIGNED": "PORTFOLIO",
    "UPBIT_PORTFOLIO_CANDIDATE_REPLACED": "PORTFOLIO",
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
    "GENERIC": "INFO",
}

# event별 필수 표시 필드(없으면 fallback + diagnostic)
REQUIRED_FIELDS: dict[str, frozenset[str]] = {
    "UPBIT_SCANNER_CANDIDATE": frozenset({"symbol_display"}),
    "UPBIT_PORTFOLIO_SLOT_ASSIGNED": frozenset({"symbol_display"}),
    "UPBIT_PORTFOLIO_CANDIDATE_REPLACED": frozenset(
        {"old_symbol_display", "new_symbol_display"}
    ),
    "UPBIT_SCANNER_SHADOW_OPENED": frozenset({"symbol_display"}),
    "ACCOUNT_DAILY_DRAWDOWN": frozenset({"account_display"}),
    "ORDER_SUBMITTED": frozenset({"symbol_display"}),
    "ORDER_FILLED": frozenset({"symbol_display"}),
    "ORDER_PARTIAL_FILLED": frozenset({"symbol_display"}),
    "ORDER_CANCELLED": frozenset({"symbol_display"}),
    "ORDER_REJECTED": frozenset({"symbol_display"}),
    "TAKE_PROFIT": frozenset({"symbol_display"}),
    "STOP_LOSS": frozenset({"symbol_display"}),
    "TRAILING_STOP": frozenset({"symbol_display"}),
    "PORTFOLIO_BULLISH_STATE_ENTRY": frozenset({"symbol_display"}),
    "AI_GATE_RECOMMENDATION_CHANGED": frozenset({"symbol_display"}),
    "KILL_SWITCH": frozenset({"account_display"}),
}


def event_category(event_type: str) -> str:
    return EVENT_CATEGORY.get(str(event_type or "").upper(), "INFO")


def required_fields_for(event_type: str) -> frozenset[str]:
    return REQUIRED_FIELDS.get(str(event_type or "").upper(), frozenset())


def _first(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def flatten_event_detail(detail: dict[str, Any] | None) -> dict[str, Any]:
    """nested candidate/order/slot/ai → top-level canonical keys (setdefault)."""

    raw = dict(detail or {})
    flat = dict(raw)

    for nest_key in (
        "candidate",
        "selection",
        "slot",
        "order",
        "signal",
        "position",
        "ai",
        "analysis",
        "payload",
        "shadow",
    ):
        blob = raw.get(nest_key)
        if isinstance(blob, dict):
            for key, value in blob.items():
                flat.setdefault(key, value)

    candidates = raw.get("candidates")
    if isinstance(candidates, list) and candidates:
        first = candidates[0]
        if isinstance(first, dict):
            for key, value in first.items():
                flat.setdefault(key, value)

    # 별칭 정규화
    if flat.get("symbol") is None:
        flat["symbol"] = _first(
            flat.get("market"),
            flat.get("symbol_code"),
            flat.get("ticker"),
        )
    if flat.get("score") is None:
        flat["score"] = _first(
            flat.get("scanner_score"),
            flat.get("opportunity_score"),
        )
    if flat.get("scanner_score") is None and flat.get("score") is not None:
        flat["scanner_score"] = flat.get("score")
    if flat.get("ai_recommendation") is None:
        flat["ai_recommendation"] = _first(
            flat.get("recommendation"),
            flat.get("new_recommendation"),
            flat.get("gate_recommendation"),
        )
    if flat.get("confidence") is None:
        flat["confidence"] = _first(
            flat.get("ai_confidence"),
            flat.get("confidence_pct"),
        )
    if flat.get("rank") is None:
        flat["rank"] = _first(flat.get("candidate_rank"), flat.get("slot_no"))
    if flat.get("slot_no") is None:
        flat["slot_no"] = _first(flat.get("slot"), flat.get("position_slot"))
    return flat


def _candidates_summary(detail: dict[str, Any]) -> str | None:
    rows = detail.get("candidates")
    if not isinstance(rows, list) or not rows:
        return None
    lines: list[str] = []
    for item in rows[:5]:
        if not isinstance(item, dict):
            continue
        sym = format_symbol(item.get("symbol") or item.get("market"))
        rank = item.get("rank")
        score = item.get("score") or item.get("scanner_score")
        rec = recommendation_ko(
            item.get("recommendation") or item.get("ai_recommendation") or ""
        )
        score_txt = (
            format_number(score, digits=2) if score is not None else None
        )
        parts = []
        if rank is not None:
            parts.append(f"#{rank}")
        if sym and sym != "-":
            parts.append(sym)
        if score_txt and score_txt != "-":
            parts.append(score_txt)
        if rec and rec != "-":
            parts.append(rec)
        if parts:
            lines.append(" · ".join(parts))
    if not lines:
        return None
    return "후보 목록:\n" + "\n".join(lines)


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
    flat = flatten_event_detail(safe)

    broker = _first(
        flat.get("broker_code"),
        flat.get("broker"),
        flat.get("exchange_code"),
    )
    side = _first(
        flat.get("side"),
        flat.get("side_code"),
        flat.get("signal_action"),
        flat.get("action"),
    )
    symbol = _first(
        flat.get("symbol"),
        flat.get("new_symbol"),
        flat.get("market"),
        flat.get("ticker"),
    )
    old_symbol = _first(flat.get("old_symbol"), flat.get("previous_symbol"))
    new_symbol = _first(flat.get("new_symbol"), flat.get("symbol"))
    status = _first(flat.get("status"), flat.get("order_status"), flat.get("status_code"))
    order_type = _first(
        flat.get("order_type"),
        flat.get("order_type_code"),
        flat.get("type"),
    )
    prev = _first(
        flat.get("previous_recommendation"),
        flat.get("prev_recommendation"),
        flat.get("from"),
    )
    new = _first(
        flat.get("new_recommendation"),
        flat.get("ai_recommendation"),
        flat.get("recommendation"),
        flat.get("to"),
    )
    amount = _first(
        flat.get("amount_krw"),
        flat.get("filled_amount"),
        flat.get("notional"),
        flat.get("order_amount"),
        flat.get("approved_amount_krw"),
        flat.get("recommended_amount_krw"),
        flat.get("assumed_amount_krw"),
    )
    price = _first(
        flat.get("avg_price"),
        flat.get("fill_price"),
        flat.get("price"),
        flat.get("signal_price"),
        flat.get("order_price"),
        flat.get("entry_price"),
    )
    qty = _first(
        flat.get("filled_qty"),
        flat.get("quantity"),
        flat.get("qty"),
        flat.get("executed_qty"),
        flat.get("order_quantity"),
    )
    confidence = _first(flat.get("confidence"), flat.get("ai_confidence"))
    reason = _first(
        flat.get("reason_ko"),
        flat.get("reason"),
        flat.get("reason_code"),
        flat.get("block_reason"),
        flat.get("error"),
    )
    strategy = _first(
        flat.get("strategy_name"),
        flat.get("strategy_code"),
        flat.get("strategy"),
    )
    account = _first(
        flat.get("account_display"),
        flat.get("uba_label"),
        (
            f"{broker_ko(broker)} {flat.get('masked_account_ref')}"
            if broker and flat.get("masked_account_ref")
            else None
        ),
        (
            f"UBA{flat['user_broker_account_id']}"
            if flat.get("user_broker_account_id") is not None
            else None
        ),
        flat.get("masked_account_ref"),
        broker_ko(broker) if broker else None,
    )
    position_status = _first(flat.get("position_status"), flat.get("slot_status"))
    created = _first(
        flat.get("created_at"),
        flat.get("sent_at"),
        flat.get("generated_at"),
        flat.get("filled_at"),
        flat.get("selected_at"),
        flat.get("analyzed_at"),
    )
    score = _first(flat.get("scanner_score"), flat.get("score"))
    rank = _first(flat.get("rank"), flat.get("scanner_rank"))
    slot_no = _first(flat.get("slot_no"), flat.get("slot"))
    ai_rec = _first(flat.get("ai_recommendation"), new)
    candidates_summary = _candidates_summary(safe)

    symbol_display = (
        format_symbol(symbol, name=flat.get("symbol_name") or flat.get("name"))
        if symbol
        else None
    )
    if symbol_display == "-":
        symbol_display = None
    old_symbol_display = (
        format_symbol(old_symbol) if old_symbol else None
    )
    if old_symbol_display == "-":
        old_symbol_display = None
    # 명시 필드도 심볼 포맷 적용 (KRW-TREE → TREE)
    if flat.get("old_symbol_display"):
        old_symbol_display = format_symbol(flat.get("old_symbol_display"))
        if old_symbol_display == "-":
            old_symbol_display = None
    new_symbol_display = (
        format_symbol(new_symbol) if new_symbol else symbol_display
    )
    if new_symbol_display == "-":
        new_symbol_display = None
    if flat.get("new_symbol_display"):
        new_symbol_display = format_symbol(flat.get("new_symbol_display"))
        if new_symbol_display == "-":
            new_symbol_display = None
    if flat.get("symbol_display") and not symbol_display:
        symbol_display = format_symbol(flat.get("symbol_display"))
        if symbol_display == "-":
            symbol_display = None
    # 교체 이벤트: symbol_display = 신규 종목
    et_upper = str(event_type or "").upper()
    if et_upper == "UPBIT_PORTFOLIO_CANDIDATE_REPLACED" and new_symbol_display:
        symbol_display = new_symbol_display

    ai_ko = recommendation_ko(ai_rec) if ai_rec else None
    if ai_ko == "-":
        ai_ko = None

    old_score = _first(flat.get("old_score"), flat.get("old_scanner_score"))
    new_score = _first(
        flat.get("new_score"), flat.get("scanner_score"), flat.get("score")
    )

    vars_: dict[str, Any] = {
        "event_type": str(event_type or "").upper(),
        "title": title or None,
        "message": message or None,
        "broker": str(broker).upper() if broker else None,
        "broker_ko": broker_ko(broker) if broker else None,
        "side": str(side).upper() if side else None,
        "side_ko": side_ko(side) if side else None,
        "symbol": str(symbol).upper() if symbol else None,
        "symbol_display": symbol_display,
        "old_symbol_display": old_symbol_display,
        "new_symbol_display": new_symbol_display,
        "old_scanner_score": (
            format_number(old_score, digits=2) if old_score is not None else None
        ),
        "new_scanner_score": (
            format_number(new_score, digits=2) if new_score is not None else None
        ),
        "order_type_ko": (
            translate(order_type, group="order_type") if order_type else None
        ),
        "status": str(status).upper() if status else None,
        "status_ko": translate(status, group="order_status") if status else None,
        "position_status_ko": (
            translate(position_status, group="slot_status")
            if position_status
            else None
        ),
        "price_display": format_krw(price) if price is not None else None,
        "avg_price": format_krw(price) if price is not None else None,
        "amount_krw": format_krw(amount) if amount is not None else None,
        "quantity": format_quantity(qty) if qty is not None else None,
        "filled_qty": format_quantity(qty) if qty is not None else None,
        "reason": str(reason) if reason else None,
        "reason_ko": str(reason) if reason else None,
        "strategy_name": str(strategy) if strategy else None,
        "account_display": str(account) if account else None,
        "previous_recommendation_ko": (
            recommendation_ko(prev) if prev else None
        ),
        "new_recommendation_ko": recommendation_ko(new) if new else None,
        "confidence_pct": (
            format_percent(confidence) if confidence is not None else None
        ),
        "rank": format_number(rank) if rank is not None else None,
        "score": format_number(score, digits=2) if score is not None else None,
        "scanner_score": (
            format_number(score, digits=2) if score is not None else None
        ),
        "ai_recommendation": ai_ko,
        "ai_recommendation_ko": ai_ko,
        "slot_no": str(slot_no) if slot_no is not None else None,
        "candidates_summary": candidates_summary,
        "current_value": (
            str(flat.get("current_value") or flat.get("current"))
            if (flat.get("current_value") or flat.get("current")) is not None
            else None
        ),
        "limit_value": (
            str(flat.get("limit_value") or flat.get("limit"))
            if (flat.get("limit_value") or flat.get("limit")) is not None
            else None
        ),
        "current_loss_display": (
            format_krw(flat.get("current_loss_amount"))
            if flat.get("current_loss_amount") is not None
            else None
        ),
        "loss_limit_display": (
            format_krw(flat.get("loss_limit_amount"))
            if flat.get("loss_limit_amount") is not None
            else None
        ),
        "created_at_kst": format_datetime_kst(created)
        if created is not None
        else None,
        "expires_at_kst": format_datetime_kst(
            flat.get("expires_at") or flat.get("arm_expires_at")
        )
        if (flat.get("expires_at") or flat.get("arm_expires_at"))
        else None,
        "uba_id": (
            str(flat.get("user_broker_account_id") or flat.get("uba_id"))
            if (flat.get("user_broker_account_id") or flat.get("uba_id"))
            is not None
            else None
        ),
        "order_id": str(flat.get("order_id"))
        if flat.get("order_id") is not None
        else None,
        "strategy_id": str(flat.get("strategy_id"))
        if flat.get("strategy_id") is not None
        else None,
        "runtime_status_ko": translate(
            flat.get("runtime_status") or flat.get("status"),
            group="runtime",
        )
        if (flat.get("runtime_status") or flat.get("status"))
        else None,
        "approved_amount_krw": (
            format_krw(flat.get("approved_amount_krw"))
            if flat.get("approved_amount_krw") is not None
            else None
        ),
        "rsi14": format_number(flat.get("rsi14"), digits=2)
        if flat.get("rsi14") is not None
        else None,
    }
    return vars_
