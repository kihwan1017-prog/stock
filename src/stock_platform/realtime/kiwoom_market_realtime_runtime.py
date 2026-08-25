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
        # 프로세스 KIWOOM_USE_MOCK 단독으로는 REAL lifecycle feed를 막지 않는다.
        # 명시적 KIWOOM_MARKET_DATA_USE_MOCK=true 만 require_real 경로를 차단.
        # Canonical SoT: UBA credential REAL + for_real_host() (아래 vault resolve).
        if require_real and settings.kiwoom_market_data_use_mock is True:
            return {
                "started": False,
                "reason": "MARKET_DATA_MOCK_FORBIDDEN",
                "process_market_environment": "MOCK",
                "note": "explicit KIWOOM_MARKET_DATA_USE_MOCK=true",
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

        def _resolve_real_feed_client() -> dict[str, Any]:
            """Vault/credential resolve는 sync — event loop 블로킹 방지용.

            시세 feed는 last_used_at write-lock이 불필요 (touch_last_used=False).
            단계별 monotonic timing만 기록 — secret 미포함.
            """

            import time

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

            timings: dict[str, float] = {}
            t_begin = time.monotonic()

            def _mark(name: str, started: float) -> None:
                timings[name] = round((time.monotonic() - started) * 1000, 1)

            t0 = time.monotonic()
            session = get_session_factory()()
            _mark("db_acquire_ms", t0)
            try:
                t1 = time.monotonic()
                # LOCAL_CREDENTIAL_RESOLVE only — token HTTP는 WS run_forever에서
                resolved = resolve_uba_credential(
                    session,
                    uba_id,
                    expected_broker="KIWOOM",
                    touch_last_used=False,
                )
                _mark("local_credential_resolve_ms", t1)
                t2 = time.monotonic()
                order_cfg = build_kiwoom_order_config_from_vault(resolved)
                _mark("build_order_cfg_ms", t2)
                if require_real and bool(getattr(order_cfg, "use_mock", False)):
                    return {
                        "ok": False,
                        "reason": "UBA_CREDENTIAL_IS_MOCK",
                        "timings": timings,
                    }
                t3 = time.monotonic()
                token_cache = KiwoomTokenCache(KiwoomTokenClient(order_cfg))
                if require_real:
                    ws_cfg = KiwoomMarketWebSocketConfig.for_real_host()
                else:
                    ws_cfg = KiwoomMarketWebSocketConfig.from_settings()
                _mark("token_cache_ws_cfg_ms", t3)
                timings["total_ms"] = round(
                    (time.monotonic() - t_begin) * 1000, 1
                )
                logger.info(
                    "kiwoom_feed_credential_resolve_timings",
                    uba_id=uba_id,
                    credential_id=int(resolved.credential_id),
                    broker=str(resolved.broker_code),
                    use_mock=bool(order_cfg.use_mock),
                    **timings,
                )
                return {
                    "ok": True,
                    "token_cache": token_cache,
                    "ws_cfg": ws_cfg,
                    "timings": timings,
                }
            except Exception as exc:  # noqa: BLE001
                timings["total_ms"] = round(
                    (time.monotonic() - t_begin) * 1000, 1
                )
                logger.warning(
                    "kiwoom_feed_credential_resolve_failed",
                    uba_id=uba_id,
                    error=type(exc).__name__,
                    **timings,
                )
                return {
                    "ok": False,
                    "reason": f"CREDENTIAL_RESOLVE_{type(exc).__name__}",
                    "timings": timings,
                }
            finally:
                session.close()

        resolved_parts = await asyncio.to_thread(_resolve_real_feed_client)
        if not resolved_parts.get("ok"):
            return {
                "started": False,
                "reason": str(
                    resolved_parts.get("reason") or "CREDENTIAL_RESOLVE_FAILED"
                ),
                "user_broker_account_id": uba_id,
            }
        token_cache = resolved_parts["token_cache"]
        ws_cfg = resolved_parts["ws_cfg"]

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
