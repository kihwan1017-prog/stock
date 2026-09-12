"""REAL 주문 계좌는 REAL 시세 소스만 허용. MOCK/REST fallback 금지."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from stock_platform.broker.kiwoom.execution_env import (
    kiwoom_uba_has_explicit_real_execution,
)
from stock_platform.broker.kiwoom.market_realtime_contract import (
    REASON_REAL_EXECUTION_REQUIRES_REAL_MARKET_DATA,
    REASON_REST_POLLING_NOT_LIVE_SOT,
    REASON_UNKNOWN_MARKET_SOURCE,
    SOURCE_REST_POLLING,
    SOURCE_WEBSOCKET_MOCK,
    SOURCE_WEBSOCKET_REAL,
)


def is_mock_market_source(source_code: str | None) -> bool:
    source = str(source_code or "").strip().upper()
    return "MOCK" in source or source == SOURCE_WEBSOCKET_MOCK


def evaluate_real_execution_market_source(
    session: Session,
    *,
    user_broker_account_id: int | None,
    broker_code: str | None,
    source_code: str | None,
) -> dict[str, Any]:
    """REAL_EXECUTION_REQUIRES_REAL_MARKET_DATA fail-closed."""

    broker = str(broker_code or "").upper()
    uba_id = int(user_broker_account_id or 0)
    source = str(source_code or "").strip().upper() or None
    result: dict[str, Any] = {
        "ok": True,
        "applied": False,
        "source_code": source,
        "reason": None,
    }
    if broker != "KIWOOM" or uba_id <= 0:
        return result
    if not kiwoom_uba_has_explicit_real_execution(session, uba_id):
        return result
    result["applied"] = True
    if source is None:
        result["ok"] = False
        result["reason"] = REASON_UNKNOWN_MARKET_SOURCE
        return result
    if source == SOURCE_REST_POLLING:
        result["ok"] = False
        result["reason"] = REASON_REST_POLLING_NOT_LIVE_SOT
        return result
    if is_mock_market_source(source) or source != SOURCE_WEBSOCKET_REAL:
        result["ok"] = False
        result["reason"] = REASON_REAL_EXECUTION_REQUIRES_REAL_MARKET_DATA
        return result
    return result
