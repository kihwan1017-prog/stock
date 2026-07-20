from functools import lru_cache
from pathlib import Path
import logging
import secrets
from urllib.parse import quote_plus

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


ENV_FILE = Path(r"E:\StockTrading\secrets\stock-platform.env")
_SECRETS_ENV_HINT = r"E:\StockTrading\secrets\stock-platform.env"
_logger = logging.getLogger(__name__)

_DEV_APP_ENVS = frozenset({"local", "dev", "development"})
_PROD_APP_ENVS = frozenset({"prod", "production", "staging"})


def format_jwt_secret_missing_message() -> str:
    """JWT_SECRET 미설정 시 사용자에게 보여줄 안내 문구."""

    return (
        "JWT_SECRET 환경변수가 없습니다.\n"
        "\n"
        "다음 내용을\n"
        f"{_SECRETS_ENV_HINT}\n"
        "에 추가하세요.\n"
        "\n"
        "JWT_SECRET=xxxxxxxxxxxxxxxx\n"
        "JWT_ALGORITHM=HS256\n"
        "JWT_ACCESS_TOKEN_EXPIRE_MINUTES=60\n"
        "JWT_REFRESH_TOKEN_EXPIRE_DAYS=30\n"
        "\n"
        "개발(local)에서는 JWT_DEV_AUTO_SECRET=true 이면 "
        "기동 시 임시 Secret을 자동 생성합니다.\n"
        "운영(prod)에서는 반드시 JWT_SECRET을 설정하세요.\n"
        "템플릿: 프로젝트 stock-platform.env.example / .env.example"
    )


