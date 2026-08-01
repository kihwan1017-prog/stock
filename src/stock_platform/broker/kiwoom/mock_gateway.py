"""Kiwoom MOCK 주문 게이트웨이 — 접수·체결·재조정 (LIVE HTTP 0)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from stock_platform.broker.kiwoom.execution_models import (
    KiwoomExecutionEvent,
)
from stock_platform.broker.kiwoom.mock_adapter import (
    KiwoomMockBrokerAdapter,
)
from stock_platform.broker.kiwoom.ws_execution_bridge import (
    order_execution_event_to_kiwoom_execution,
)
from stock_platform.broker.kiwoom.ws_models import (
    KiwoomOrderEventType,
    KiwoomOrderExecutionEvent,
)
from stock_platform.broker.models import (
    BrokerOrderRequest,
    BrokerOrderSide,
    BrokerOrderType,
)
from stock_platform.order.entities import TradingOrderEntity
from stock_platform.order.models import OrderStatus
from stock_platform.order.repository import TradingOrderRepository
from stock_platform.trading.execution_sync_service import (
    ExecutionSyncResult,
    ExecutionSyncService,
)


class KiwoomMockOrderGateway:
    """결정적 모의 이벤트만으로 TradingOrder↔Execution↔Ledger 경로를 구동."""

    def __init__(
        self,
        session: Session,
        *,
        adapter: KiwoomMockBrokerAdapter | None = None,
    ) -> None:
        self._session = session
        self._orders = TradingOrderRepository(session)
        self.adapter = adapter or KiwoomMockBrokerAdapter()
        self._last_filled: dict[str, Decimal] = {}
        self.live_api_calls = 0

    def accept_order(
        self,
        *,
        paper_account_id: int,
        user_broker_account_id: int,
        symbol: str,
        side: str,
        quantity: Decimal,
        price: Decimal,
        client_order_id: str | None = None,
        exchange_code: str = "KRX",
    ) -> TradingOrderEntity:
        """Mock 어댑터 접수 → ACCEPTED TradingOrder 생성."""

        cid = client_order_id or f"KMOCK-{uuid4().hex[:20]}"
        req = BrokerOrderRequest(
            client_order_id=cid,
            exchange_code=exchange_code,
            symbol=symbol,
            side=BrokerOrderSide(side.upper()),
            order_type=BrokerOrderType.LIMIT,
            quantity=quantity,
            price=price,
            account_id=paper_account_id,
        )
        result = self.adapter.submit_order(req)
        if not result.accepted or not result.broker_order_id:
            order = TradingOrderEntity(
                client_order_id=cid,
                account_id=paper_account_id,
                user_broker_account_id=user_broker_account_id,
                broker_code="KIWOOM",
                exchange_code=exchange_code,
                symbol=str(symbol).upper(),
                side_code=side.upper(),
                order_type_code="LIMIT",
                order_quantity=quantity,
                order_price=price,
                filled_quantity=Decimal("0"),
                remaining_quantity=quantity,
                filled_amount=Decimal("0"),
                status_code=OrderStatus.REJECTED.value,
                reject_code=result.reject_code,
                reject_message=result.reject_message,
                metadata_payload={
                    "environment": "MOCK",
                    "source": "KIWOOM_MOCK_GATEWAY",
                    "kiwoom_use_mock": True,
                },
            )
            self._session.add(order)
            self._session.flush()
            self._session.commit()
            return order

        order = TradingOrderEntity(
            client_order_id=cid,
            broker_order_id=result.broker_order_id,
            account_id=paper_account_id,
            user_broker_account_id=user_broker_account_id,
            broker_code="KIWOOM",
            exchange_code=exchange_code,
            symbol=str(symbol).upper(),
            side_code=side.upper(),
            order_type_code="LIMIT",
            order_quantity=quantity,
            order_price=price,
            filled_quantity=Decimal("0"),
            remaining_quantity=quantity,
            filled_amount=Decimal("0"),
            status_code=OrderStatus.ACCEPTED.value,
            accepted_at=datetime.now(timezone.utc),
            metadata_payload={
                "environment": "MOCK",
                "source": "KIWOOM_MOCK_GATEWAY",
                "kiwoom_use_mock": True,
            },
        )
        self._session.add(order)
        self._session.flush()
        self._session.commit()
        return order

    def apply_fill_event(
        self,
        *,
        broker_order_id: str,
        filled_quantity: Decimal,
        remaining_quantity: Decimal,
        fill_price: Decimal,
        event_type: KiwoomOrderEventType,
        symbol: str,
        side: str,
        broker_execution_id: str | None = None,
        actor: str = "KIWOOM_MOCK_WS",
    ) -> ExecutionSyncResult:
        """WS 스타일 체결 이벤트 → bridge → ExecutionSync (+ Ledger)."""

        prev = self._last_filled.get(str(broker_order_id))
        raw: dict[str, Any] = {}
        if broker_execution_id:
            raw["broker_execution_id"] = broker_execution_id
        event = KiwoomOrderExecutionEvent(
            account_number="MOCK",
            broker_order_id=str(broker_order_id),
            original_order_id=None,
            exchange_code="KRX",
            symbol=str(symbol).upper(),
            side=side.upper(),
            event_type=event_type,
            order_quantity=filled_quantity + remaining_quantity,
            filled_quantity=filled_quantity,
            remaining_quantity=remaining_quantity,
            fill_price=fill_price,
            average_fill_price=fill_price,
            event_time=datetime.now(timezone.utc),
            received_at=datetime.now(timezone.utc),
            raw_data=raw,
        )
        sync_event = order_execution_event_to_kiwoom_execution(
            event, previous_filled_quantity=prev
        )
        if sync_event is None:
            return ExecutionSyncResult(
                duplicate=False,
                order_found=True,
                execution_id=None,
                order_status=None,
            )
        result = ExecutionSyncService(self._session).synchronize(
            sync_event, actor=actor
        )
        self._last_filled[str(broker_order_id)] = Decimal(str(filled_quantity))
        return result

    def reconcile_remote_filled(
        self,
        *,
        broker_order_id: str,
        remote_filled_quantity: Decimal,
        fill_price: Decimal,
        symbol: str,
        side: str,
        broker_execution_id: str | None = None,
    ) -> ExecutionSyncResult:
        """원격 누적 체결량과 로컬 불일치 시 증분 반영 (Recovery/Recon)."""

        order = self._orders.get_by_broker_order_id(
            broker_code="KIWOOM",
            broker_order_id=str(broker_order_id),
        )
        if order is None:
            return ExecutionSyncResult(
                duplicate=False,
                order_found=False,
                execution_id=None,
                order_status=None,
            )
        local_filled = Decimal(str(order.filled_quantity or 0))
        remote = Decimal(str(remote_filled_quantity))
        if remote <= local_filled:
            return ExecutionSyncResult(
                duplicate=True,
                order_found=True,
                execution_id=None,
                order_status=order.status_code,
            )
        remaining = max(
            Decimal("0"),
            Decimal(str(order.order_quantity)) - remote,
        )
        event_type = (
            KiwoomOrderEventType.FILLED
            if remaining <= 0
            else KiwoomOrderEventType.PARTIALLY_FILLED
        )
        # last_filled를 로컬 기준으로 맞춰 증분만 반영
        self._last_filled[str(broker_order_id)] = local_filled
        return self.apply_fill_event(
            broker_order_id=str(broker_order_id),
            filled_quantity=remote,
            remaining_quantity=remaining,
            fill_price=fill_price,
            event_type=event_type,
            symbol=symbol,
            side=side,
            broker_execution_id=broker_execution_id
            or f"RECON:{broker_order_id}:{remote}",
            actor="KIWOOM_MOCK_RECONCILE",
        )

    def apply_direct_execution(
        self,
        event: KiwoomExecutionEvent,
        *,
        actor: str = "KIWOOM_MOCK",
    ) -> ExecutionSyncResult:
        return ExecutionSyncService(self._session).synchronize(
            event, actor=actor
        )
