from dataclasses import dataclass
from datetime import datetime, timezone

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
        # OAuth는 HTML 랜딩(start.html)으로의 302를 따라가면 안 됨
        self.client = client or httpx.Client(
            timeout=config.timeout_seconds,
            follow_redirects=False,
        )

    def issue(self) -> KiwoomAccessToken:
        url = f"{self.config.base_url.rstrip('/')}/oauth2/token"
        env = "mock" if self.config.use_mock else "live"
        try:
            response = self.client.post(
                url,
                json={
                    "grant_type": "client_credentials",
                    "appkey": self.config.app_key,
                    "secretkey": self.config.secret_key,
                },
                headers={
                    "Content-Type": "application/json;charset=UTF-8",
                    # au10001 — 키움 토큰 발급 TR (일부 게이트웨이에서 요구)
                    "api-id": "au10001",
                },
            )
        except Exception as exc:
            raise BrokerAuthenticationError(str(exc)) from exc

        location = str(response.headers.get("location") or "")
        if response.status_code in {301, 302, 303, 307, 308}:
            raise BrokerAuthenticationError(
                "KIWOOM_OAUTH_GATEWAY_REDIRECT "
                f"env={env} status={response.status_code} "
                f"url={url} location={location or 'none'}"
            )

        try:
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise BrokerAuthenticationError(str(exc)) from exc

        if int(payload.get("return_code", -1)) != 0 or not payload.get("token"):
            raise BrokerAuthenticationError(
                payload.get("return_msg", "Kiwoom token issuance failed")
            )

        # expires_dt는 키움 서버 로컬시각 문자열 — UTC로 정규화해 캐시 비교에 사용
        expires_at = datetime.strptime(
            payload["expires_dt"],
            "%Y%m%d%H%M%S",
        ).replace(tzinfo=timezone.utc)

        return KiwoomAccessToken(
            token=payload["token"],
            token_type=payload.get("token_type", "bearer"),
            expires_at=expires_at,
        )
