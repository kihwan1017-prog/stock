# -*- coding: utf-8 -*-
"""Long-hold watch — Alert V2 observability only (no SELL / Time Exit)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable

from sqlalchemy import text
from sqlalchemy.orm import Session

from stock_platform.notification.alert_v2.display import (
    format_holding_duration,
    format_signed_krw,
    format_signed_percent,
    symbol_line,
)
from stock_platform.notification.formatting import format_krw
from stock_platform.operation.upbit_long_hold_watch.checkpoints import (
    dedupe_key,
    long_hold_badge,
    select_latest_checkpoint,
)
from stock_platform.risk_engine.strategy_owned_entities import OWNERSHIP_STRATEGY

logger = logging.getLogger(__name__)

ZERO = Decimal("0")
EVENT_TYPE = "UPBIT_AUTO_LONG_HOLD"
OWNERSHIP_AUTO = OWNERSHIP_STRATEGY
EXCLUDED_OWNERSHIP = frozenset({"MANUAL", "UNKNOWN", "TEST", "SMOKE"})


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _dec(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:  # noqa: BLE001
        return None


def exit_state_user_label(code: str | None) -> str:
    """내부 상태 → 사용자 친화 라벨."""

    mapping = {
        "NO_EXIT_SIGNAL": "자동 청산 신호 대기 중",
        "BEARISH_WAITING_EDGE": "이동평균 약세 상태",
        "CONFIRMING": "청산신호 확인 중",
        "ORDER_PENDING": "매도주문 진행 중",
        "EXIT_PENDING": "매도주문 진행 중",
        "RECOVERY": "복구 확인 중",
        "CONDITION_NOT_MET": "청산조건 미충족",
        "STALE_PRICE": "데이터 확인 필요",
        "UNKNOWN": "데이터 확인 필요",
    }
    return mapping.get(str(code or "UNKNOWN").upper(), "데이터 확인 필요")


def format_long_hold_alert(detail: dict[str, Any]) -> tuple[str, str]:
    """사용자용 title/body — raw JSON 금지."""

    title = "[시스템] ⚠️ UPBIT AUTO 장기보유"
    symbol = detail.get("symbol")
    name = detail.get("symbol_name") or detail.get("name")
    hold = format_holding_duration(detail.get("holding_seconds"))
    entry = detail.get("entry_price")
    cur = detail.get("current_price")
    cur_stale = bool(detail.get("current_price_stale"))
    pnl = detail.get("estimated_pnl")
    pnl_rate = detail.get("estimated_pnl_rate_pct")
    exit_label = detail.get("exit_state_label") or exit_state_user_label(
        detail.get("exit_state")
    )
    slot_used = detail.get("auto_slot_used")
    slot_limit = detail.get("auto_slot_limit")

    price_line = (
        "현재가: 데이터 확인 필요"
        if cur is None or cur_stale
        else f"현재가: {format_krw(cur)}"
    )
    entry_line = (
        f"매수가: {format_krw(entry)}"
        if _dec(entry) is not None
        else "매수가: -"
    )
    pnl_line = None
    if pnl is not None:
        rate_txt = (
            f" ({format_signed_percent(pnl_rate)})"
            if pnl_rate is not None
            else ""
        )
        pnl_line = f"평가손익: {format_signed_krw(pnl)}{rate_txt}"

    slot_line = None
    if slot_used is not None and slot_limit is not None:
        slot_line = f"AUTO 슬롯: {slot_used} / {slot_limit}"

    lines = [
        f"종목: {symbol_line(symbol, name=name)}",
        f"보유시간: {hold}",
        "",
        entry_line,
        price_line,
        "",
    ]
    if pnl_line:
        lines.append(pnl_line)
        lines.append("")
    lines.append("현재 청산상태:")
    lines.append(exit_label)
    if slot_line:
        lines.append("")
        lines.append(slot_line)
    lines.append("")
    lines.append("※ 장기보유 경고이며 자동매도 알림이 아닙니다.")
    return title, "\n".join(lines)


def _quote(
    session: Session, symbol: str
) -> tuple[Decimal | None, bool]:
    row = session.execute(
        text(
            """
            SELECT q.trade_price, q.quoted_at
            FROM market.quote_snapshot q
            JOIN market.instrument i ON i.instrument_id = q.instrument_id
            WHERE i.symbol = :sym
            LIMIT 1
            """
        ),
        {"sym": str(symbol).upper()},
    ).mappings().first()
    if not row:
        return None, True
    price = _dec(row.get("trade_price"))
    quoted_at = row.get("quoted_at")
    stale = True
    if quoted_at is not None and price is not None:
        try:
            qa = quoted_at
            if getattr(qa, "tzinfo", None) is None:
                qa = qa.replace(tzinfo=timezone.utc)
            stale = (_now() - qa).total_seconds() > 900
        except Exception:  # noqa: BLE001
            stale = True
    return price, stale


def _auto_slot_counts(session: Session, uba_id: int) -> tuple[int | None, int | None]:
    try:
        from stock_platform.operation.upbit_full_market.auto_slot_count import (
            count_auto_slots_used,
        )

        used = int(count_auto_slots_used(session, user_broker_account_id=int(uba_id)))
    except Exception:  # noqa: BLE001
        used = None
    try:
        row = session.execute(
            text(
                """
                SELECT max_position_count
                FROM trading.user_broker_account_risk_setting
                WHERE user_broker_account_id = :uba
                LIMIT 1
                """
            ),
            {"uba": int(uba_id)},
        ).mappings().first()
        limit = int(row["max_position_count"]) if row and row.get("max_position_count") is not None else None
    except Exception:  # noqa: BLE001
        limit = None
    return used, limit


def _infer_exit_state(session: Session, uba_id: int, symbol: str) -> str:
    intent = session.execute(
        text(
            """
            SELECT status FROM operation.upbit_exit_intent
            WHERE user_broker_account_id = :uba AND UPPER(symbol) = :sym
              AND status IN (
                'CONFIRMED','ORDER_PENDING','COOLDOWN',
                'REVALIDATING','BLOCKED'
              )
            ORDER BY exit_intent_id DESC LIMIT 1
            """
        ),
        {"uba": int(uba_id), "sym": str(symbol).upper()},
    ).mappings().first()
    if intent:
        st = str(intent.get("status") or "").upper()
        if st == "ORDER_PENDING":
            return "ORDER_PENDING"
        if st in {"COOLDOWN", "REVALIDATING", "CONFIRMED", "BLOCKED"}:
            return "CONFIRMING"
    open_sell = session.execute(
        text(
            """
            SELECT COUNT(*) AS n FROM trading.trading_order
            WHERE user_broker_account_id = :uba AND UPPER(symbol) = :sym
              AND UPPER(side_code)='SELL'
              AND UPPER(status_code) IN (
                'CREATED','PENDING','SUBMITTING','SENT','ACCEPTED',
                'PARTIALLY_FILLED','CANCEL_REQUESTED'
              )
            """
        ),
        {"uba": int(uba_id), "sym": str(symbol).upper()},
    ).mappings().first()
    if int((open_sell or {}).get("n") or 0) > 0:
        return "EXIT_PENDING"
    return "BEARISH_WAITING_EDGE"


def evaluate_long_hold_positions(
    session: Session,
    *,
    user_broker_account_id: int,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """UPBIT REAL AUTO OPEN only — PAPER/MANUAL/UNKNOWN 제외."""

    now_ref = now or _now()
    rows = session.execute(
        text(
            """
            SELECT binding_id, user_broker_account_id, symbol, status,
                   ownership_code, entry_order_id, owned_quantity,
                   entry_price, opened_at
            FROM operation.strategy_position_binding
            WHERE user_broker_account_id = :uba
              AND UPPER(broker_code) = 'UPBIT'
              AND UPPER(status) = 'OPEN'
            ORDER BY binding_id
            """
        ),
        {"uba": int(user_broker_account_id)},
    ).mappings().all()

    slot_used, slot_limit = _auto_slot_counts(session, int(user_broker_account_id))
    out: list[dict[str, Any]] = []
    for row in rows:
        ownership = str(row.get("ownership_code") or "").upper()
        if ownership in EXCLUDED_OWNERSHIP or ownership != OWNERSHIP_AUTO:
            continue
        qty = _dec(row.get("owned_quantity")) or ZERO
        if qty <= ZERO:
            continue
        opened_at = row.get("opened_at")
        if opened_at is None:
            continue
        oa = opened_at
        if getattr(oa, "tzinfo", None) is None:
            oa = oa.replace(tzinfo=timezone.utc)
        hold_seconds = int((now_ref - oa).total_seconds())
        checkpoint = select_latest_checkpoint(hold_seconds)
        if checkpoint is None:
            continue
        symbol = str(row["symbol"]).upper()
        entry_price = _dec(row.get("entry_price"))
        quote, stale = _quote(session, symbol)
        pnl = None
        pnl_rate = None
        if quote is not None and entry_price is not None:
            pnl = float((quote - entry_price) * qty)
            cost = float(entry_price * qty)
            pnl_rate = (pnl / cost * 100.0) if cost else None
        exit_state = _infer_exit_state(session, int(user_broker_account_id), symbol)
        if stale:
            exit_state = "STALE_PRICE"
        badge = long_hold_badge(hold_seconds)
        position_id = int(row["binding_id"])
        detail = {
            "market": "UPBIT",
            "broker_code": "UPBIT",
            "telegram_market": "UPBIT",
            "user_broker_account_id": int(user_broker_account_id),
            "symbol": symbol,
            "position_id": position_id,
            "binding_id": position_id,
            "ownership": ownership,
            "holding_seconds": hold_seconds,
            "checkpoint": checkpoint,
            "entry_price": str(entry_price) if entry_price is not None else None,
            "current_price": None if quote is None or stale else str(quote),
            "current_price_stale": stale or quote is None,
            "quantity": str(qty),
            "estimated_pnl": pnl,
            "estimated_pnl_rate_pct": pnl_rate,
            "exit_state": exit_state,
            "exit_state_label": exit_state_user_label(exit_state),
            "auto_slot_used": slot_used,
            "auto_slot_limit": slot_limit,
            "badge": badge,
            "dedupe_key": dedupe_key(
                position_id=position_id, checkpoint=checkpoint
            ),
            "alert_kind": "LONG_HOLD",
            "observability_only": True,
            "auto_sell": False,
            "max_holding_time_real": None,
        }
        title, body = format_long_hold_alert(detail)
        detail["title_ko"] = title
        detail["message_ko"] = body
        out.append(detail)
    return out


def build_long_hold_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Daily report용 — 이미 평가된 목록 재사용 (N+1 금지)."""

    rows = []
    for it in items:
        rows.append(
            {
                "symbol": it.get("symbol"),
                "holding_seconds": it.get("holding_seconds"),
                "holding_label": format_holding_duration(it.get("holding_seconds")),
                "estimated_pnl_rate_pct": it.get("estimated_pnl_rate_pct"),
                "checkpoint": it.get("checkpoint"),
            }
        )
    return {
        "count": len(rows),
        "positions": rows,
        "note": "장기보유 감시(자동매도 아님)",
    }


