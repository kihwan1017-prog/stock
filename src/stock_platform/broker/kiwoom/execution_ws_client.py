from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import websockets

from stock_platform.broker.kiwoom.execution_parser import (
    KiwoomExecutionParser,
)
from stock_platform.broker.kiwoom.token_cache import (
    KiwoomTokenCache,
)
from stock_platform.broker.kiwoom.ws_config import (
    KiwoomWebSocketConfig,
)

logger = logging.getLogger(__name__)

EventHandler = Callable[
    [Any],
    Awaitable[None],
]


class KiwoomExecutionWebSocketClient:
    def __init__(
        self,
        *,
        config: KiwoomWebSocketConfig,
        token_cache: KiwoomTokenCache,
        parser: KiwoomExecutionParser,
        event_handler: EventHandler,
    ) -> None:
        self._config = config
        self._token_cache = token_cache
        self._parser = parser
        self._event_handler = event_handler
        self._stop_event = asyncio.Event()

    async def run_forever(self) -> None:
        delay = (
            self._config
            .reconnect_min_seconds
        )

        while not self._stop_event.is_set():
            try:
                await self._connect_once()
                delay = (
                    self._config
                    .reconnect_min_seconds
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "Kiwoom execution WebSocket "
                    "disconnected"
                )

                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=delay,
                    )
                except TimeoutError:
                    pass

                delay = min(
                    delay * 2,
                    self._config
                    .reconnect_max_seconds,
                )

    async def shutdown(self) -> None:
        self._stop_event.set()

    async def _connect_once(self) -> None:
        token = self._token_cache.get()

        async with websockets.connect(
            self._config.endpoint,
            ping_interval=(
                self._config
                .ping_interval_seconds
            ),
            ping_timeout=(
                self._config
                .ping_timeout_seconds
            ),
            max_size=2**22,
        ) as socket:
            await socket.send(
                json.dumps(
                    self._login_message(
                        token.token
                    ),
                    ensure_ascii=False,
                )
            )

            await socket.send(
                json.dumps(
                    self._subscription_message(),
                    ensure_ascii=False,
                )
            )

            async for raw in socket:
                message = json.loads(raw)

                if self._is_ping(message):
                    await socket.send(
                        json.dumps(message)
                    )
                    continue

                for event in (
                    self._parser
                    .parse_message(message)
                ):
                    await self._event_handler(
                        event
                    )

                if self._stop_event.is_set():
                    break

    @staticmethod
    def _login_message(
        token: str,
    ) -> dict[str, str]:
        return {
            "trnm": "LOGIN",
            "token": token,
        }

    def _subscription_message(
        self,
    ) -> dict[str, Any]:
        return {
            "trnm": "REG",
            "grp_no": "1",
            "refresh": "1",
            "data": [
                {
                    "item": [""],
                    "type": [
                        self._config
                        .service_type
                    ],
                }
            ],
        }

    @staticmethod
    def _is_ping(
        message: dict[str, Any],
    ) -> bool:
        return (
            str(message.get("trnm", ""))
            .upper()
            == "PING"
        )
