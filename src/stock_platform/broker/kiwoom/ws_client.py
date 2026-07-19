from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

import structlog
import websockets
from websockets.exceptions import ConnectionClosed

from stock_platform.broker.kiwoom.auth import (
    KiwoomTokenProvider,
)
from stock_platform.broker.kiwoom.ws_mapper import (
    KiwoomOrderExecutionMapper,
)
from stock_platform.broker.kiwoom.ws_models import (
    KiwoomOrderExecutionEvent,
)


logger = structlog.get_logger(__name__)

EventHandler = Callable[
    [KiwoomOrderExecutionEvent],
    Awaitable[None],
]


class KiwoomOrderExecutionWebSocketClient:
    """
    키움 주문체결 WebSocket 클라이언트.

    구독 메시지 형식은 키움 계정에 제공되는 최신 공식 가이드와
    샘플을 확인해 환경변수 JSON으로 주입한다.
    """

    def __init__(
        self,
        *,
        token_provider: KiwoomTokenProvider,
        websocket_url: str,
        subscribe_message: dict[str, Any],
        handler: EventHandler,
        reconnect_max_seconds: float = 60.0,
        max_consecutive_failures: int = 8,
    ) -> None:
        if not websocket_url.startswith("wss://"):
            raise ValueError(
                "websocket_url must start with wss://"
            )
        if not subscribe_message:
            raise ValueError(
                "subscribe_message must not be empty"
            )

        self._token_provider = token_provider
        self._websocket_url = websocket_url
        self._subscribe_message = subscribe_message
        self._handler = handler
        self._reconnect_max_seconds = (
            reconnect_max_seconds
        )
        # 0이면 실패해도 계속 재시도 (운영에서만 신중히 사용)
        self._max_consecutive_failures = max(
            0,
            max_consecutive_failures,
        )
        self._stop_event = asyncio.Event()
        self._connected = False
        self._received_count = 0
        self._mapped_count = 0
        self._consecutive_failures = 0
        self._last_error: str | None = None
        self._task: asyncio.Task | None = None

    async def start(self) -> dict[str, Any]:
        if self._task is not None:
            raise ValueError(
                "Kiwoom WebSocket client is already running"
            )

        self._stop_event.clear()
        self._task = asyncio.create_task(
            self.run_forever(),
            name="kiwoom-order-execution-websocket",
        )
        return self.status()

    async def run_forever(self) -> None:
        retry_seconds = 1.0

        while not self._stop_event.is_set():
            try:
                await self._run_once()
                retry_seconds = 1.0
                self._consecutive_failures = 0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._connected = False
                self._last_error = str(exc)
                self._consecutive_failures += 1
                # mock/로컬 재연결 루프는 traceback 대신 warning만
                logger.warning(
                    "kiwoom_websocket_failed",
                    error=str(exc),
                    retry_seconds=retry_seconds,
                    consecutive_failures=self._consecutive_failures,
                )

                if (
                    self._max_consecutive_failures > 0
                    and self._consecutive_failures
                    >= self._max_consecutive_failures
                ):
                    logger.error(
                        "kiwoom_websocket_gave_up",
                        error=str(exc),
                        consecutive_failures=self._consecutive_failures,
                        hint=(
                            "POST /api/v1/broker/kiwoom/"
                            "order-websocket/start 로 다시 시작하거나 "
                            "KIWOOM_RECOVERY_START_WS=false 로 자동시작을 끄세요"
                        ),
                    )
                    self._stop_event.set()
                    break

                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=retry_seconds,
                    )
                except asyncio.TimeoutError:
                    pass

                retry_seconds = min(
                    retry_seconds * 2,
                    self._reconnect_max_seconds,
                )

    async def _run_once(self) -> None:
        token = await self._token_provider.get_token()

        headers = {
            "Authorization": f"Bearer {token.token}",
        }

        async with websockets.connect(
            self._websocket_url,
            additional_headers=headers,
            ping_interval=30,
            ping_timeout=10,
            close_timeout=5,
            max_queue=2048,
        ) as websocket:
            await websocket.send(
                json.dumps(
                    self._subscribe_message,
                    ensure_ascii=False,
                )
            )

            self._connected = True
            self._last_error = None

            while not self._stop_event.is_set():
                try:
                    raw = await asyncio.wait_for(
                        websocket.recv(),
                        timeout=90,
                    )
                except asyncio.TimeoutError:
                    await websocket.ping()
                    continue
                except ConnectionClosed:
                    break

                self._received_count += 1

                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")

                payload = json.loads(raw)

                if not isinstance(payload, dict):
                    continue

                event = (
                    KiwoomOrderExecutionMapper.map(
                        payload
                    )
                )

                if not event.broker_order_id:
                    continue

                self._mapped_count += 1
                await self._handler(event)

        self._connected = False

    async def stop(self) -> None:
        self._stop_event.set()

        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            finally:
                self._task = None

    def status(self) -> dict[str, Any]:
        return {
            "connected": self._connected,
            "websocket_url": self._websocket_url,
            "received_count": self._received_count,
            "mapped_count": self._mapped_count,
            "consecutive_failures": self._consecutive_failures,
            "last_error": self._last_error,
            "running": (
                self._task is not None
                and not self._task.done()
            ),
        }
