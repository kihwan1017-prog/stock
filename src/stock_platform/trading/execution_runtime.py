from __future__ import annotations

import asyncio
from sqlalchemy.orm import Session, sessionmaker

from stock_platform.broker.kiwoom.execution_models import (
    KiwoomExecutionEvent,
)
from stock_platform.broker.kiwoom.execution_ws_client import (
    KiwoomExecutionWebSocketClient,
)
from stock_platform.trading.execution_sync_service import (
    ExecutionSyncService,
)


class ExecutionRuntime:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        client: KiwoomExecutionWebSocketClient,
    ) -> None:
        self._session_factory = session_factory
        self._client = client
        self._task: asyncio.Task | None = None

    async def handle_event(
        self,
        event: KiwoomExecutionEvent,
    ) -> None:
        def sync() -> None:
            with self._session_factory() as session:
                ExecutionSyncService(
                    session
                ).synchronize(event)
                session.commit()

        await asyncio.to_thread(sync)

    def start(self) -> None:
        if (
            self._task is None
            or self._task.done()
        ):
            self._task = asyncio.create_task(
                self._client.run_forever(),
                name=(
                    "kiwoom-execution-websocket"
                ),
            )

    async def shutdown(self) -> None:
        await self._client.shutdown()

        if self._task is not None:
            await self._task
            self._task = None
