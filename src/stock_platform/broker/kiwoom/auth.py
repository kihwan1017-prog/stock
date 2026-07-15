import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import httpx
from stock_platform.broker.kiwoom.config import KiwoomBrokerConfig

@dataclass(frozen=True, slots=True)
class KiwoomAccessToken:
    token: str
    token_type: str
    expires_at: datetime

    def is_expiring(self, margin_seconds: int = 120) -> bool:
        return self.expires_at <= datetime.now(timezone.utc) + timedelta(seconds=margin_seconds)

class KiwoomTokenProvider:
    def __init__(self, config: KiwoomBrokerConfig, client: httpx.AsyncClient | None = None):
        config.validate()
        self.config, self.client = config, client
        self.token: KiwoomAccessToken | None = None
        self.lock = asyncio.Lock()

    async def get_token(self) -> KiwoomAccessToken:
        async with self.lock:
            if self.token and not self.token.is_expiring():
                return self.token
            self.token = await self._issue()
            return self.token

    async def invalidate(self) -> None:
        async with self.lock:
            self.token = None

    async def _issue(self) -> KiwoomAccessToken:
        owns = self.client is None
        client = self.client or httpx.AsyncClient(timeout=self.config.timeout_seconds)
        try:
            r = await client.post(
                self.config.base_url + "/oauth2/token",
                headers={"Content-Type": "application/json;charset=UTF-8"},
                json={"grant_type": "client_credentials", "appkey": self.config.app_key, "secretkey": self.config.secret_key},
            )
            r.raise_for_status()
            data = r.json()
        finally:
            if owns:
                await client.aclose()
        if int(data.get("return_code", 0)) != 0:
            raise RuntimeError(data.get("return_msg", "Kiwoom token error"))
        raw = str(data.get("expires_dt", ""))
        try:
            expires = datetime.strptime(raw, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        except ValueError:
            expires = datetime.now(timezone.utc) + timedelta(hours=23)
        return KiwoomAccessToken(str(data["token"]), str(data.get("token_type", "bearer")), expires)
