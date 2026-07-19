from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


SettingValueType = Literal["string", "int", "float", "bool"]
SettingCategory = Literal[
    "system",
    "ai",
    "risk",
    "scheduler",
    "trading",
    "environment",
]

MASKED_VALUE = "********"


@dataclass(frozen=True, slots=True)
class SettingDefinition:
    key: str
    category: SettingCategory
    value_type: SettingValueType
    description: str
    is_secret: bool = False
    env_attr: str | None = None
    default: str = ""
    min_value: float | None = None
    max_value: float | None = None
    allowed_values: tuple[str, ...] | None = None


# DB에서 관리하는 설정 카탈로그 (env 부트스트랩 제외: db_*, jwt_secret, admin_api_key)
SETTING_DEFINITIONS: tuple[SettingDefinition, ...] = (
    # system
    SettingDefinition(
        "app_env",
        "system",
        "string",
        "애플리케이션 환경",
        env_attr="app_env",
        default="local",
        allowed_values=("local", "dev", "staging", "prod"),
    ),
    SettingDefinition(
        "app_name",
        "system",
        "string",
        "애플리케이션 이름",
        env_attr="app_name",
        default="stock-platform",
    ),
    SettingDefinition(
        "app_timezone",
        "system",
        "string",
        "기본 타임존",
        env_attr="app_timezone",
        default="Asia/Seoul",
    ),
    SettingDefinition(
        "jwt_access_token_expire_minutes",
        "system",
        "int",
        "Access Token 만료(분)",
        env_attr="jwt_access_token_expire_minutes",
        default="30",
        min_value=5,
        max_value=1440,
    ),
    SettingDefinition(
        "jwt_refresh_token_expire_days",
        "system",
        "int",
        "Refresh Token 만료(일)",
        env_attr="jwt_refresh_token_expire_days",
        default="7",
        min_value=1,
        max_value=90,
    ),
    # ai
    SettingDefinition(
        "ollama_base_url",
        "ai",
        "string",
        "Ollama Base URL",
        env_attr="ollama_base_url",
        default="http://127.0.0.1:11434",
    ),
    SettingDefinition(
        "ollama_model",
        "ai",
        "string",
        "기본 Ollama 모델",
        env_attr="ollama_model",
        default="qwen3.5:4b",
    ),
    SettingDefinition(
        "ollama_timeout_seconds",
        "ai",
        "float",
        "Ollama 타임아웃(초)",
        env_attr="ollama_timeout_seconds",
        default="120",
        min_value=5,
        max_value=600,
    ),
    SettingDefinition(
        "ollama_temperature",
        "ai",
        "float",
        "Ollama temperature",
        env_attr="ollama_temperature",
        default="0.2",
        min_value=0,
        max_value=2,
    ),
    SettingDefinition(
        "ollama_keep_alive",
        "ai",
        "string",
        "Ollama keep_alive",
        env_attr="ollama_keep_alive",
        default="10m",
    ),
    # risk (DB 전용 운영 파라미터)
    SettingDefinition(
        "risk_max_daily_loss_pct",
        "risk",
        "float",
        "일일 최대 손실 비율(%)",
        default="5",
        min_value=0.1,
        max_value=100,
    ),
    SettingDefinition(
        "risk_max_open_positions",
        "risk",
        "int",
        "최대 보유 포지션 수",
        default="10",
        min_value=1,
        max_value=200,
    ),
    SettingDefinition(
        "risk_max_order_amount",
        "risk",
        "float",
        "주문 1건 최대 금액",
        default="5000000",
        min_value=1000,
        max_value=1_000_000_000,
    ),
    SettingDefinition(
        "risk_require_kill_switch_reason",
        "risk",
        "bool",
        "Kill Switch 사유 필수 여부",
        default="true",
    ),
    # scheduler
    SettingDefinition(
        "scheduler_enabled",
        "scheduler",
        "bool",
        "스케줄러 활성화",
        env_attr="scheduler_enabled",
        default="true",
    ),
    SettingDefinition(
        "scheduler_timezone",
        "scheduler",
        "string",
        "스케줄러 타임존",
        env_attr="scheduler_timezone",
        default="Asia/Seoul",
    ),
    SettingDefinition(
        "scheduler_candidate_hour",
        "scheduler",
        "int",
        "후보 스크리닝 시(시)",
        env_attr="scheduler_candidate_hour",
        default="16",
        min_value=0,
        max_value=23,
    ),
    SettingDefinition(
        "scheduler_candidate_minute",
        "scheduler",
        "int",
        "후보 스크리닝 시(분)",
        env_attr="scheduler_candidate_minute",
        default="10",
        min_value=0,
        max_value=59,
    ),
    SettingDefinition(
        "scheduler_ai_hour",
        "scheduler",
        "int",
        "AI 분석 시(시)",
        env_attr="scheduler_ai_hour",
        default="16",
        min_value=0,
        max_value=23,
    ),
    SettingDefinition(
        "scheduler_ai_minute",
        "scheduler",
        "int",
        "AI 분석 시(분)",
        env_attr="scheduler_ai_minute",
        default="30",
        min_value=0,
        max_value=59,
    ),
    SettingDefinition(
        "scheduler_position_hour",
        "scheduler",
        "int",
        "포지션 계획 시(시)",
        env_attr="scheduler_position_hour",
        default="17",
        min_value=0,
        max_value=23,
    ),
    SettingDefinition(
        "scheduler_position_minute",
        "scheduler",
        "int",
        "포지션 계획 시(분)",
        env_attr="scheduler_position_minute",
        default="0",
        min_value=0,
        max_value=59,
    ),
    SettingDefinition(
        "scheduler_exchange_code",
        "scheduler",
        "string",
        "스케줄 대상 거래소",
        env_attr="scheduler_exchange_code",
        default="KRX",
    ),
    SettingDefinition(
        "scheduler_candidate_limit",
        "scheduler",
        "int",
        "후보 상위 N",
        env_attr="scheduler_candidate_limit",
        default="30",
        min_value=1,
        max_value=500,
    ),
    SettingDefinition(
        "scheduler_minimum_score",
        "scheduler",
        "float",
        "후보 최소 점수",
        env_attr="scheduler_minimum_score",
        default="50",
        min_value=0,
        max_value=100,
    ),
    SettingDefinition(
        "scheduler_ai_limit",
        "scheduler",
        "int",
        "AI 분석 상위 N",
        env_attr="scheduler_ai_limit",
        default="10",
        min_value=1,
        max_value=100,
    ),
    SettingDefinition(
        "scheduler_position_limit",
        "scheduler",
        "int",
        "포지션 계획 상위 N",
        env_attr="scheduler_position_limit",
        default="5",
        min_value=1,
        max_value=50,
    ),
    SettingDefinition(
        "scheduler_policy_id",
        "scheduler",
        "int",
        "기본 Risk Policy ID",
        env_attr="scheduler_policy_id",
        default="1",
        min_value=1,
    ),
    SettingDefinition(
        "scheduler_portfolio_value",
        "scheduler",
        "float",
        "스케줄 포트폴리오 가치",
        env_attr="scheduler_portfolio_value",
        default="10000000",
        min_value=0,
    ),
    SettingDefinition(
        "scheduler_available_cash",
        "scheduler",
        "float",
        "스케줄 가용 현금",
        env_attr="scheduler_available_cash",
        default="5000000",
        min_value=0,
    ),
    SettingDefinition(
        "scheduler_minimum_ai_score",
        "scheduler",
        "float",
        "AI 최소 점수",
        env_attr="scheduler_minimum_ai_score",
        default="70",
        min_value=0,
        max_value=100,
    ),
    SettingDefinition(
        "scheduler_minimum_confidence",
        "scheduler",
        "float",
        "AI 최소 confidence",
        env_attr="scheduler_minimum_confidence",
        default="0.5",
        min_value=0,
        max_value=1,
    ),
    # trading
    SettingDefinition(
        "kiwoom_use_mock",
        "trading",
        "bool",
        "키움 Mock 사용",
        env_attr="kiwoom_use_mock",
        default="true",
    ),
    SettingDefinition(
        "kiwoom_live_order_enabled",
        "trading",
        "bool",
        "키움 실주문 허용",
        env_attr="kiwoom_live_order_enabled",
        default="false",
    ),
    SettingDefinition(
        "kiwoom_app_key",
        "trading",
        "string",
        "키움 App Key",
        is_secret=True,
        env_attr="kiwoom_app_key",
    ),
    SettingDefinition(
        "kiwoom_secret_key",
        "trading",
        "string",
        "키움 Secret Key",
        is_secret=True,
        env_attr="kiwoom_secret_key",
    ),
    SettingDefinition(
        "kiwoom_account_number",
        "trading",
        "string",
        "키움 계좌번호",
        is_secret=True,
        env_attr="kiwoom_account_number",
    ),
    SettingDefinition(
        "kiwoom_timeout_seconds",
        "trading",
        "float",
        "키움 API 타임아웃",
        env_attr="kiwoom_timeout_seconds",
        default="10",
        min_value=1,
        max_value=120,
    ),
    SettingDefinition(
        "kiwoom_max_requests_per_second",
        "trading",
        "int",
        "키움 RPS 제한",
        env_attr="kiwoom_max_requests_per_second",
        default="5",
        min_value=1,
        max_value=50,
    ),
    SettingDefinition(
        "realtime_strategy_market_code",
        "trading",
        "string",
        "실시간 전략 시장",
        env_attr="realtime_strategy_market_code",
        default="KRX",
    ),
    SettingDefinition(
        "realtime_strategy_symbol",
        "trading",
        "string",
        "실시간 전략 심볼",
        env_attr="realtime_strategy_symbol",
        default="",
    ),
    SettingDefinition(
        "strategy_auto_deploy_enabled",
        "trading",
        "bool",
        "전략 자동 배포",
        env_attr="strategy_auto_deploy_enabled",
        default="false",
    ),
    SettingDefinition(
        "paper_strategy_auto_stop_enabled",
        "trading",
        "bool",
        "Paper 전략 자동 중지",
        env_attr="paper_strategy_auto_stop_enabled",
        default="false",
    ),
    # environment / integration
    SettingDefinition(
        "upbit_base_url",
        "environment",
        "string",
        "Upbit Base URL",
        env_attr="upbit_base_url",
        default="https://api.upbit.com",
    ),
    SettingDefinition(
        "upbit_timeout_seconds",
        "environment",
        "float",
        "Upbit 타임아웃",
        env_attr="upbit_timeout_seconds",
        default="10",
        min_value=1,
        max_value=60,
    ),
    SettingDefinition(
        "dart_api_key",
        "environment",
        "string",
        "DART API Key",
        is_secret=True,
        env_attr="dart_api_key",
    ),
    SettingDefinition(
        "dart_base_url",
        "environment",
        "string",
        "DART Base URL",
        env_attr="dart_base_url",
        default="https://opendart.fss.or.kr/api",
    ),
    SettingDefinition(
        "naver_client_id",
        "environment",
        "string",
        "Naver Client ID",
        is_secret=True,
        env_attr="naver_client_id",
    ),
    SettingDefinition(
        "naver_client_secret",
        "environment",
        "string",
        "Naver Client Secret",
        is_secret=True,
        env_attr="naver_client_secret",
    ),
    SettingDefinition(
        "telegram_enabled",
        "environment",
        "bool",
        "Telegram 알림 사용",
        env_attr="telegram_enabled",
        default="false",
    ),
    SettingDefinition(
        "telegram_bot_token",
        "environment",
        "string",
        "Telegram Bot Token",
        is_secret=True,
        env_attr="telegram_bot_token",
    ),
    SettingDefinition(
        "telegram_chat_id",
        "environment",
        "string",
        "Telegram Chat ID",
        env_attr="telegram_chat_id",
    ),
    SettingDefinition(
        "telegram_ops_enabled",
        "environment",
        "bool",
        "Telegram 운영 명령 Polling",
        env_attr="telegram_ops_enabled",
        default="false",
    ),
    SettingDefinition(
        "telegram_ops_poll_interval_seconds",
        "environment",
        "number",
        "Telegram Ops Polling 주기(초)",
        env_attr="telegram_ops_poll_interval_seconds",
        default="3",
    ),
    SettingDefinition(
        "telegram_allowed_chat_ids",
        "environment",
        "string",
        "Telegram 허용 Chat ID (쉼표)",
        env_attr="telegram_allowed_chat_ids",
    ),
    SettingDefinition(
        "telegram_notification_level",
        "environment",
        "string",
        "알림 레벨 (INFO/WARN/CRITICAL)",
        env_attr="telegram_notification_level",
        default="INFO",
    ),
    SettingDefinition(
        "slack_enabled",
        "environment",
        "bool",
        "Slack 알림 사용",
        env_attr="slack_enabled",
        default="false",
    ),
    SettingDefinition(
        "slack_webhook_url",
        "environment",
        "string",
        "Slack Webhook URL",
        is_secret=True,
        env_attr="slack_webhook_url",
    ),
    SettingDefinition(
        "discord_enabled",
        "environment",
        "bool",
        "Discord 알림 사용",
        env_attr="discord_enabled",
        default="false",
    ),
    SettingDefinition(
        "discord_webhook_url",
        "environment",
        "string",
        "Discord Webhook URL",
        is_secret=True,
        env_attr="discord_webhook_url",
    ),
)


DEFINITION_BY_KEY: dict[str, SettingDefinition] = {
    item.key: item for item in SETTING_DEFINITIONS
}

CATEGORIES: tuple[str, ...] = (
    "system",
    "ai",
    "risk",
    "scheduler",
    "trading",
    "environment",
)


def serialize_value(value: Any, value_type: SettingValueType) -> str:
    if value_type == "bool":
        return "true" if bool(value) else "false"
    if value is None:
        return ""
    return str(value)


def parse_value(raw: str, value_type: SettingValueType) -> Any:
    text = (raw or "").strip()
    if value_type == "bool":
        lowered = text.lower()
        if lowered in {"1", "true", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "no", "n", "off", ""}:
            return False
        raise ValueError("bool 값은 true/false 여야 합니다.")
    if value_type == "int":
        return int(text)
    if value_type == "float":
        return float(text)
    return text


def mask_secret(value: str | None, *, is_secret: bool) -> str:
    if not is_secret:
        return value or ""
    if not value:
        return ""
    return MASKED_VALUE


def is_masked_input(value: str | None) -> bool:
    if value is None:
        return True
    stripped = value.strip()
    return stripped == "" or stripped == MASKED_VALUE or set(stripped) <= {"*"}
