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
    kiwoom_timeout_seconds: float = 10.0
    kiwoom_max_requests_per_second: int = 5

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
