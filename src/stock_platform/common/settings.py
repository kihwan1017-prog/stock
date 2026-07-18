from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


ENV_FILE = Path(r"E:\StockTrading\secrets\stock-platform.env")


class Settings(BaseSettings):
    app_env: str = "local"
    app_name: str = "stock-platform"
    app_timezone: str = "Asia/Seoul"

    db_host: str
    db_port: int = 5432
    db_name: str
    db_user: str
    db_password: str

    kiwoom_app_key: str = Field(default="")
    kiwoom_secret_key: str = Field(default="")
    kiwoom_use_mock: bool = True
    kiwoom_live_order_enabled: bool = False
    kiwoom_timeout_seconds: float = 10.0
    kiwoom_http_timeout_seconds: float = 10.0
    kiwoom_max_requests_per_second: int = 5
    kiwoom_account_number: str = Field(default="")
    kiwoom_recovery_start_ws: bool = True
    kiwoom_recovery_start_trading: bool = False
    kiwoom_recovery_start_scheduler: bool = True

    # 키움 WebSocket (시세/주문체결)
    kiwoom_ws_url: str = Field(default="")
    kiwoom_ws_path: str = "/api/dostk/websocket"
    kiwoom_ws_execution_type: str = "00"
    kiwoom_ws_reconnect_min_seconds: float = 1.0
    kiwoom_ws_reconnect_max_seconds: float = 30.0
    kiwoom_ws_ping_interval_seconds: float = 20.0
    kiwoom_ws_ping_timeout_seconds: float = 10.0
    kiwoom_order_ws_url: str = Field(default="")
    kiwoom_order_ws_path: str = Field(default="")
    kiwoom_order_ws_subscribe_json: str = Field(default="")

    realtime_strategy_market_code: str = "KRX"
    realtime_strategy_symbol: str = Field(default="")
    strategy_auto_deploy_enabled: bool = False
    paper_strategy_auto_stop_enabled: bool = False

    # 알림 (선택)
    telegram_enabled: bool = False
    telegram_bot_token: str = Field(default="")
    telegram_chat_id: str = Field(default="")
    slack_enabled: bool = False
    slack_webhook_url: str = Field(default="")
    discord_enabled: bool = False
    discord_webhook_url: str = Field(default="")

    # 관리 API 보호 (비어 있으면 로컬 개발 모드로 통과)
    admin_api_key: str = Field(default="")

    upbit_base_url: str = "https://api.upbit.com"
    upbit_timeout_seconds: float = 10.0
    upbit_max_requests_per_second: int = 8

    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3.5:4b"
    ollama_timeout_seconds: float = 120.0
    ollama_temperature: float = 0.2
    ollama_keep_alive: str = "10m"

    dart_api_key: str = Field(default="")
    dart_base_url: str = "https://opendart.fss.or.kr/api"
    dart_timeout_seconds: float = 20.0

    naver_client_id: str = Field(default="")
    naver_client_secret: str = Field(default="")
    naver_news_base_url: str = (
        "https://openapi.naver.com/v1/search/news.json"
    )
    naver_news_timeout_seconds: float = 15.0

    scheduler_enabled: bool = True
    scheduler_timezone: str = "Asia/Seoul"
    scheduler_candidate_hour: int = 16
    scheduler_candidate_minute: int = 10
    scheduler_ai_hour: int = 16
    scheduler_ai_minute: int = 30
    scheduler_position_hour: int = 17
    scheduler_position_minute: int = 0

    scheduler_exchange_code: str = "KRX"
    scheduler_candidate_limit: int = 30
    scheduler_minimum_score: float = 50.0
    scheduler_ai_limit: int = 10
    scheduler_position_limit: int = 5
    scheduler_policy_id: int = 1
    scheduler_portfolio_value: float = 10000000
    scheduler_available_cash: float = 5000000
    scheduler_minimum_ai_score: float = 70.0
    scheduler_minimum_confidence: float = 0.5

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def database_url(self) -> str:
        user = quote_plus(self.db_user)
        password = quote_plus(self.db_password)
        return (
            f"postgresql+psycopg://{user}:{password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def kiwoom_base_url(self) -> str:
        return (
            "https://mockapi.kiwoom.com"
            if self.kiwoom_use_mock
            else "https://api.kiwoom.com"
        )

    @property
    def kiwoom_ws_default_url(self) -> str:
        if self.kiwoom_use_mock:
            return "wss://mockapi.kiwoom.com:10000"
        return "wss://api.kiwoom.com:10000"

    @property
    def kiwoom_ws_url_resolved(self) -> str:
        return self.kiwoom_ws_url.strip() or self.kiwoom_ws_default_url

    @property
    def kiwoom_order_ws_url_resolved(self) -> str:
        return (
            self.kiwoom_order_ws_url.strip()
            or self.kiwoom_ws_default_url
        )

    @property
    def realtime_strategy_symbol_or_none(self) -> str | None:
        symbol = self.realtime_strategy_symbol.strip()
        return symbol or None

    def validate_startup(self) -> None:
        """서버 기동 시 필수 설정을 검증한다."""

        if self.kiwoom_live_order_enabled and self.kiwoom_use_mock:
            raise ValueError(
                "KIWOOM_LIVE_ORDER_ENABLED cannot be true "
                "when KIWOOM_USE_MOCK is true"
            )

    def validate_kiwoom_credentials(self) -> None:
        missing: list[str] = []
        if not self.kiwoom_app_key.strip():
            missing.append("KIWOOM_APP_KEY")
        if not self.kiwoom_secret_key.strip():
            missing.append("KIWOOM_SECRET_KEY")
        if missing:
            raise ValueError(
                f"Missing Kiwoom credentials: {', '.join(missing)}"
            )

    def validate_dart_credentials(self) -> None:
        if not self.dart_api_key.strip():
            raise ValueError("Missing DART_API_KEY")

    def validate_naver_credentials(self) -> None:
        missing: list[str] = []
        if not self.naver_client_id.strip():
            missing.append("NAVER_CLIENT_ID")
        if not self.naver_client_secret.strip():
            missing.append("NAVER_CLIENT_SECRET")
        if missing:
            raise ValueError(
                f"Missing Naver credentials: {', '.join(missing)}"
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