def emit_long_hold_alert(detail: dict[str, Any]) -> dict[str, Any]:
    """Alert V2 경로 — fail-open, SELL 없음."""

    try:
        from stock_platform.order.live_safety_audit import emit_live_order_telegram

        title, body = format_long_hold_alert(detail)
        emit_live_order_telegram(
            event_type=EVENT_TYPE,
            title=title,
            message=body,
            detail=detail,
        )
        return {"emitted": True, "dedupe_key": detail.get("dedupe_key")}
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "long_hold_alert_emit_failed",
            extra={"error": f"{type(exc).__name__}:{exc}"[:200]},
        )
        return {"emitted": False, "error": type(exc).__name__}


def run_long_hold_watch_once(
    session: Session,
    *,
    user_broker_account_id: int,
    emit: bool = True,
    emit_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """한 사이클 — checkpoint당 1회 (inbox dedupe)."""

    items = evaluate_long_hold_positions(
        session,
        user_broker_account_id=int(user_broker_account_id),
        now=now,
    )
    results = []
    emitter = emit_fn or emit_long_hold_alert
    for detail in items:
        if not emit:
            results.append({"symbol": detail["symbol"], "skipped_emit": True, **detail})
            continue
        er = emitter(detail)
        results.append(
            {
                "symbol": detail["symbol"],
                "checkpoint": detail["checkpoint"],
                "dedupe_key": detail["dedupe_key"],
                **er,
            }
        )
    return {
        "user_broker_account_id": int(user_broker_account_id),
        "long_hold_count": len(items),
        "summary": build_long_hold_summary(items),
        "results": results,
        "sell_created": 0,
        "time_exit_real": False,
        "max_holding_time": None,
    }
