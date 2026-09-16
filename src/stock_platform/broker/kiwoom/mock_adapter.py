"""Kiwoom MOCK 브로커 어댑터 — 네트워크/실계좌 없이 결정적 응답."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from stock_platform.broker.adapter import BrokerAdapter
from stock_platform.broker.models import (
    BrokerOrderRequest,
    BrokerOrderResult,
    BrokerOrderStatus,
)


class KiwoomMockBrokerAdapter(BrokerAdapter):
    """LIVE API 호출 없음. reject_symbols / reject_all 로 거부 시뮬레이션."""

    def __init__(
        self,
        *,
        reject_symbols: set[str] | None = None,
        reject_all: bool = False,
    ) -> None:
        self._reject_symbols = {
            s.upper() for s in (reject_symbols or set())
        }
        self._reject_all = bool(reject_all)
        self._orders: dict[str, BrokerOrderRequest] = {}
        self.submit_count = 0
        self.cancel_count = 0
        self.replace_count = 0
        self.live_http_calls = 0  # 항상 0 — 관측용

    def submit_order(
        self,
        request: BrokerOrderRequest,
        **_kwargs,
    ) -> BrokerOrderResult:
        self.submit_count += 1
        symbol = str(request.symbol or "").upper()
        if self._reject_all or symbol in self._reject_symbols:
            return BrokerOrderResult(
                accepted=False,
                status=BrokerOrderStatus.REJECTED,
                broker_order_id=None,
                submitted_at=datetime.now(timezone.utc),
                reject_code="MOCK_REJECTED",
                reject_message=f"mock reject symbol={symbol}",
            )
        stable = "".join(
            ch for ch in str(request.client_order_id).upper() if ch.isalnum()
        )
        if len(stable) < 8:
            stable = f"{stable}{uuid4().hex}".upper()
        broker_order_id = f"KMOCK-{stable[:16]}"
        self._orders[broker_order_id] = request
        return BrokerOrderResult(
            accepted=True,
            status=BrokerOrderStatus.ACCEPTED,
            broker_order_id=broker_order_id,
            submitted_at=datetime.now(timezone.utc),
        )

    def cancel_order(
        self,
        broker_order_id: str,
        **_kwargs,
    ) -> BrokerOrderResult:
        self.cancel_count += 1
        return BrokerOrderResult(
            accepted=True,
            status=BrokerOrderStatus.CANCELLED,
            broker_order_id=broker_order_id,
            submitted_at=datetime.now(timezone.utc),
        )

    def replace_order(
        self,
        broker_order_id: str,
        request: BrokerOrderRequest,
        **_kwargs,
    ) -> BrokerOrderResult:
        self.replace_count += 1
        _ = request
        # 정정 성공 시 동일 broker_order_id 유지 (Mock)
        return BrokerOrderResult(
            accepted=True,
            status=BrokerOrderStatus.ACCEPTED,
            broker_order_id=broker_order_id,
            submitted_at=datetime.now(timezone.utc),
        )

    def get_order(
        self,
        broker_order_id: str,
    ) -> BrokerOrderResult:
        return BrokerOrderResult(
            accepted=True,
            status=BrokerOrderStatus.ACCEPTED,
            broker_order_id=broker_order_id,
            submitted_at=datetime.now(timezone.utc),
        )