class Settings(BaseSettings):
    app_env: str = "local"
    app_name: str = "stock-platform"
    app_timezone: str = "Asia/Seoul"
    # STEP59 — 운영 로깅 / CORS
    log_level: str = "INFO"
    cors_allow_origins: str = (
        "http://localhost:3000,http://127.0.0.1:3000"
    )

    db_host: str
    db_port: int = 5432
    db_name: str
    db_user: str
    db_password: str
    # STEP58 — Connection Pool (운영 기본값)
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: float = 30.0
    db_pool_recycle: int = 1800
    db_pool_pre_ping: bool = True

    kiwoom_app_key: str = Field(default="")
    kiwoom_secret_key: str = Field(default="")
    kiwoom_use_mock: bool = True
    kiwoom_live_order_enabled: bool = False
    kiwoom_timeout_seconds: float = 10.0
    kiwoom_http_timeout_seconds: float = 10.0
    kiwoom_max_requests_per_second: int = 5
    kiwoom_account_number: str = Field(default="")
    # 모의(mock) WebSocket은 handshake 실패가 잦아 기본은 수동 시작
    kiwoom_recovery_start_ws: bool = False
    kiwoom_recovery_start_trading: bool = False
    kiwoom_recovery_start_scheduler: bool = True
    # 연속 실패 후 자동 재연결 중단 (0이면 무한 재시도)
    kiwoom_ws_max_consecutive_failures: int = 8

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
    # STEP54 — Telegram Ops
    telegram_ops_enabled: bool = False
    telegram_ops_poll_interval_seconds: float = 3.0
    telegram_allowed_chat_ids: str = ""
    telegram_notification_level: str = "INFO"
    # Telegram webhook Secret-Token (설정 시 헤더 검증 필수)
    telegram_webhook_secret: str = Field(default="")
    app_version: str = "1.1.0"
    slack_enabled: bool = False
    slack_webhook_url: str = Field(default="")
    discord_enabled: bool = False
    discord_webhook_url: str = Field(default="")

    # 관리 API 보호 (비어 있으면 로컬 개발 모드로 통과)
    # 스크립트/자동화용. Admin Web은 JWT 사용 (프론트에 Key를 두지 않음)
    admin_api_key: str = Field(default="")

    # JWT 인증 (Secret은 env 파일에만 — 코드/ NEXT_PUBLIC 금지)
    jwt_secret: str = Field(default="")
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 7
    # local/dev 에서만 허용. prod 에서는 무시되고 JWT_SECRET 필수
    jwt_dev_auto_secret: bool = True
    # 최초 관리자 시드 (사용자가 0명일 때만 생성)
    auth_bootstrap_admin_username: str = Field(default="")
    auth_bootstrap_admin_password: str = Field(default="")

    upbit_base_url: str = "https://api.upbit.com"
    upbit_timeout_seconds: float = 10.0
    upbit_max_requests_per_second: int = 8

    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3.5:4b"
    ollama_timeout_seconds: float = 120.0
    ollama_temperature: float = 0.2
    ollama_keep_alive: str = "10m"
    # STEP69 — 사용자 공시 AI 요약 (미설정 시 ollama_model 사용)
    ai_disclosure_summary_model: str = Field(default="")
    ai_disclosure_summary_prompt_version: str = "v1"
    ai_disclosure_summary_cooldown_seconds: int = 30
    ai_disclosure_summary_max_per_minute: int = 10

    # STEP70 — 사용자 AI 종목 추천
    ai_recommendation_model: str = Field(default="")
    ai_recommendation_prompt_version: str = "v1"
    ai_recommendation_cooldown_seconds: int = 60
    ai_recommendation_max_per_minute: int = 5

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
    # STEP66 — 장후 자산 스냅샷 (기본 15:40 KST)
    scheduler_equity_snapshot_hour: int = 15
    scheduler_equity_snapshot_minute: int = 40

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

    # STEP53 — Position Exit Monitor (Polling)
    position_exit_monitor_enabled: bool = True
    position_exit_monitor_interval_seconds: float = 5.0
    position_exit_stop_loss_ratio: float = 0.05
    position_exit_take_profit_ratio: float = 0.10
    position_exit_trailing_stop_ratio: float | None = 0.03
    position_exit_relative_loss_ratio: float | None = 0.08

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def resolved_disclosure_summary_model(self) -> str:
        """사용자 공시 요약 모델 — 전용 설정 우선, 없으면 ollama_model."""

        custom = (self.ai_disclosure_summary_model or "").strip()
        return custom or self.ollama_model

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

    @property
    def is_production_env(self) -> bool:
        return self.app_env.strip().lower() in _PROD_APP_ENVS

    @property
    def is_dev_env(self) -> bool:
        return self.app_env.strip().lower() in _DEV_APP_ENVS

    def ensure_jwt_secret(self) -> None:
        """
        JWT_SECRET 보장.
        - 운영: 미설정 시 친절한 ValueError로 기동 중단
        - 개발(local/dev): JWT_DEV_AUTO_SECRET=true 이면 임시 Secret 생성
        """

        if self.jwt_secret.strip():
            return

        can_auto = (
            self.is_dev_env
            and self.jwt_dev_auto_secret
            and not self.is_production_env
        )
        if can_auto:
            generated = secrets.token_urlsafe(48)
            self.jwt_secret = generated
            _logger.warning(
                "JWT_SECRET 미설정 — 개발용 임시 Secret을 생성했습니다. "
                "재시작마다 달라지므로 로그인 토큰이 무효화됩니다. "
                "고정 Secret이 필요하면 %s 에 JWT_SECRET 을 설정하세요.",
                _SECRETS_ENV_HINT,
            )
            return

        raise ValueError(format_jwt_secret_missing_message())

    def ensure_admin_api_key(self) -> None:
        """
        운영/스테이징: ADMIN_API_KEY 필수 (DEV_OPEN 금지).
        로컬/개발: 비어 있어도 기동 허용 — 단 require_admin 은 JWT admin 필요.
        """

        if not self.is_production_env:
            return
        if self.admin_api_key.strip():
            return
        raise ValueError(
            "운영 환경(APP_ENV=prod|production|staging)에서는 "
            "ADMIN_API_KEY 가 필수입니다. DEV_OPEN 은 제거되었습니다."
        )

    def validate_startup(self) -> None:
        """서버 기동 시 필수 설정을 검증한다."""

        if self.kiwoom_live_order_enabled and self.kiwoom_use_mock:
            raise ValueError(
                "KIWOOM_LIVE_ORDER_ENABLED cannot be true "
                "when KIWOOM_USE_MOCK is true"
            )
        self.ensure_jwt_secret()
        self.ensure_admin_api_key()
        algo = (self.jwt_algorithm or "HS256").strip().upper()
        if algo not in {"HS256"}:
            raise ValueError(
                "JWT_ALGORITHM 은 HS256 만 허용됩니다."
            )
        self.jwt_algorithm = algo
        if self.is_production_env:
            origins = [
                item.strip()
                for item in self.cors_allow_origins.split(",")
                if item.strip()
            ]
            if not origins:
                raise ValueError(
                    "운영 환경에서는 CORS_ALLOW_ORIGINS 가 필수입니다."
                )
            if all(
                "localhost" in origin or "127.0.0.1" in origin
                for origin in origins
            ):
                raise ValueError(
                    "운영 환경 CORS_ALLOW_ORIGINS 에 localhost 만 있으면 "
                    "안 됩니다. 실제 Admin Origin을 설정하세요."
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
