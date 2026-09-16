"""OES persist 직전 EXIT/최소노셔널 게이트.

skip_risk_checks=True 여도 적용한다. TradingOrder/Outbox 생성 전에 차단.
"""

from __future__ import annotations

import logging
import time
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from stock_platform.broker.upbit.rules import (
    REASON_UPBIT_MIN_NOTIONAL_NOT_MET,
    UPBIT_MIN_NOTIONAL_KRW,
    compute_upbit_notional,
    describe_upbit_exit_notional,
    evaluate_upbit_min_notional,
)
from stock_platform.risk_engine.exit_risk import classify_risk_reducing_exit


logger = logging.getLogger(__name__)

# tick 폭주 방지 — (uba, symbol, reason) 당 최소 간격
_LOG_INTERVAL_SEC = 60.0
_LAST_BLOCK_LOG: dict[tuple[Any, ...], float] = {}


def _log_dust_block(
    *,
    user_broker_account_id: int | None,
    broker_code: str,
    symbol: str,
    side: str,
    quantity: Decimal,
    notional: Decimal | None,
    reason_code: str,
) -> None:
    key = (
        int(user_broker_account_id or 0),
        str(broker_code or "").upper(),
        str(symbol or "").upper(),
        str(reason_code),
    )
    now = time.monotonic()
    last = _LAST_BLOCK_LOG.get(key, 0.0)
    if now - last < _LOG_INTERVAL_SEC:
        return
    _LAST_BLOCK_LOG[key] = now
    logger.warning(
        "pre_persist_exit_block uba=%s broker=%s symbol=%s side=%s "
        "qty=%s notional=%s min_notional=%s reason=%s",
        user_broker_account_id,
        broker_code,
        symbol,
        side,
        quantity,
        notional,
        UPBIT_MIN_NOTIONAL_KRW,
        reason_code,
    )


def evaluate_pre_persist_exit_gate(
    session: Session,
    *,
    side: str,
    symbol: str,
    exchange_code: str,
    quantity: Decimal,
    price: Decimal | None,
    order_type: str,
    broker_code: str,
    environment: str,
    user_broker_account_id: int | None,
    paper_account_id: int | None,
    market_krw_amount: Decimal | None = None,
) -> str | None:
    """lock 내부에서 persist 전에 호출. 차단 reason 또는 None.

    순서: outstanding SELL / EXIT 분류 → UPBIT 최소 노셔널.
    """

    side_u = str(side or "").strip().upper()
    if side_u == "SELL":
        exit_clf = classify_risk_reducing_exit(
            session,
            side=side_u,
            symbol=symbol,
            exchange_code=exchange_code,
            quantity=quantity,
            user_broker_account_id=user_broker_account_id,
            paper_account_id=paper_account_id,
            environment=environment,
            broker_code=broker_code,
        )
        if not exit_clf.is_risk_reducing_exit:
            reason = exit_clf.reason_code or "NO_POSITION_TO_SELL"
            _log_dust_block(
                user_broker_account_id=user_broker_account_id,
                broker_code=broker_code,
                symbol=symbol,
                side=side_u,
                quantity=quantity,
                notional=None,
                reason_code=reason,
            )
            return reason

    min_reason = evaluate_upbit_min_notional(
        broker_code=broker_code,
        environment=environment,
        side=side_u,
        order_type=order_type,
        quantity=quantity,
        price=price,
        market_krw_amount=market_krw_amount,
    )
    if min_reason:
        notional = compute_upbit_notional(
            side=side_u,
            order_type=order_type,
            quantity=quantity,
            price=price,
            market_krw_amount=market_krw_amount,
        )
        _log_dust_block(
            user_broker_account_id=user_broker_account_id,
            broker_code=broker_code,
            symbol=symbol,
            side=side_u,
            quantity=quantity,
            notional=notional,
            reason_code=min_reason,
        )
        # 관측 필드는 로그에만. 주문가 자동 변경 없음.
        _ = describe_upbit_exit_notional(
            held_quantity=quantity,
            current_price=price,
        )
        return REASON_UPBIT_MIN_NOTIONAL_NOT_MET
    return None
