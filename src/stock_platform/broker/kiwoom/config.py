from dataclasses import dataclass
import os

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
        use_mock = os.getenv("KIWOOM_USE_MOCK", "true").lower() == "true"
        return cls(
            base_url=(
                "https://mockapi.kiwoom.com"
                if use_mock
                else "https://api.kiwoom.com"
            ),
            app_key=os.environ["KIWOOM_APP_KEY"],
            secret_key=os.environ["KIWOOM_SECRET_KEY"],
            use_mock=use_mock,
            live_order_enabled=(
                os.getenv("KIWOOM_LIVE_ORDER_ENABLED", "false").lower()
                == "true"
            ),
            timeout_seconds=float(
                os.getenv("KIWOOM_HTTP_TIMEOUT_SECONDS", "10")
            ),
        )
