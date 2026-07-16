from dataclasses import dataclass
from datetime import datetime
import httpx
from stock_platform.broker.exceptions import BrokerAuthenticationError
from stock_platform.broker.kiwoom.config import KiwoomOrderConfig

@dataclass(frozen=True, slots=True)
class KiwoomAccessToken:
    token: str
    token_type: str
    expires_at: datetime

class KiwoomTokenClient:
    def __init__(self, config: KiwoomOrderConfig, client: httpx.Client | None = None):
        self.config = config
        self.client = client or httpx.Client(timeout=config.timeout_seconds)

    def issue(self) -> KiwoomAccessToken:
        try:
            response = self.client.post(
                f"{self.config.base_url}/oauth2/token",
                json={
                    "grant_type": "client_credentials",
                    "appkey": self.config.app_key,
                    "secretkey": self.config.secret_key,
                },
                headers={"Content-Type": "application/json;charset=UTF-8"},
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise BrokerAuthenticationError(str(exc)) from exc

        if int(payload.get("return_code", -1)) != 0 or not payload.get("token"):
            raise BrokerAuthenticationError(
                payload.get("return_msg", "Kiwoom token issuance failed")
            )

        return KiwoomAccessToken(
            token=payload["token"],
            token_type=payload.get("token_type", "bearer"),
            expires_at=datetime.strptime(payload["expires_dt"], "%Y%m%d%H%M%S"),
        )
