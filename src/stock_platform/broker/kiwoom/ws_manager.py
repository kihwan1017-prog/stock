from __future__ import annotations

from collections import deque
from decimal import Decimal
from typing import Any

from stock_platform.broker.kiwoom.ws_runtime import (
    build_kiwoom_order_websocket,
    kiwoom_order_event_bus,
)
from stock_platform.database.session import (
    get_session_factory,
)
from stock_platform.broker.kiwoom.ws_service import (
    KiwoomOrderExecutionEventService,
)


class KiwoomOrderWebSocketManager:
    def __init__(self) -> None:
        self._client = None
        self._history: deque[dict[str, Any]] = deque(
            maxlen=500
        )
        # broker_order_id → 직전 filled_quantity (증분 체결용)
        self._last_filled: dict[str, Decimal] = {}

    async def handle_event(self, event) -> None:
        session = get_session_factory()()
        try:
            previous_filled = self._last_filled.get(
                str(getattr(event, "broker_order_id", "") or "")
            )
            result = (
                KiwoomOrderExecutionEventService(
                    session
                ).apply(event)
            )
            self._history.appendleft(result)

            # P0-2 — Pending 반영 후 TradingOrder/Execution 동기화
            try:
                from stock_platform.broker.kiwoom.ws_execution_bridge import (
                    order_execution_event_to_kiwoom_execution,
                )
                from stock_platform.trading.execution_sync_service import (
                    ExecutionSyncService,
                )

                sync_event = order_execution_event_to_kiwoom_execution(
                    event,
                    previous_filled_quantity=previous_filled,
                )
                if sync_event is not None:
                    ExecutionSyncService(session).synchronize(
                        sync_event,
                        actor="KIWOOM_ORDER_WS",
                    )
            except Exception:  # noqa: BLE001
                # TradingOrder 미매칭/중복은 Pending 성공을 깨지 않음
                # apply()가 이미 commit했을 수 있으므로 rollback만 시도
                try:
                    session.rollback()
                except Exception:  # noqa: BLE001
                    pass

            # 증분 추적용 스냅샷 갱신
            try:
                filled_now = Decimal(
                    str(getattr(event, "filled_quantity", 0) or 0)
                )
                oid = str(getattr(event, "broker_order_id", "") or "")
                if oid:
                    self._last_filled[oid] = filled_now
            except Exception:  # noqa: BLE001
                pass

            await kiwoom_order_event_bus.publish(event)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    async def start(self):
        if self._client is not None:
            status = self.status()
            # 포기(gave up) 후 task가 끝났으면 다시 시작 가능하도록 정리
            if status.get("running"):
                return {
                    "already_running": True,
                    **status,
                }
            await self.stop()

        self._client = build_kiwoom_order_websocket(
            self.handle_event
        )

        try:
            return await self._client.start()
        except Exception:
            self._client = None
            raise

    async def stop(self):
        if self._client is not None:
            await self._client.stop()
            self._client = None

    def status(self):
        if self._client is None:
            return {
                "running": False,
                "connected": False,
                "history_count": len(self._history),
            }

        return {
            **self._client.status(),
            "history_count": len(self._history),
            "subscriber_count": (
                kiwoom_order_event_bus.subscriber_count
            ),
        }

    def history(self):
        return list(self._history)


kiwoom_order_websocket_manager = (
    KiwoomOrderWebSocketManager()
)
