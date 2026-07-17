from __future__ import annotations

from dataclasses import dataclass

from stock_platform.common.settings import get_settings


@dataclass(frozen=True, slots=True)
class KiwoomOrderConfig:
    base_url: str
    app_key: str
    secret_key: str
    use_mock: bool
    live_order_enabled: bool
    timeout_seconds: float = 10.0

    @classmethod
    def from_env(cls) -> "KiwoomOrderConfig":
        settings = get_settings()
        return cls(
            base_url=settings.kiwoom_base_url,
            app_key=settings.kiwoom_app_key,
            secret_key=settings.kiwoom_secret_key,
            use_mock=settings.kiwoom_use_mock,
            live_order_enabled=settings.kiwoom_live_order_enabled,
            timeout_seconds=settings.kiwoom_http_timeout_seconds,
        )


@dataclass(frozen=True, slots=True)
class KiwoomBrokerConfig:
    """계좌 조회·인증·WebSocket 등 공통 키움 REST 설정."""

    app_key: str
    secret_key: str
    use_mock: bool = True
    live_order_enabled: bool = False
    timeout_seconds: float = 10.0
    max_retries: int = 2
    requests_per_second: int = 5

    @classmethod
    def from_settings(cls) -> "KiwoomBrokerConfig":
        settings = get_settings()
        return cls(
            app_key=settings.kiwoom_app_key,
            secret_key=settings.kiwoom_secret_key,
            use_mock=settings.kiwoom_use_mock,
            live_order_enabled=settings.kiwoom_live_order_enabled,
            timeout_seconds=settings.kiwoom_http_timeout_seconds,
            requests_per_second=(
                settings.kiwoom_max_requests_per_second
            ),
        )

    @property
    def base_url(self) -> str:
        if self.use_mock:
            return "https://mockapi.kiwoom.com"
        return "https://api.kiwoom.com"

    def validate(self) -> None:
        if not self.app_key.strip():
            raise ValueError("KIWOOM_APP_KEY is required")
        if not self.secret_key.strip():
            raise ValueError("KIWOOM_SECRET_KEY is required")
        if self.live_order_enabled and self.use_mock:
            raise ValueError(
                "live_order_enabled cannot be true when use_mock is true"
            )
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        if self.max_retries < 0:
            raise ValueError("max_retries must be zero or greater")
        if self.requests_per_second <= 0:
            raise ValueError(
                "requests_per_second must be greater than zero"
            )
