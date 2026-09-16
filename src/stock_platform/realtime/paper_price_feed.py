"""Paper 결정적 가격 공급 — LIVE WebSocket 미사용."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Sequence

import structlog

from stock_platform.common.settings import get_settings
from stock_platform.realtime.manager import realtime_manager
from stock_platform.realtime.models import MarketEventType, RealtimeQuote

logger = structlog.get_logger(__name__)


class PaperPriceFeed:
    """테스트/Replay용 가격 시퀀스를 Quote Bus에 주입한다."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stopping: asyncio.Event | None = None
        self._queue: asyncio.Queue[RealtimeQuote] | None = None
        self._published = 0
        self._last_published_at: datetime | None = None
        self._last_error: str | None = None
        self._seen_keys: set[str] = set()

    def _ensure_loop_primitives(self) -> None:
        """pytest-asyncio 등 루프가 바뀌면 Queue/Event를 재생성."""

        self._stopping = asyncio.Event()
        self._queue = asyncio.Queue()

    def start(self) -> dict[str, Any]:
        settings = get_settings()
        if not bool(getattr(settings, "paper_price_feed_enabled", False)):
            return {
                "started": False,
                "reason": "PAPER_PRICE_FEED_DISABLED",
                **self.status(),
            }
        if self._task is not None and not self._task.done():
            return {"started": False, "reason": "ALREADY_RUNNING", **self.status()}
        self._ensure_loop_primitives()
        assert self._stopping is not None
        self._task = asyncio.create_task(
            self._run(),
            name="paper-price-feed",
        )
        return {"started": True, **self.status()}

    async def shutdown(self) -> None:
        if self._stopping is not None:
            self._stopping.set()
        task = self._task
        self._task = None
        if task is not None and not task.done():
            try:
                await asyncio.wait_for(task, timeout=3.0)
            except TimeoutError:
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=1.0)
                except (
                    asyncio.CancelledError,
                    TimeoutError,
                    Exception,
                ):  # noqa: BLE001
                    pass
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._seen_keys.clear()
        self._stopping = None
        self._queue = None

    async def inject_prices(
        self,
        *,
        exchange_code: str,
        symbol: str,
        prices: Sequence[Decimal | int | float | str],
        source_code: str = "PAPER_REPLAY",
    ) -> int:
        """결정적 가격 시퀀스 주입 (미래 데이터·LIVE WS 없음)."""

        if self._queue is None:
            self._ensure_loop_primitives()
        assert self._queue is not None

        count = 0
        base = datetime.now(timezone.utc)
        for idx, raw in enumerate(prices):
            price = Decimal(str(raw))
            if price <= 0:
                continue
            # 이벤트 시각을 증가시켜 MA 역순 차단·중복 fingerprint 완화
            from datetime import timedelta

            ts = base + timedelta(milliseconds=idx * 25)
            key = f"{exchange_code}|{symbol}|{price}|{idx}|{ts.isoformat()}"
            if key in self._seen_keys:
                continue
            self._seen_keys.add(key)
            quote = RealtimeQuote(
                exchange_code=str(exchange_code).upper(),
                symbol=str(symbol).upper(),
                event_type=MarketEventType.TRADE,
                trade_price=price,
                opening_price=None,
                high_price=None,
                low_price=None,
                previous_close_price=None,
                change_price=None,
                change_rate=None,
                accumulated_volume=None,
                trade_volume=Decimal("1"),
                event_time=ts,
                received_at=ts,
                source_code=source_code,
            )
            await self._queue.put(quote)
            count += 1
        return count

    async def publish_now(self, quote: RealtimeQuote) -> None:
        """즉시 Quote Bus + Manager 경로로 전달."""

        await realtime_manager.handle_quote(quote)
        self._published += 1
        self._last_published_at = datetime.now(timezone.utc)

    async def _run(self) -> None:
        settings = get_settings()
        interval = float(
            getattr(settings, "paper_price_feed_interval_seconds", 1.0)
        )
        assert self._stopping is not None and self._queue is not None
        stopping = self._stopping
        queue = self._queue
        while not stopping.is_set():
            try:
                try:
                    quote = await asyncio.wait_for(
                        queue.get(),
                        timeout=max(0.2, interval),
                    )
                except TimeoutError:
                    continue
                await self.publish_now(quote)
                queue.task_done()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self._last_error = type(exc).__name__
                logger.warning(
                    "paper_price_feed_error",
                    error=str(exc)[:200],
                )
                # 루프 바인딩 오류 시 busy-spin 방지
                await asyncio.sleep(0.5)

    def status(self) -> dict[str, Any]:
        settings = get_settings()
        running = self._task is not None and not self._task.done()
        return {
            "enabled": bool(
                getattr(settings, "paper_price_feed_enabled", False)
            ),
            "running": running,
            "queued": self._queue.qsize() if self._queue is not None else 0,
            "published": self._published,
            "last_published_at": (
                self._last_published_at.isoformat()
                if self._last_published_at
                else None
            ),
            "last_error": self._last_error,
        }


paper_price_feed = PaperPriceFeed()
