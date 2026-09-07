# -*- coding: utf-8 -*-
"""Upbit market SELL port — controlled residual cleanup 전용."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from stock_platform.broker.credential_adapter_factory import (
    build_upbit_adapter_for_uba,
)
from stock_platform.broker.models import (
    BrokerOrderRequest,
    BrokerOrderSide,
    BrokerOrderType,
)
from stock_platform.broker.upbit.exceptions import UpbitAmbiguousOrderResultError
from stock_platform.broker.upbit.rules import round_upbit_volume


def upbit_identifier_from_key(idempotency_key: str) -> str:
    """Upbit identifier ≤36, 계정 unique."""

    raw = "".join(ch for ch in str(idempotency_key) if ch.isalnum())
    return ("CRC" + raw)[:36]


class UpbitControlledResidualSellPort:
    """기존 UpbitBrokerAdapter 경로로 market SELL (신규 주문방식 금지)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def submit_market_sell(
        self,
        *,
        uba_id: int,
        symbol: str,
        quantity: Decimal,
        idempotency_key: str,
    ) -> dict[str, Any]:
        qty = round_upbit_volume(Decimal(str(quantity)))
        if qty <= 0:
            raise ValueError("cleanup sell qty must be > 0")

        identifier = upbit_identifier_from_key(idempotency_key)
        adapter = build_upbit_adapter_for_uba(self._session, int(uba_id))
        request = BrokerOrderRequest(
            client_order_id=f"CRC-{identifier}"[:64],
            exchange_code="UPBIT",
            symbol=str(symbol).upper(),
            side=BrokerOrderSide.SELL,
            order_type=BrokerOrderType.MARKET,
            quantity=qty,
            price=None,
            user_broker_account_id=int(uba_id),
            broker_code="UPBIT",
            account_type="LIVE",
            upbit_client_identifier=identifier,
        )
        try:
            result = adapter.submit_order(
                request, idempotency_key=f"CRC_SUBMIT:{identifier}"
            )
        except UpbitAmbiguousOrderResultError as exc:
            return {
                "accepted": False,
                "ambiguous": True,
                "status": "AMBIGUOUS",
                "broker_order_id": None,
                "identifier": identifier,
                "error": str(exc)[:500],
                "submitted_at": datetime.now(timezone.utc).isoformat(),
            }

        return {
            "accepted": bool(result.accepted),
            "ambiguous": False,
            "status": str(result.status.value if hasattr(result.status, "value") else result.status),
            "broker_order_id": result.broker_order_id,
            "identifier": identifier,
            "reject_code": result.reject_code,
            "reject_message": (result.reject_message or "")[:500],
            "submitted_at": result.submitted_at.isoformat()
            if result.submitted_at
            else datetime.now(timezone.utc).isoformat(),
        }

    def get_order(
        self,
        *,
        uba_id: int,
        uuid: str | None = None,
        identifier: str | None = None,
    ) -> dict[str, Any]:
        adapter = build_upbit_adapter_for_uba(self._session, int(uba_id))
        client = adapter._client  # noqa: SLF001 — reconcile 전용
        return client.get_order(uuid=uuid, identifier=identifier)
