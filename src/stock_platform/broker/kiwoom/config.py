from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class KiwoomBrokerConfig:
    app_key: str
    secret_key: str
    use_mock: bool = True
    timeout_seconds: float = 15.0
    max_retries: int = 2
    requests_per_second: int = 4
    live_order_enabled: bool = False

    @property
    def base_url(self) -> str:
        return "https://mockapi.kiwoom.com" if self.use_mock else "https://api.kiwoom.com"

    def validate(self) -> None:
        missing = [n for n, v in {
            "KIWOOM_APP_KEY": self.app_key,
            "KIWOOM_SECRET_KEY": self.secret_key,
        }.items() if not v.strip()]
        if missing:
            raise ValueError("Missing Kiwoom credentials: " + ", ".join(missing))
