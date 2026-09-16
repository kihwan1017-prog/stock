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


@dataclass(frozen=True, slots=True)
class KiwoomMarketWebSocketConfig:
    """시장 시세 WS 전용. 주문체결 type=00 설정과 분리."""

    url: str
    path: str
    service_type: str = "0B"
    reconnect_min_seconds: float = 1.0
    reconnect_max_seconds: float = 30.0
    ping_interval_seconds: float = 20.0
    ping_timeout_seconds: float = 10.0
    environment: str = "MOCK"

    @property
    def endpoint(self) -> str:
        return f"{self.url.rstrip('/')}/{self.path.lstrip('/')}"

    @classmethod
    def from_settings(cls) -> "KiwoomMarketWebSocketConfig":
        settings = get_settings()
        is_mock = bool(settings.kiwoom_market_data_is_mock)
        return cls(
            url=settings.kiwoom_market_ws_url_resolved,
            path=settings.kiwoom_ws_path,
            service_type=(
                str(settings.kiwoom_ws_market_type or "0B").strip()
                or "0B"
            ),
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
            environment="MOCK" if is_mock else "REAL",
        )

    @classmethod
    def for_real_host(cls) -> "KiwoomMarketWebSocketConfig":
        """UBA REAL credential probe용. KIWOOM_USE_MOCK을 바꾸지 않는다."""

        settings = get_settings()
        cfg = cls.from_settings()
        return cls(
            url="wss://api.kiwoom.com:10000",
            path=settings.kiwoom_ws_path,
            service_type=cfg.service_type,
            reconnect_min_seconds=cfg.reconnect_min_seconds,
            reconnect_max_seconds=cfg.reconnect_max_seconds,
            ping_interval_seconds=cfg.ping_interval_seconds,
            ping_timeout_seconds=cfg.ping_timeout_seconds,
            environment="REAL",
        )
