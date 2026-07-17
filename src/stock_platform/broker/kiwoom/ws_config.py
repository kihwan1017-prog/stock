from __future__ import annotations

import os
from dataclasses import dataclass


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
        use_mock = os.getenv(
            "KIWOOM_USE_MOCK", "true"
        ).lower() == "true"

        default_url = (
            "wss://mockapi.kiwoom.com:10000"
            if use_mock
            else "wss://api.kiwoom.com:10000"
        )

        return cls(
            url=os.getenv(
                "KIWOOM_WS_URL", default_url
            ),
            path=os.getenv(
                "KIWOOM_WS_PATH",
                "/api/dostk/websocket",
            ),
            service_type=os.getenv(
                "KIWOOM_WS_EXECUTION_TYPE", "00"
            ),
            reconnect_min_seconds=float(
                os.getenv(
                    "KIWOOM_WS_RECONNECT_MIN_SECONDS",
                    "1",
                )
            ),
            reconnect_max_seconds=float(
                os.getenv(
                    "KIWOOM_WS_RECONNECT_MAX_SECONDS",
                    "30",
                )
            ),
            ping_interval_seconds=float(
                os.getenv(
                    "KIWOOM_WS_PING_INTERVAL_SECONDS",
                    "20",
                )
            ),
            ping_timeout_seconds=float(
                os.getenv(
                    "KIWOOM_WS_PING_TIMEOUT_SECONDS",
                    "10",
                )
            ),
        )
