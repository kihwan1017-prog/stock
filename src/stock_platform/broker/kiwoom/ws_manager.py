from __future__ import annotations

from collections import deque
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

    async def handle_event(self, event) -> None:
        session = get_session_factory()()
        try:
            result = (
                KiwoomOrderExecutionEventService(
                    session
                ).apply(event)
            )
            self._history.appendleft(result)
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
