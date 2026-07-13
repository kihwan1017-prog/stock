from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


ENV_FILE = Path(r"E:\StockTrading\secrets\stock-platform.env")


class Settings(BaseSettings):
    """Application settings loaded from the external secrets file."""

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
        if self.kiwoom_use_mock:
            return "https://mockapi.kiwoom.com"

        return "https://api.kiwoom.com"

    def validate_kiwoom_credentials(self) -> None:
        missing: list[str] = []

        if not self.kiwoom_app_key.strip():
            missing.append("KIWOOM_APP_KEY")

        if not self.kiwoom_secret_key.strip():
            missing.append("KIWOOM_SECRET_KEY")

        if missing:
            joined = ", ".join(missing)
            raise ValueError(f"Missing Kiwoom credentials: {joined}")


@lru_cache
def get_settings() -> Settings:
    return Settings()
