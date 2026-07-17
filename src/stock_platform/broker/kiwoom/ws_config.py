from __future__ import annotations

from dataclasses import dataclass

from stock_platform.common.settings import get_settings


@dataclass(frozen=True, slots=True)
class KiwoomWebSocketConfig:
    url: str
    path: str
    service_type: str = "00"
    reconnect_min_seconds: float = 1.0
    reconnect_max_seconds: float = 30.0
    ping_interval_seconds: float = 20.0
    ping_timeout_seconds: float = 10.0

    @property
    def endpoint(self) -> str:
        return f"{self.url.rstrip('/')}/{self.path.lstrip('/')}"

    @classmethod
    def from_env(cls) -> "KiwoomWebSocketConfig":
        settings = get_settings()
        return cls(
            url=settings.kiwoom_ws_url_resolved,
            path=settings.kiwoom_ws_path,
            service_type=settings.kiwoom_ws_execution_type,
            reconnect_min_seconds=(
                settings.kiwoom_ws_reconnect_min_seconds
            ),
            reconnect_max_seconds=(
                settings.kiwoom_ws_reconnect_max_seconds
            ),
            ping_interval_seconds=(
                settings.kiwoom_ws_ping_interval_seconds
            ),
            ping_timeout_seconds=(
                settings.kiwoom_ws_ping_timeout_seconds
            ),
        )
