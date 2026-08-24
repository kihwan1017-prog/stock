"""Kiwoom AUTO SELL ↔ BUY/position provenance 분류.

과거 데이터 추정 조작 금지. 신규 fill부터 binding 연결을 보장하기 위한
진단·분류 헬퍼만 제공한다.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session


# 분류 코드 (FINAL REPORT / audit)
MISSING_LOCAL_BUY_HISTORY = "MISSING_LOCAL_BUY_HISTORY"
BROKER_IMPORTED_POSITION = "BROKER_IMPORTED_POSITION"
POSITION_PROVENANCE_GAP = "POSITION_PROVENANCE_GAP"
EXECUTION_LINK_GAP = "EXECUTION_LINK_GAP"
OTHER = "OTHER"
LINKED_OK = "LINKED_OK"


def classify_sell_entry_provenance(
    session: Session,
    *,
    sell_order_id: int,
) -> dict[str, Any]:
    """SELL 주문에 대한 entry provenance gap 분류 (READ-ONLY)."""

    from stock_platform.order.entities import TradingOrderEntity
    from stock_platform.risk_engine.strategy_owned_entities import (
        StrategyPositionBindingEntity,
    )

    order = session.get(TradingOrderEntity, int(sell_order_id))
    if order is None:
        return {
            "order_id": int(sell_order_id),
            "classification": OTHER,
            "reason": "ORDER_NOT_FOUND",
        }

    side = str(getattr(order, "side_code", "") or "").upper()
    if side not in {"SELL", "ASK"}:
        return {
            "order_id": int(sell_order_id),
            "classification": OTHER,
            "reason": "NOT_SELL",
            "side": side,
        }

    uba_id = getattr(order, "user_broker_account_id", None)
    symbol = str(getattr(order, "symbol", "") or "").upper()
    strategy_id = getattr(order, "strategy_id", None)

    # 동일 심볼 로컬 FILLED BUY 존재 여부
    buy_rows: list[Any] = []
    if uba_id is not None and symbol:
        buy_q = (
            select(TradingOrderEntity)
            .where(
                TradingOrderEntity.user_broker_account_id == int(uba_id),
                TradingOrderEntity.symbol == symbol,
                TradingOrderEntity.side_code.in_(("BUY", "BID")),
                TradingOrderEntity.status_code == "FILLED",
            )
            .order_by(TradingOrderEntity.order_id.desc())
            .limit(5)
        )
        if strategy_id is not None:
            buy_q = buy_q.where(
                TradingOrderEntity.strategy_id == int(strategy_id)
            )
        buy_rows = list(session.scalars(buy_q).all())

    bindings: list[Any] = []
    if uba_id is not None and symbol and strategy_id is not None:
        bindings = list(
            session.scalars(
                select(StrategyPositionBindingEntity)
                .where(
                    StrategyPositionBindingEntity.user_broker_account_id
                    == int(uba_id),
                    StrategyPositionBindingEntity.symbol == symbol,
                    StrategyPositionBindingEntity.strategy_id
                    == int(strategy_id),
                )
                .order_by(
                    StrategyPositionBindingEntity.binding_id.desc()
                )
                .limit(10)
            ).all()
        )

    open_with_entry = [
        b
        for b in bindings
        if str(getattr(b, "status", "") or "").upper() == "OPEN"
        and getattr(b, "entry_order_id", None) is not None
    ]
    any_with_entry = [
        b
        for b in bindings
        if getattr(b, "entry_order_id", None) is not None
    ]

    classification = OTHER
    reasons: list[str] = []

    if open_with_entry or (
        any_with_entry
        and any(
            int(getattr(b, "entry_order_id", 0) or 0) > 0
            for b in any_with_entry
        )
        and buy_rows
    ):
        classification = LINKED_OK
        reasons.append("BINDING_HAS_ENTRY_ORDER")
    elif not buy_rows and not bindings:
        classification = MISSING_LOCAL_BUY_HISTORY
        reasons.append("NO_LOCAL_FILLED_BUY")
        reasons.append("NO_STRATEGY_BINDING")
        # 브로커 잔고만 있는 외부/이전 포지션일 가능성
        classification = BROKER_IMPORTED_POSITION
        reasons.append("LIKELY_EXTERNAL_OR_IMPORTED_POSITION")
    elif not buy_rows and bindings:
        classification = POSITION_PROVENANCE_GAP
        reasons.append("NO_LOCAL_FILLED_BUY")
        reasons.append("BINDING_WITHOUT_USABLE_ENTRY")
    elif buy_rows and not any_with_entry:
        classification = EXECUTION_LINK_GAP
        reasons.append("LOCAL_BUY_EXISTS_BUT_NO_BINDING_ENTRY")
    else:
        classification = POSITION_PROVENANCE_GAP
        reasons.append("UNRESOLVED_ENTRY_LINK")

    return {
        "order_id": int(sell_order_id),
        "user_broker_account_id": (
            int(uba_id) if uba_id is not None else None
        ),
        "symbol": symbol or None,
        "strategy_id": (
            int(strategy_id) if strategy_id is not None else None
        ),
        "classification": classification,
        "reasons": reasons,
        "local_filled_buy_order_ids": [
            int(r.order_id) for r in buy_rows
        ],
        "binding_ids": [
            int(b.binding_id) for b in bindings if hasattr(b, "binding_id")
        ],
        "binding_entry_order_ids": [
            int(b.entry_order_id)
            for b in bindings
            if getattr(b, "entry_order_id", None) is not None
        ],
        # 과거 데이터 조작 금지 — 진단만
        "historical_mutation_allowed": False,
    }
