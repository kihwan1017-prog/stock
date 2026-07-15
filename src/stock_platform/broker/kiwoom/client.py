import asyncio
from collections import deque
from typing import Any
import httpx
from stock_platform.broker.kiwoom.auth import KiwoomTokenProvider
from stock_platform.broker.kiwoom.config import KiwoomBrokerConfig

class KiwoomRestError(RuntimeError):
    pass

class KiwoomRestClient:
    def __init__(self, config: KiwoomBrokerConfig, token_provider: KiwoomTokenProvider, client: httpx.AsyncClient | None = None):
        self.config, self.tokens = config, token_provider
        self.client = client or httpx.AsyncClient(base_url=config.base_url, timeout=config.timeout_seconds)
        self.owns_client = client is None
        self.times, self.lock = deque(), asyncio.Lock()

    async def close(self):
        if self.owns_client:
            await self.client.aclose()

    async def post(self, path: str, api_id: str, body: dict[str, Any]) -> dict[str, Any]:
        last = None
        for attempt in range(self.config.max_retries + 1):
            await self._limit()
            token = await self.tokens.get_token()
            try:
                r = await self.client.post(path, headers={
                    "Authorization": f"Bearer {token.token}",
                    "Content-Type": "application/json;charset=UTF-8",
                    "api-id": api_id, "cont-yn": "N", "next-key": "",
                }, json=body)
                if r.status_code == 401:
                    await self.tokens.invalidate()
                r.raise_for_status()
                data = r.json()
                if int(data.get("return_code", 0)) != 0:
                    raise KiwoomRestError(data.get("return_msg", "Kiwoom API error"))
                return data
            except (httpx.HTTPError, KiwoomRestError) as exc:
                last = exc
                if attempt < self.config.max_retries:
                    await asyncio.sleep(min(2 ** attempt, 5))
        raise KiwoomRestError(f"Kiwoom request failed: {last}")

    async def _limit(self):
        async with self.lock:
            loop, now = asyncio.get_running_loop(), asyncio.get_running_loop().time()
            while self.times and now - self.times[0] >= 1:
                self.times.popleft()
            if len(self.times) >= self.config.requests_per_second:
                await asyncio.sleep(max(1 - (now - self.times[0]), 0))
            self.times.append(loop.time())
