"""프로세스 전역 KIWOOM 시세 WS 런타임.

Admin/운영/stack-restore/watchdog L1 가 명시 START 할 때만 연결한다.
기동 시 무조건부 auto_start flag는 기본 OFF (settings).
REAL 주문 경로와 MOCK 시세를 섞지 않는다 (Fail Closed).

동시 start race 로 자기 task 를 cancel 하지 않도록 asyncio.Lock 으로 직렬화한다.
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

# handshake 대기 (초) — restore thrash 방지용 최소 연결 확인
_CONNECT_WAIT_SECONDS = 3.0


class KiwoomMarketRealtimeRuntime:
    """UBA credential 기반 시세 WS. account/strategy 하드코딩 없음."""

    def __init__(self) -> None:
        self._client: KiwoomMarketRealtimeClient | None = None
        self._task: asyncio.Task | None = None
        self._uba_id: int | None = None
        self._require_real: bool = True
        self._started_at: datetime | None = None
        self._generation: int = 0
        self._lock = asyncio.Lock()

    def _loop_safe_lock(self) -> asyncio.Lock:
        """현재 event loop에 묶인 Lock — loop 교체/stall 시 재생성.

        APScheduler vs FastAPI request loop 불일치로
        'Lock is bound to a different event loop' 가 나면
        TOP10 refresh/subscribe 가 실패하고 FIXED-only 로 남을 수 있다.
        """

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return self._lock
        lock = self._lock
        bound = getattr(lock, "_loop", None)
        if bound is not None and bound is not loop:
            logger.warning(
                "kiwoom_market_realtime_lock_recreated",
                reason="EVENT_LOOP_MISMATCH",
            )
            self._lock = asyncio.Lock()
            return self._lock
        return lock

    def bind(self, client: KiwoomMarketRealtimeClient | None) -> None:
        """테스트/probe용 수동 바인딩."""

        self._client = client

    def _task_running(self) -> bool:
        return bool(self._task is not None and not self._task.done())

    def status(self) -> dict[str, Any]:
        settings = get_settings()
        client_status = (
            self._client.status() if self._client is not None else None
        )
        task_running = self._task_running()
        # task 가 죽었으면 connected stale 금지 (과거 connected=true/running=false)
        connected = bool(
            task_running
            and client_status
            and client_status.get("connected")
        )
        last_event_at = None
        feed_age = None
        last_frame_at = None
        frame_age = None
        if isinstance(client_status, dict):
            last_event_at = client_status.get("last_event_at")
            last_frame_at = client_status.get("last_frame_at")
            if last_frame_at and task_running:
                try:
                    fdt = datetime.fromisoformat(
                        str(last_frame_at).replace("Z", "+00:00")
                    )
                    if fdt.tzinfo is None:
                        fdt = fdt.replace(tzinfo=timezone.utc)
                    frame_age = (
                        datetime.now(timezone.utc) - fdt.astimezone(timezone.utc)
                    ).total_seconds()
                except Exception:  # noqa: BLE001
                    frame_age = None
            if last_event_at and task_running:
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
            "generation_id": self._generation,
            "started_at": (
                self._started_at.isoformat() if self._started_at else None
            ),
            "lifecycle": (
                (client_status or {}).get("lifecycle")
                if isinstance(client_status, dict)
                else None
            ),
            "last_tick_at": last_event_at if task_running else None,
            "feed_age_seconds": feed_age,
            "last_frame_at": last_frame_at if task_running else None,
            "frame_age_seconds": frame_age,
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
        connect_wait_seconds: float = _CONNECT_WAIT_SECONDS,
    ) -> dict[str, Any]:
        """시세 WS START. 다른 UBA/Upbit runner는 건드리지 않는다."""

        async with self._loop_safe_lock():
            return await self._start_locked(
                user_broker_account_id=user_broker_account_id,
                symbols=symbols,
                require_real=require_real,
                connect_wait_seconds=connect_wait_seconds,
            )

    async def _start_locked(
        self,
        *,
        user_broker_account_id: int,
        symbols: list[str],
        require_real: bool,
        connect_wait_seconds: float,
    ) -> dict[str, Any]:
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
        if require_real and settings.kiwoom_market_data_use_mock is True:
            return {
                "started": False,
                "reason": "MARKET_DATA_MOCK_FORBIDDEN",
                "process_market_environment": "MOCK",
                "note": "explicit KIWOOM_MARKET_DATA_USE_MOCK=true",
            }

        # 동일 UBA에서 이미 RUNNING이면 심볼만 합집합 (stop 금지 — thrash 방지)
        if (
            self._task_running()
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
        if self._task_running() and self._uba_id != uba_id:
            await self._stop_locked()

        def _resolve_real_feed_client() -> dict[str, Any]:
            """Vault/credential resolve는 sync — event loop 블로킹 방지용."""

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

        # credential resolve 중 다른 start 가 이미 task 를 띄웠을 수 있음
        resolved_parts = await asyncio.to_thread(_resolve_real_feed_client)
        if (
            self._task_running()
            and self._client is not None
            and self._uba_id == uba_id
        ):
            self._client.subscribe_symbols(cleaned)
            return {
                "started": True,
                "already_running": True,
                "user_broker_account_id": uba_id,
                "note": "RACE_LOST_TO_PEER_START",
                **self.status(),
            }
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

        # 죽은 task 잔여 정리 (cancel 없이 참조만 교체)
        if self._task is not None and self._task.done():
            self._task = None

        self._generation += 1
        generation_id = self._generation

        client = KiwoomMarketRealtimeClient(
            config=ws_cfg,
            token_cache=token_cache,
            quote_handler=self._handle_quote,
            generation_id=generation_id,
        )
        client.subscribe_symbols(cleaned)
        self._client = client
        self._uba_id = uba_id
        self._require_real = bool(require_real)
        self._started_at = datetime.now(timezone.utc)
        self._task = asyncio.create_task(
            self._run_feed_task(client, generation_id),
            name=f"kiwoom-market-realtime-{uba_id}-g{generation_id}",
        )

        # handshake 대기 — running 유지 여부 확인 (connected 는 선택)
        wait_budget = max(0.2, float(connect_wait_seconds or 0.2))
        deadline = asyncio.get_event_loop().time() + wait_budget
        while asyncio.get_event_loop().time() < deadline:
            if not self._task_running():
                break
            st = self.status()
            if st.get("connected"):
                break
            await asyncio.sleep(0.15)

        still_running = self._task_running()
        st = self.status()
        logger.info(
            "kiwoom_market_realtime_started",
            uba_id=uba_id,
            symbols=cleaned,
            environment=ws_cfg.environment,
            require_real=require_real,
            running=still_running,
            connected=bool(st.get("connected")),
            last_error=(st.get("client") or {}).get("last_error")
            if isinstance(st.get("client"), dict)
            else None,
        )
        if not still_running:
            return {
                "started": False,
                "already_running": False,
                "reason": "FEED_TASK_EXITED",
                "user_broker_account_id": uba_id,
                "symbols": cleaned,
                "environment": ws_cfg.environment,
                **st,
            }
        return {
            "started": True,
            "already_running": False,
            "user_broker_account_id": uba_id,
            "symbols": cleaned,
            "environment": ws_cfg.environment,
            "source_code": SOURCE_WEBSOCKET_REAL
            if ws_cfg.environment == "REAL"
            else None,
            **st,
        }

    async def _run_feed_task(
        self,
        client: KiwoomMarketRealtimeClient,
        generation_id: int,
    ) -> None:
        """generation-aware feed task — old cleanup 이 new state 덮어쓰기 방지."""

        try:
            await client.run_forever()
        except asyncio.CancelledError:
            client.note_exit_reason("TASK_CANCELLED")
            raise
        except Exception as exc:  # noqa: BLE001
            client.note_exit_reason(type(exc).__name__)
            raise
        finally:
            if generation_id == self._generation:
                logger.info(
                    "kiwoom_market_realtime_task_exit",
                    generation_id=generation_id,
                    uba_id=self._uba_id,
                    lifecycle=(client.status().get("lifecycle") or {}),
                )

    async def stop(self) -> dict[str, Any]:
        """시세 WS STOP. Upbit/다른 runner는 유지."""

        async with self._loop_safe_lock():
            return await self._stop_locked()

    async def _stop_locked(self) -> dict[str, Any]:
        stop_generation = self._generation
        client = self._client
        task = self._task
        if client is not None:
            client.note_exit_reason("CLIENT_SHUTDOWN")
            await client.shutdown()
        if task is not None and not task.done():
            task.cancel()
            try:
                await asyncio.wait_for(task, timeout=2.0)
            except (asyncio.CancelledError, TimeoutError):
                pass
        # 새 generation start 가 이미 올라갔으면 state 유지
        if self._generation == stop_generation:
            self._task = None
            self._client = None
            self._uba_id = None
            self._started_at = None
        return {"stopped": True, "generation_id": stop_generation, **self.status()}

    async def _handle_quote(self, quote: RealtimeQuote) -> None:
        """Hub/cache/persistence 공통 경로로 시세 주입."""

        from stock_platform.realtime.manager import realtime_manager

        await realtime_manager.handle_quote(quote)


kiwoom_market_realtime_runtime = KiwoomMarketRealtimeRuntime()


async def publish_kiwoom_market_quote(quote: RealtimeQuote) -> None:
    """기존 Hub quote bus로 publish. 신규 엔진 없음."""

    from stock_platform.realtime.manager import realtime_manager

    await realtime_manager.handle_quote(quote)
