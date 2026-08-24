"""프로세스 전역 KIWOOM 시세 WS 런타임.

기동 시 자동 start 금지. Admin/운영 API가 명시 START 할 때만 연결한다.
REAL 주문 경로와 MOCK 시세를 섞지 않는다 (Fail Closed).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import structlog

from stock_platform.broker.kiwoom.market_realtime_client import (
    KiwoomMarketRealtimeClient,
)
from stock_platform.broker.kiwoom.market_realtime_contract import (
    REST_POLLING_IS_LIVE_RUNTIME_SOT,
    SOURCE_WEBSOCKET_REAL,
)
from stock_platform.common.settings import get_settings
from stock_platform.realtime.models import RealtimeQuote


logger = structlog.get_logger(__name__)


class KiwoomMarketRealtimeRuntime:
    """UBA credential 기반 시세 WS. account/strategy 하드코딩 없음."""

    def __init__(self) -> None:
        self._client: KiwoomMarketRealtimeClient | None = None
        self._task: asyncio.Task | None = None
        self._uba_id: int | None = None
        self._require_real: bool = True
        self._started_at: datetime | None = None

    def bind(self, client: KiwoomMarketRealtimeClient | None) -> None:
        """테스트/probe용 수동 바인딩."""

        self._client = client

    def status(self) -> dict[str, Any]:
        settings = get_settings()
        client_status = (
            self._client.status() if self._client is not None else None
        )
        task_running = bool(self._task is not None and not self._task.done())
        connected = bool(client_status and client_status.get("connected"))
        last_event_at = None
        feed_age = None
        if isinstance(client_status, dict):
            last_event_at = client_status.get("last_event_at")
            if last_event_at:
                try:
                    dt = datetime.fromisoformat(
                        str(last_event_at).replace("Z", "+00:00")
                    )
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    feed_age = (
                        datetime.now(timezone.utc) - dt.astimezone(timezone.utc)
                    ).total_seconds()
                except Exception:  # noqa: BLE001
                    feed_age = None
        return {
            "auto_start": bool(settings.kiwoom_market_realtime_auto_start),
            "running": task_running,
            "connected": connected,
            "user_broker_account_id": self._uba_id,
            "require_real": self._require_real,
            "started_at": (
                self._started_at.isoformat() if self._started_at else None
            ),
            "last_tick_at": last_event_at,
            "feed_age_seconds": feed_age,
            "process_market_environment": (
                "MOCK" if settings.kiwoom_market_data_is_mock else "REAL"
            ),
            "execution_process_kiwoom_use_mock": bool(
                settings.kiwoom_use_mock
            ),
            "rest_polling_is_live_runtime_sot": (
                REST_POLLING_IS_LIVE_RUNTIME_SOT
            ),
            "client": client_status,
        }

    async def start(
        self,
        *,
        user_broker_account_id: int,
        symbols: list[str],
        require_real: bool = True,
    ) -> dict[str, Any]:
        """시세 WS START. 다른 UBA/Upbit runner는 건드리지 않는다."""

        uba_id = int(user_broker_account_id)
        cleaned = sorted(
            {
                str(s).strip().upper()
                for s in (symbols or [])
                if str(s or "").strip()
            }
        )
        if uba_id <= 0:
            return {"started": False, "reason": "UBA_REQUIRED"}
        if not cleaned:
            return {"started": False, "reason": "SYMBOLS_REQUIRED"}

        settings = get_settings()
        if require_real and bool(settings.kiwoom_market_data_is_mock):
            return {
                "started": False,
                "reason": "MARKET_DATA_MOCK_FORBIDDEN",
                "process_market_environment": "MOCK",
            }

        # 동일 UBA에서 이미 RUNNING이면 심볼만 합집합 추가
        if (
            self._task is not None
            and not self._task.done()
            and self._client is not None
            and self._uba_id == uba_id
        ):
            self._client.subscribe_symbols(cleaned)
            return {
                "started": True,
                "already_running": True,
                "user_broker_account_id": uba_id,
                **self.status(),
            }

        # 다른 UBA가 돌고 있으면 교체 (시세 WS는 프로세스당 1개)
        if self._task is not None and not self._task.done():
            await self.stop()

        from stock_platform.broker.credential_adapter_factory import (
            build_kiwoom_order_config_from_vault,
            resolve_uba_credential,
        )
        from stock_platform.broker.kiwoom.token_cache import KiwoomTokenCache
        from stock_platform.broker.kiwoom.token_client import KiwoomTokenClient
        from stock_platform.broker.kiwoom.ws_config import (
            KiwoomMarketWebSocketConfig,
        )
        from stock_platform.database.session import get_session_factory

        session = get_session_factory()()
        try:
            resolved = resolve_uba_credential(
                session,
                uba_id,
                expected_broker="KIWOOM",
            )
            order_cfg = build_kiwoom_order_config_from_vault(resolved)
            if require_real and bool(getattr(order_cfg, "use_mock", False)):
                return {
                    "started": False,
                    "reason": "UBA_CREDENTIAL_IS_MOCK",
                    "user_broker_account_id": uba_id,
                }
            token_cache = KiwoomTokenCache(KiwoomTokenClient(order_cfg))
            if require_real:
                ws_cfg = KiwoomMarketWebSocketConfig.for_real_host()
            else:
                ws_cfg = KiwoomMarketWebSocketConfig.from_settings()
        except Exception as exc:  # noqa: BLE001
            return {
                "started": False,
                "reason": f"CREDENTIAL_RESOLVE_{type(exc).__name__}",
                "user_broker_account_id": uba_id,
            }
        finally:
            session.close()

        client = KiwoomMarketRealtimeClient(
            config=ws_cfg,
            token_cache=token_cache,
            quote_handler=self._handle_quote,
        )
        client.subscribe_symbols(cleaned)
        self._client = client
        self._uba_id = uba_id
        self._require_real = bool(require_real)
        self._started_at = datetime.now(timezone.utc)
        self._task = asyncio.create_task(
            client.run_forever(),
            name=f"kiwoom-market-realtime-{uba_id}",
        )
        # 연결 handshake까지 짧게 양보
        await asyncio.sleep(0.2)
        logger.info(
            "kiwoom_market_realtime_started",
            uba_id=uba_id,
            symbols=cleaned,
            environment=ws_cfg.environment,
            require_real=require_real,
        )
        return {
            "started": True,
            "already_running": False,
            "user_broker_account_id": uba_id,
            "symbols": cleaned,
            "environment": ws_cfg.environment,
            "source_code": SOURCE_WEBSOCKET_REAL
            if ws_cfg.environment == "REAL"
            else None,
            **self.status(),
        }

    async def stop(self) -> dict[str, Any]:
        """시세 WS STOP. Upbit/다른 runner는 유지."""

        client = self._client
        task = self._task
        if client is not None:
            await client.shutdown()
        if task is not None and not task.done():
            task.cancel()
            try:
                await asyncio.wait_for(task, timeout=2.0)
            except (asyncio.CancelledError, TimeoutError):
                pass
        self._task = None
        self._client = None
        self._uba_id = None
        self._started_at = None
        return {"stopped": True, **self.status()}

    async def _handle_quote(self, quote: RealtimeQuote) -> None:
        """Hub/cache/persistence 공통 경로로 시세 주입."""

        from stock_platform.realtime.manager import realtime_manager

        await realtime_manager.handle_quote(quote)


kiwoom_market_realtime_runtime = KiwoomMarketRealtimeRuntime()


async def publish_kiwoom_market_quote(quote: RealtimeQuote) -> None:
    """기존 Hub quote bus로 publish. 신규 엔진 없음."""

    from stock_platform.realtime.manager import realtime_manager

    await realtime_manager.handle_quote(quote)
