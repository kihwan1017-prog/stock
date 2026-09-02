from functools import lru_cache
from pathlib import Path
import logging
import os
import secrets
import sys
from urllib.parse import quote_plus

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_logger = logging.getLogger(__name__)

_DEV_APP_ENVS = frozenset({"local", "dev", "development"})
_PROD_APP_ENVS = frozenset({"prod", "production", "staging"})
_TRUTHY = frozenset({"1", "true", "yes", "on"})

# 레거시 머신 고정 경로 — 호환용. 신규 배포는 STOCK_PLATFORM_ENV_FILE 권장
_LEGACY_ENV_PATH = Path(r"E:\StockTrading\secrets\stock-platform.env")

# LIVE Activation 최대 창(시간). ARM 세션 절대 상한은 이 값×3600초.
# 3600초 하드캡으로 1시간마다 재ARM을 강제하지 않는다.
LIVE_ACTIVATION_TTL_HOURS_MAX = 72


def is_testing_runtime() -> bool:
    """pytest / 명시적 테스트 플래그 여부."""

    flag = (os.environ.get("STOCK_PLATFORM_TESTING") or "").strip().lower()
    if flag in _TRUTHY:
        return True
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return True
    return "pytest" in sys.modules


def _env_flag(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in _TRUTHY


def resolve_env_file() -> Path | None:
    """ENV 파일 경로 결정.

    우선순위:
    1. STOCK_PLATFORM_DISABLE_ENV_FILE=true → 파일 미사용(환경변수만)
    2. STOCK_PLATFORM_ENV_FILE (명시 경로)
    3. cwd / 프로젝트 루트 stock-platform.env · .env
    4. 레거시 머신 경로 (테스트 런타임에서는 기본 제외)

    import 시점에 Settings를 만들지 않는다.
    """

    if _env_flag("STOCK_PLATFORM_DISABLE_ENV_FILE"):
        return None

    explicit = (os.environ.get("STOCK_PLATFORM_ENV_FILE") or "").strip()
    if explicit:
        path = Path(explicit)
        try:
            return path if path.is_file() else path
        except OSError:
            return path

    candidates: list[Path] = [
        Path.cwd() / "stock-platform.env",
        Path.cwd() / ".env",
        Path(__file__).resolve().parents[3] / "stock-platform.env",
        Path(__file__).resolve().parents[3] / ".env",
    ]

    # 레거시 머신 경로(호환). CI/이식 환경에서는 DISABLE_LEGACY 로 차단.
    # Live 플래그 오염은 pytest_configure 의 환경변수 오버라이드로 차단한다.
    if not _env_flag("STOCK_PLATFORM_DISABLE_LEGACY_ENV_PATH"):
        candidates.append(_LEGACY_ENV_PATH)

    for path in candidates:
        try:
            if path.is_file():
                return path
        except OSError:
            continue
    return None


def format_jwt_secret_missing_message() -> str:
    """JWT_SECRET 미설정 시 사용자에게 보여줄 안내 문구."""

    env_hint = resolve_env_file()
    hint = str(env_hint) if env_hint is not None else (
        "STOCK_PLATFORM_ENV_FILE 로 지정한 env 파일 "
        "또는 프로세스 환경변수"
    )

    return (
        "JWT_SECRET 환경변수가 없습니다.\n"
        "\n"
        "다음 내용을\n"
        f"{hint}\n"
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
        "템플릿: 프로젝트 stock-platform.env.example / .env.example\n"
        "참고: 구명칭 JWT_SECRET_KEY 는 JWT_SECRET 으로 이전하세요."
    )


class Settings(BaseSettings):
    app_env: str = "local"
    app_name: str = "stock-platform"
    app_timezone: str = "Asia/Seoul"
    # REAL 자동매매 ↔ 개발 hot-reload 분리 (History #92)
    # development: reload 허용, REAL activation fail-closed
    # production: reload 금지, REAL activation 허용
    app_runtime_mode: str = Field(
        default="development",
        description="APP_RUNTIME_MODE=development|production",
    )
    hot_reload_enabled: bool | None = Field(
        default=None,
        description="HOT_RELOAD_ENABLED — None이면 app_runtime_mode로 추론",
    )
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
    # 시세 WS 전용. None이면 KIWOOM_USE_MOCK 상속. 주문 host(UBA is_mock)와 분리.
    kiwoom_market_data_use_mock: bool | None = Field(default=None)
    kiwoom_live_order_enabled: bool = False
    # STEP 8-5-21 — LIVE Activation 기본 만료(시간). 무기한 금지.
    live_activation_ttl_hours: int = Field(
        default=4, ge=1, le=LIVE_ACTIVATION_TTL_HOURS_MAX
    )
    # 24H Unattended — 운영자 승인 horizon (시간). 무제한 금지.
    live_unattended_default_horizon_hours: int = Field(
        default=24, ge=1, le=168
    )
    live_unattended_max_horizon_hours: int = Field(default=168, ge=1, le=168)
    live_unattended_renewal_interval_seconds: int = Field(
        default=3600, ge=60, le=86400
    )
    live_unattended_renewal_margin_seconds: int = Field(
        default=600, ge=60, le=3600
    )
    live_unattended_arm_lease_ttl_seconds: int = Field(
        default=3600, ge=300, le=7200
    )
    live_unattended_activation_renew_hours: int = Field(
        default=8, ge=1, le=LIVE_ACTIVATION_TTL_HOURS_MAX
    )
    # 24H horizon 자동 연장 — 만료 N초 전 precheck (기본 60분)
    live_unattended_horizon_renew_margin_seconds: int = Field(
        default=3600, ge=300, le=7200
    )
    # horizon 연장 최소 간격 / 의미 있는 연장 하한 (기본 1시간)
    live_unattended_horizon_renew_interval_seconds: int = Field(
        default=3600, ge=300, le=86400
    )
    live_unattended_horizon_min_extension_seconds: int = Field(
        default=3600, ge=300, le=86400
    )
    # ARM/Activation 만료 스캔 주기(초). 주문/Runtime 기동 아님.
    live_session_expiry_scan_interval_seconds: float = Field(
        default=15.0, ge=5.0, le=60.0
    )
    # LIVE Dry Run / 소액 한도 (설정 없으면 Fail Closed는 Risk/Transition 경로)
    live_small_max_order_amount: float = Field(default=100_000.0, gt=0)
    live_small_max_daily_order_amount: float = Field(default=300_000.0, gt=0)
    live_small_max_daily_order_count: int = Field(default=10, ge=1)
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
    # 공식 국내주식 체결 실시간 type (주문체결 00과 혼용 금지)
    kiwoom_ws_market_type: str = "0B"
    # 백엔드 기동 시 REAL/MOCK 시세 WS 자동 시작 금지 (명시 probe/ops만)
    kiwoom_market_realtime_auto_start: bool = False
    kiwoom_ws_reconnect_min_seconds: float = 1.0
    kiwoom_ws_reconnect_max_seconds: float = 30.0
    kiwoom_ws_ping_interval_seconds: float = 20.0
    kiwoom_ws_ping_timeout_seconds: float = 10.0
    kiwoom_order_ws_url: str = Field(default="")
    kiwoom_order_ws_path: str = Field(default="")
    kiwoom_order_ws_subscribe_json: str = Field(default="")

    realtime_strategy_market_code: str = "KRX"
    realtime_strategy_symbol: str = Field(default="")
    # 실시간 Paper 실행 기본 계좌 (환경변수 REALTIME_PAPER_ACCOUNT_ID)
    realtime_paper_account_id: int = Field(default=1, ge=1)
    # Paper Outbox ACCEPTED → 자동 Fill (기본 OFF — 명시 활성화)
    paper_outbox_auto_fill: bool = False
    # Paper Outbox Worker 상시 Polling (기본 OFF)
    paper_outbox_worker_enabled: bool = False
    paper_outbox_worker_interval_seconds: float = 1.0
    paper_outbox_worker_batch_size: int = 20
    paper_outbox_worker_backoff_seconds: float = 2.0
    paper_outbox_worker_stale_seconds: float = 30.0
    # LIVE Outbox Worker 상시 Polling (기본 OFF — Fail Closed, Paper와 claim 분리)
    live_outbox_worker_enabled: bool = False
    # enabled=true여도 기동 시 자동 start 금지 (명시 Admin/ops start 필요)
    live_outbox_worker_auto_start: bool = False
    live_outbox_worker_interval_seconds: float = 1.0
    live_outbox_worker_batch_size: int = 20
    live_outbox_worker_backoff_seconds: float = 2.0
    live_outbox_worker_stale_seconds: float = 30.0
    # UPBIT AUTO BUY 제한 병렬 V1 — 기본 1(직렬), 상한 2 (잘못된 값→1)
    upbit_buy_executor_concurrency: int = Field(default=1, ge=1, le=2)
    upbit_buy_order_submit_concurrency: int = Field(default=1, ge=1, le=2)
    # AUTO LIVE readiness — 시세 stale 임계(초). 초과 시 BLOCKER
    autotrading_market_feed_stale_seconds: float = 30.0
    # Reliability watchdog (AutoTradingReliabilityWatchdog)
    autotrading_reliability_watchdog_enabled: bool = True
    autotrading_reliability_watchdog_interval_seconds: float = 30.0
    # UPBIT AUTO long-hold observability (Alert V2) — REAL Time Exit 아님
    upbit_long_hold_watch_enabled: bool = True
    upbit_long_hold_watch_interval_seconds: float = 60.0
    autotrading_scanner_slo_multiplier: float = 2.0
    autotrading_runner_heartbeat_slo_seconds: float = 30.0
    autotrading_worker_heartbeat_slo_seconds: float = 30.0
    autotrading_exit_heartbeat_slo_seconds: float = 30.0
    autotrading_exit_eval_slo_seconds: float = 30.0
    autotrading_pipeline_stall_minutes: float = 15.0
    autotrading_funnel_window_minutes: float = 15.0
    # Portfolio: ENTRY_PENDING + entry_order_id null 고착 해제 (DB updated_at 기준)
    # 실제 reservation/주문 단계에만 적용 (WAITING_SIGNAL 제외)
    upbit_portfolio_entry_pending_timeout_seconds: float = 120.0
    # WAITING_SIGNAL 후보 유지 / 교체 임계
    upbit_portfolio_candidate_hold_seconds: float = 1800.0
    upbit_portfolio_candidate_switch_min_score_delta: float = 8.0
    # WAITING_SIGNAL 최대 대기(초). hold 이후 stale/장기 미진입 교체에 사용
    upbit_portfolio_candidate_max_wait_seconds: float = 10800.0
    # WAITING lifecycle — slot starvation 방지 (전략 threshold 변경 없음)
    upbit_waiting_revalidation_interval_seconds: float = 300.0
    upbit_waiting_soft_stale_seconds: float = 1800.0
    upbit_waiting_hard_expire_no_signal_seconds: float = 5400.0
    upbit_waiting_consecutive_no_signal_threshold: int = 3
    upbit_waiting_starvation_degraded_seconds: float = 900.0
    upbit_waiting_starvation_broken_seconds: float = 3600.0
    # MA entry policy — CROSS_EVENT(기존 golden cross) | BULLISH_STATE(portfolio)
    # 실제 적용은 FULL_MARKET_PORTFOLIO + DB risk_group_policy_json.entry_signal_policy 우선
    upbit_portfolio_entry_signal_policy: str = "CROSS_EVENT"
    upbit_portfolio_entry_rsi_max: float = 70.0
    upbit_portfolio_entry_min_volume_surge: float = 0.8
    upbit_portfolio_entry_min_ma_separation_pct: float = 0.05
    upbit_portfolio_entry_require_ai_allow: bool = True
    # MA_DEAD_CROSS anti-churn (보호 SL/TP/Trailing 미적용)
    upbit_portfolio_exit_min_ma_separation_pct: float = 0.03
    upbit_portfolio_ma_exit_min_holding_seconds: int = 180
    upbit_portfolio_estimated_fee_rate: float = 0.0005
    # WRK-014 durable exit intent + bounded retry (승인 정책)
    upbit_exit_intent_retry_enabled: bool = True
    upbit_exit_intent_retry_cooldown_seconds: int = 60
    upbit_exit_intent_max_retries: int = 3
    # MA Signal → AI Gate (기본 OFF). LIVE Gate는 별도 플래그(기본 OFF)
    autotrading_ai_signal_gate_enabled: bool = False
    autotrading_ai_signal_gate_live_enabled: bool = False
    autotrading_ai_signal_gate_shadow_enabled: bool = True
    autotrading_ai_analysis_ttl_seconds: float = 900.0
    # Scheduler skip/reuse window — Gate TTL(900)과 분리.
    # None이면 interval-grace(기본) — reuse==interval이면 분석 지연으로 격 tick skip.
    # age <= reuse 이면 FRESH_RESULT_EXISTS skip; 동일 tick 중복은 time_bucket.
    # Gate freshness는 TTL 유지(임의 변경 금지).
    autotrading_ai_analysis_reuse_seconds: float | None = None
    autotrading_ai_live_fail_closed: bool = True
    autotrading_ai_min_confidence: float = 0.4
    autotrading_ai_reduce_ratio: float = 0.5
    # UPBIT AI Market Analysis 주기 Job (Gate ON과 분리, 기본 OFF)
    autotrading_ai_analysis_enabled: bool = False
    autotrading_ai_analysis_interval_seconds: float = 300.0
    autotrading_ai_analysis_symbol: str = "KRW-XRP"
    autotrading_ai_analysis_timeframe: str = "1m"
    autotrading_ai_analysis_provider: str = "ollama"
    # 빈 문자열 → resolved_analysis_llm_model (1.7b). 4b는 Teacher/reference 전용.
    autotrading_ai_analysis_model: str = Field(default="")
    # Ollama 분석 timeout — cold start 여유만 소폭 (무분별 확대 금지)
    autotrading_ai_analysis_timeout_seconds: float = 150.0
    autotrading_ai_analysis_max_tokens: int = Field(default=1024, ge=256, le=4096)
    autotrading_ai_analysis_warmup_enabled: bool = True
    # UPBIT Opportunity Scanner — SHADOW_ONLY Fail Closed (기본 OFF, 주문/Runtime 무관)
    upbit_opportunity_scanner_enabled: bool = False
    upbit_opportunity_scanner_mode: str = "SHADOW_ONLY"
    # 기본 900. 5분(300)은 latency gate(median<=180 / p95<=240) 통과 후에만 env로 적용.
    upbit_opportunity_scanner_interval_seconds: float = 900.0
    upbit_scanner_min_24h_trade_value_krw: float = 5_000_000_000.0
    upbit_scanner_top_n: int = Field(default=5, ge=1, le=10)
    upbit_scanner_symbol_cooldown_seconds: float = 1800.0
    upbit_scanner_max_spike_pct: float = 15.0
    upbit_scanner_technical_candidate_limit: int = Field(
        default=30, ge=5, le=100
    )
    upbit_scanner_min_candles: int = Field(default=30, ge=20, le=200)
    upbit_scanner_candle_unit: int = Field(default=1, ge=1, le=15)
    # 분봉 N+1 완화 — Upbit quotation rate limiter(기본 8 rps)와 맞춤
    upbit_scanner_candle_concurrency: int = Field(default=8, ge=1, le=16)
    # Ollama는 미니PC에서 과병렬 금지. 1=직렬, 2=제한 병렬(동일 판정 semantics)
    upbit_scanner_ai_concurrency: int = Field(default=2, ge=1, le=4)
    # 심볼당 candle REST timeout (전체 scan hang 방지)
    upbit_scanner_candle_timeout_seconds: float = Field(
        default=12.0, ge=3.0, le=60.0
    )
    upbit_scanner_ai_enabled: bool = True
    upbit_scanner_notify_hold: bool = False
    # Scanner universe 품질 필터 (중앙 policy)
    upbit_scanner_exclude_stablecoins: bool = True
    upbit_scanner_exclude_caution_markets: bool = True
    upbit_scanner_ai_backfill_enabled: bool = True
    upbit_scanner_stablecoin_base_assets: str = (
        "USDT,USDC,USD1,DAI,BUSD,TUSD,USDP,FDUSD,USDE,USDS,USDD"
    )
    # FULL_MARKET Dynamic LIVE — 기본 OFF, FIXED_SYMBOL 보호
    upbit_full_market_min_score: float = 0.0
    upbit_full_market_min_liquidity_krw: float = 0.0
    upbit_full_market_min_confidence: float = 0.0
    upbit_full_market_max_candidate_age_seconds: float = 1800.0
    upbit_full_market_entry_cooldown_seconds: float = 300.0
    upbit_full_market_ai_live_gate_mode: str = "ENFORCE"
    upbit_full_market_allow_reduce_as_entry: bool = True
    upbit_full_market_excluded_symbols: str = ""
    upbit_full_market_consume_after_scanner: bool = True
    # Paper Shadow v1 — 실주문 없이 가상 성과만 (Scanner enabled와 독립)
    upbit_scanner_shadow_enabled: bool = True
    upbit_scanner_shadow_assumed_amount_krw: float = 5000.0
    upbit_scanner_shadow_reduce_ratio: float = Field(
        default=0.5, ge=0.1, le=1.0
    )
    upbit_scanner_shadow_cooldown_seconds: float = 3600.0
    upbit_scanner_shadow_sl_pct: float = 3.0
    upbit_scanner_shadow_tp_pct: float = 6.0
    # Shadow evaluator 자동 주기 (1~5분, LIVE/주문 무관)
    upbit_scanner_shadow_evaluator_enabled: bool = True
    upbit_scanner_shadow_evaluator_interval_seconds: float = 180.0
    # MA exit forward shadow — Confirm2 vs REAL baseline (연구용, REAL 정책 0 변경)
    upbit_ma_exit_forward_shadow_enabled: bool = True
    upbit_entry_signal_shadow_enabled: bool = True
    upbit_entry_signal_shadow_interval_seconds: float = 120.0
    # H2/H3 frozen forward-shadow — research only, no REAL publish
    upbit_h2_h3_forward_shadow_enabled: bool = True
    upbit_h2_h3_forward_shadow_interval_seconds: float = 180.0
    kiwoom_entry_signal_shadow_enabled: bool = True
    kiwoom_entry_signal_shadow_interval_seconds: float = 120.0
    # KIWOOM multi-symbol universe V1 — SHADOW | REAL (REAL = shadow observability + executor)
    kiwoom_multi_symbol_mode: str = "SHADOW"
    kiwoom_multi_symbol_shadow_enabled: bool = False
    kiwoom_multi_symbol_shadow_only: bool = True
    kiwoom_multi_symbol_monitor_target: int = 10
    kiwoom_multi_symbol_refresh_interval_seconds: float = 300.0
    kiwoom_multi_symbol_min_trade_value: int = 100_000_000
    kiwoom_multi_symbol_default_uba_id: int = 1381
    upbit_ma_exit_forward_shadow_deployed_at: str = ""
    upbit_ma_exit_forward_shadow_interval_seconds: float = 60.0
    # Trailing forward shadow — T0 REAL 유지, T1~T4 가상만 (REAL threshold 0 변경)
    upbit_trailing_forward_shadow_enabled: bool = True
    upbit_trailing_forward_shadow_deployed_at: str = ""
    upbit_trailing_forward_shadow_interval_seconds: float = 60.0
    # Exit strategy shadow V1 — SL/TP/Trail/Time research (REAL exit 정책 0 변경)
    upbit_exit_strategy_shadow_enabled: bool = True
    upbit_exit_strategy_shadow_interval_seconds: float = 60.0
    # Waiting lifecycle forward shadow lab — R0/R1/R2/R3 (REAL waiting policy 0 변경)
    upbit_waiting_lifecycle_shadow_enabled: bool = True
    upbit_waiting_lifecycle_shadow_interval_seconds: float = 60.0
    # Exit Order Recovery Shadow Lab V1 — RESEARCH ONLY (REAL cancel/reprice 금지)
    upbit_exit_order_recovery_shadow_enabled: bool = True
    upbit_exit_order_recovery_shadow_interval_seconds: float = 60.0
    # Exit Optimization Shadow Lab V3 — E1–E4 forward research (REAL exit 0 변경)
    upbit_exit_optimization_shadow_v3_enabled: bool = True
    upbit_exit_optimization_shadow_v3_deployed_at: str = ""
    upbit_exit_optimization_shadow_v3_interval_seconds: float = 60.0
    # Profitability Improvement Shadow Lab V1 — Candidate V2 / Exit V4 / Reentry (REAL 0 변경)
    upbit_profitability_improvement_shadow_enabled: bool = True
    upbit_profitability_improvement_shadow_deployed_at: str = ""
    upbit_profitability_improvement_shadow_interval_seconds: float = 60.0
    upbit_scanner_shadow_mismatch_watch_enabled: bool = True
    upbit_scanner_shadow_mismatch_tolerance: float = 5e-4
    upbit_scanner_shadow_cohort_milestone_watch_enabled: bool = True
    # Paper ACCEPTED Fill Recovery Scheduler (기본 OFF)
    paper_fill_recovery_enabled: bool = False
    paper_fill_recovery_interval_seconds: float = 5.0
    paper_fill_recovery_batch_size: int = 50
    # Paper 결정적/Replay 가격 공급 (기본 OFF, LIVE WS 미사용)
    paper_price_feed_enabled: bool = False
    paper_price_feed_interval_seconds: float = 1.0
    # Runtime/Runner 자동 기동 Feature Flag (기본 OFF — Fail Closed)
    realtime_execution_auto_start_enabled: bool = False
    realtime_paper_auto_start_enabled: bool = False
    realtime_live_auto_start_enabled: bool = False
    # LIVE Runner 대상 UBA / Unlock (기본 미설정 — Fail Closed)
    realtime_live_user_broker_account_id: int = 0
    realtime_live_unlock_token: str = Field(default="")
    # LIVE Shadow — 실주문 HTTP 0, Intent만 기록 (기본 OFF)
    live_shadow_mode_enabled: bool = False
    # LIVE Dry-Run — Risk 통과 후 submit 직전 Payload 검증·차단 (기본 OFF)
    live_order_dry_run_enabled: bool = False
    # Upbit 24/7 Shadow 시세·Candidate Runtime (기본 OFF, 실주문 Flag와 분리)
    realtime_upbit_shadow_auto_start_enabled: bool = False
    # KRX 장 종료 시 UPBIT feed/runner 유지 (24/7 — Scheduler PAUSE와 무관)
    realtime_upbit_24x7_keep_on_krx_close: bool = True
    realtime_upbit_default_symbol: str = "KRW-BTC"
    # Kiwoom MOCK realtime loop (기본 OFF — Fail Closed, LIVE와 분리)
    realtime_kiwoom_mock_auto_start_enabled: bool = False
    kiwoom_mock_outbox_auto_fill: bool = False
    # STEP 8-5-9 — Realtime Hub / Scope
    realtime_hub_enabled: bool = True
    realtime_auto_connect: bool = True
    realtime_event_max_age_seconds: float = 10.0
    realtime_reconnect_base_seconds: float = 1.0
    realtime_reconnect_max_seconds: float = 60.0
    realtime_reconnect_jitter_ratio: float = 0.2
    realtime_signal_cooldown_seconds: int = 30
    realtime_warmup_timeout_seconds: float = 60.0
    realtime_max_scopes_per_symbol: int = 100
    strategy_auto_deploy_enabled: bool = False
    paper_strategy_auto_stop_enabled: bool = False

    # 알림 (선택)
    telegram_enabled: bool = False
    telegram_bot_token: str = Field(default="")
    telegram_chat_id: str = Field(default="")
    # 시장별 destination (비어 있으면 telegram_chat_id fallback)
    telegram_upbit_chat_id: str = Field(default="")
    telegram_kiwoom_chat_id: str = Field(default="")
    # STEP54 — Telegram Ops
    telegram_ops_enabled: bool = False
    telegram_ops_poll_interval_seconds: float = 3.0
    # 자동매매 일일 운영보고 Telegram (23:30 KST 기본) — trading fail-open
    autotrading_daily_report_telegram_enabled: bool = True
    autotrading_daily_report_hour_kst: int = 23
    autotrading_daily_report_minute_kst: int = 30
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

    # JWT 인증 — 공식 이름 JWT_SECRET. JWT_SECRET_KEY 는 호환 alias.
    jwt_secret: str = Field(
        default="",
        validation_alias=AliasChoices(
            "JWT_SECRET",
            "jwt_secret",
            "JWT_SECRET_KEY",
            "jwt_secret_key",
        ),
    )
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 7
    # local/dev 에서만 허용. prod 에서는 무시되고 JWT_SECRET 필수
    jwt_dev_auto_secret: bool = True
    # 최초 관리자 시드 (사용자가 0명일 때만 생성)
    auth_bootstrap_admin_username: str = Field(default="")
    auth_bootstrap_admin_password: str = Field(default="")
    # 로그인 실패 잠금
    auth_max_failed_logins: int = 5
    auth_lockout_minutes: int = 15
    # true면 login/refresh 응답에 HttpOnly refresh cookie 설정
    # SPA가 다른 Origin이면 credentials + CORS 필요
    auth_refresh_cookie_enabled: bool = False

    # Google OAuth / OIDC (Authorization Code). 비어 있으면 기능 OFF.
    google_oauth_enabled: bool = False
    google_oauth_client_id: str = Field(default="")
    google_oauth_client_secret: str = Field(default="")
    # 브라우저가 도달하는 exact redirect (예: https://stock.../api/v1/auth/google/callback)
    google_oauth_redirect_uri: str = Field(default="")
    # callback 후 FE 완료 페이지 (예: https://stock.../login/google/complete)
    google_oauth_frontend_complete_url: str = Field(default="")

    upbit_base_url: str = "https://api.upbit.com"
    upbit_timeout_seconds: float = 10.0
    upbit_max_requests_per_second: int = 8
    # Private API (잔고·주문) — 평문 env만, DB 저장 금지
    # 사용자 실계좌는 Vault(UBA) Credential 사용 (STEP 8-5-2)
    upbit_access_key: str = Field(default="")
    upbit_secret_key: str = Field(default="")
    # AES-256-GCM Master Key 파일 경로 (원문 금지 — 경로만)
    broker_vault_master_key_file: str = Field(default="")
    # true면 private 호출 대신 mock 스냅샷 (로컬/CI)
    upbit_use_mock: bool = True
    # 실주문은 이중 게이트 필요 — 기본 false
    upbit_live_order_enabled: bool = False
    # 허용 마켓 화이트리스트 (쉼표). 비우면 제한 없음(조회용)
    upbit_allowed_markets: str = Field(default="")
    # 스냅샷 account_number 식별자 (업비트는 단일 마스터 키)
    upbit_account_ref: str = Field(default="MAIN")

    # STEP 8-5-8 — Upbit Rate Limit / Retry-After
    upbit_retry_max_attempts_read: int = 4
    upbit_retry_max_attempts_write: int = 1
    upbit_retry_base_delay_seconds: float = 1.0
    upbit_retry_max_delay_seconds: float = 60.0
    upbit_retry_jitter_ratio: float = 0.2
    upbit_retry_after_max_seconds: float = 300.0
    upbit_rate_limit_cooldown_persist_seconds: float = 10.0
    upbit_418_default_block_seconds: float = 600.0
    upbit_rate_limit_coordinator_enabled: bool = True
    # STEP 8-5-12 — Client Identifier / Ambiguous Resolver
    upbit_client_order_identifier_enabled: bool = True
    upbit_ambiguous_resolver_enabled: bool = True
    upbit_ambiguous_lookup_initial_delay_seconds: int = 2
    upbit_ambiguous_lookup_max_attempts: int = 5
    upbit_ambiguous_lookup_max_age_seconds: int = 120
    upbit_ambiguous_lookup_backoff_seconds: int = 2
    upbit_order_auto_resubmit_enabled: bool = False
    upbit_order_idempotency_enabled: bool = True
    upbit_order_idempotency_ttl_hours: int = 24
    # STEP 8-5-14 — Ambiguous Resolver Scheduler (DB Claim / Distributed Lock)
    upbit_ambiguous_resolver_poll_seconds: int = 5
    upbit_ambiguous_resolver_batch_size: int = 20
    upbit_ambiguous_resolver_claim_seconds: int = 60
    upbit_ambiguous_max_orders_per_account_per_run: int = 5
    upbit_ambiguous_lookup_max_interval_seconds: int = 60
    upbit_ambiguous_resolver_run_history_days: int = 30

    # 실거래 전역 이중 게이트 (브로커별 LIVE_* 와 AND)
    global_live_order_enabled: bool = False

    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3.5:4b"
    ollama_timeout_seconds: float = 120.0
    ollama_temperature: float = 0.2
    ollama_keep_alive: str = "10m"
    # Dual LLM roles — RESEARCH/SHADOW only. REAL 주문 경로 미연결.
    # 빈 문자열이면 아래 기본 역할 모델로 resolve (ollama_model=4b는 reference 유지).
    analysis_llm_model: str = Field(default="qwen3:1.7b")
    analysis_llm_timeout_seconds: float = Field(default=90.0, ge=5.0, le=300.0)
    analysis_llm_temperature: float = Field(default=0.2, ge=0.0, le=1.0)
    analysis_llm_max_tokens: int = Field(default=512, ge=128, le=2048)
    analysis_llm_cache_ttl_seconds: float = Field(default=600.0, ge=30.0, le=3600.0)
    trading_llm_model: str = Field(default="qwen3.5:2b")
    trading_llm_timeout_seconds: float = Field(default=90.0, ge=5.0, le=300.0)
    trading_llm_temperature: float = Field(default=0.2, ge=0.0, le=1.0)
    trading_llm_max_tokens: int = Field(default=512, ge=128, le=2048)
    trading_llm_shadow_enabled: bool = True
    dual_llm_ollama_enabled: bool = True
    # Teacher (qwen3.5:4b) — selective audit only. REAL 미배선.
    teacher_llm_model: str = Field(default="")  # 빈값 → ollama_model
    teacher_llm_enabled: bool = True
    teacher_llm_timeout_seconds: float = Field(default=120.0, ge=5.0, le=300.0)
    teacher_llm_temperature: float = Field(default=0.2, ge=0.0, le=1.0)
    teacher_llm_max_tokens: int = Field(default=512, ge=128, le=2048)
    teacher_llm_max_rate: float = Field(default=0.15, ge=0.01, le=0.5)
    teacher_llm_confidence_threshold: float = Field(default=0.65, ge=0.1, le=1.0)
    teacher_llm_sample_rate: float = Field(default=0.05, ge=0.0, le=0.2)
    # CLEAN RAG (no Vector DB)
    dual_llm_rag_top_k: int = Field(default=5, ge=1, le=10)
    dual_llm_rag_cache_ttl_seconds: float = Field(default=300.0, ge=30.0, le=3600.0)
    # KIWOOM Dual LLM SHADOW — MA REAL path 미연결
    kiwoom_dual_llm_shadow_enabled: bool = True
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

    # STEP 11-1 — AI Provider Framework (자동매매 없음)
    ai_provider_mock_enabled: bool = True
    ai_provider_mock_default: bool = True
    ai_provider_mock_priority: int = 10
    ai_provider_mock_model: str = "mock-v1"
    ai_provider_mock_timeout_seconds: float = 5.0
    ai_provider_mock_retry_max: int = 1
    ai_provider_mock_signal: str = "HOLD"
    ai_provider_mock_latency_ms: float = 5.0
    ai_provider_mock_simulate_error: bool = False
    ai_provider_mock_simulate_timeout: bool = False
    ai_provider_openai_enabled: bool = False
    ai_provider_openai_priority: int = 20
    ai_provider_openai_model: str = "gpt-4o-mini"
    ai_provider_openai_endpoint: str = "https://api.openai.com/v1"
    ai_provider_openai_api_key: str = Field(default="")
    ai_provider_openai_timeout_seconds: float = 30.0
    ai_provider_openai_retry_max: int = 2
    ai_provider_openai_max_tokens: int = 1024
    ai_provider_openai_temperature: float = 0.2
    ai_provider_claude_enabled: bool = False
    ai_provider_claude_priority: int = 30
    ai_provider_claude_model: str = "claude-3-5-sonnet-latest"
    ai_provider_claude_endpoint: str = "https://api.anthropic.com"
    ai_provider_claude_api_key: str = Field(default="")
    ai_provider_claude_timeout_seconds: float = 30.0
    ai_provider_gemini_enabled: bool = False
    ai_provider_gemini_priority: int = 40
    ai_provider_gemini_model: str = "gemini-2.0-flash"
    ai_provider_gemini_endpoint: str = (
        "https://generativelanguage.googleapis.com"
    )
    ai_provider_gemini_api_key: str = Field(default="")
    ai_provider_gemini_timeout_seconds: float = 30.0
    ai_provider_ollama_enabled: bool = False
    ai_provider_ollama_priority: int = 50
    ai_provider_ollama_model: str = Field(default="")
    ai_provider_ollama_endpoint: str = Field(default="")
    ai_provider_ollama_timeout_seconds: float = 120.0
    ai_provider_openai_compatible_enabled: bool = False
    ai_provider_openai_compatible_priority: int = 60
    ai_provider_openai_compatible_model: str = "local-model"
    ai_provider_openai_compatible_endpoint: str = Field(default="")
    ai_provider_openai_compatible_api_key: str = Field(default="")
    ai_provider_openai_compatible_timeout_seconds: float = 30.0
    ai_provider_openai_compatible_allow_localhost: bool = True

    dart_api_key: str = Field(default="")
    dart_base_url: str = "https://opendart.fss.or.kr/api"
    dart_timeout_seconds: float = 60.0

    naver_client_id: str = Field(default="")
    naver_client_secret: str = Field(default="")
    naver_news_base_url: str = (
        "https://openapi.naver.com/v1/search/news.json"
    )
    naver_news_timeout_seconds: float = 15.0

    # Upbit Market Context Research Collection (연구 전용, 기본 ON)
    upbit_market_context_collection_enabled: bool = True
    upbit_market_context_collection_interval_seconds: float = 600.0  # 10분
    upbit_market_context_fng_interval_seconds: float = 3600.0  # 60분 F&G
    # 후보 Shadow 오픈 시 heuristic LLM (전종목 주기 호출 금지)
    upbit_market_context_candidate_llm_enabled: bool = True

    # STEP N2 — UPBIT News/Notice Collector
    # 공지(공식 API) 기본 ON · 암호화폐 뉴스(Naver 키 필요) 기본 OFF
    upbit_notice_collection_enabled: bool = True
    upbit_notice_collection_interval_seconds: float = 900.0  # 15분 (권장)
    upbit_notice_collection_overlap_hours: float = 48.0
    upbit_notice_api_base_url: str = (
        "https://api-manager.upbit.com/api/v1"
    )
    upbit_notice_page_size: int = Field(default=20, ge=1, le=50)
    upbit_notice_max_pages: int = Field(default=3, ge=1, le=10)
    upbit_notice_fetch_body: bool = True
    upbit_notice_timeout_seconds: float = 15.0
    upbit_notice_max_retries: int = Field(default=3, ge=0, le=8)
    upbit_notice_max_body_chars: int = Field(default=20_000, ge=500, le=100_000)
    crypto_news_collection_enabled: bool = False
    crypto_news_collection_interval_seconds: float = 900.0
    crypto_news_collection_query: str = "업비트 암호화폐"
    crypto_news_collection_display: int = Field(default=20, ge=1, le=50)

    # STEP N4 — UPBIT AI News Analysis (기본 OFF, INFORMATIONAL ONLY)
    upbit_news_ai_analysis_enabled: bool = False
    upbit_news_ai_analysis_interval_seconds: float = 900.0
    upbit_news_ai_analysis_batch_size: int = Field(default=5, ge=1, le=5)
    upbit_news_ai_analysis_model: str = Field(default="")
    upbit_news_ai_analysis_timeout_seconds: float = 180.0
    # STEP N5 — News Signal Standardization (DEFAULT OFF, LLM 금지)
    upbit_news_signal_enabled: bool = False
    upbit_news_signal_interval_seconds: float = 300.0
    # STEP N6 — News Combined Shadow Experiment (DEFAULT OFF, CONTROL 비수정)
    upbit_news_combined_shadow_enabled: bool = False
    upbit_news_combined_shadow_interval_seconds: float = 900.0

    scheduler_enabled: bool = True
    # API lifecycle 내 cron(일손실·전략 등). False면 outbox 제외 cron 미기동
    lifecycle_scheduler_enabled: bool = True
    # True면 PG advisory lock 리더만 lifecycle cron 기동 (다중 replica)
    scheduler_leader_lock_enabled: bool = False
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
    # Market data daily collection (AutomaticScheduler cron)
    scheduler_upbit_daily_hour: int = 2
    scheduler_upbit_daily_minute: int = 10
    scheduler_kiwoom_daily_hour: int = 18
    scheduler_kiwoom_daily_minute: int = 30
    market_data_backfill_batch_size: int = 20

    # STEP 8-5-3 — Broker Recovery Scheduler
    recovery_scheduler_enabled: bool = True
    # Startup Recovery 직후 Scheduler Job Cooldown (초)
    recovery_scheduler_startup_cooldown_seconds: int = 120

    # STEP 8-5-6 — PostgreSQL Distributed Recovery Lock
    recovery_distributed_lock_enabled: bool = True
    # Conflict 선택 Resolve 실제 실행 (기본 False = dry-run only)
    recovery_conflict_resolve_execute_enabled: bool = False
    recovery_lock_lease_seconds: int = 120
    recovery_lock_heartbeat_seconds: int = 30
    recovery_lock_acquire_timeout_seconds: float = 5.0
    recovery_lock_namespace: str = "stock-platform-recovery"

    # STEP 8-5-7 — KRX Trading Calendar
    krx_calendar_allow_weekday_fallback: bool = False
    krx_calendar_required_future_days: int = 60
    krx_calendar_sync_enabled: bool = True
    krx_calendar_stale_after_days: int = 30
    # STEP 8-5-11 — 변경 요청 승인자 분리 (소규모 운영 기본 false)
    krx_calendar_require_separate_approver: bool = False
    # Calendar 메모리 Cache TTL (초). 다중 인스턴스 최대 지연 ≈ TTL
    krx_calendar_cache_ttl_seconds: float = 2.0
    # STEP 8-5-13 — Session Timeline Offsets
    krx_preopen_minutes_before_open: int = 30
    krx_recovery_preopen_minutes_before_open: int = 30
    krx_new_entry_cutoff_minutes_before_close: int = 10
    krx_recovery_postclose_minutes_after_close: int = 10
    krx_snapshot_minutes_after_close: int = 10
    krx_settlement_minutes_after_close: int = 20
    krx_ai_analysis_minutes_after_close: int = 30
    krx_dynamic_session_jobs_enabled: bool = True
    krx_cron_fallback_enabled: bool = True
    krx_cron_fallback_early_tolerance_minutes: int = 5
    krx_cron_fallback_late_tolerance_minutes: int = 60
    paper_stock_follow_krx_calendar: bool = True

    # STEP 8-5-15 — 영속 Market Session Job (DB Claim 기반 Dispatcher/Reconcile)
    market_session_job_enabled: bool = True
    market_session_job_dispatcher_poll_seconds: int = 5
    market_session_job_batch_size: int = 20
    market_session_job_claim_seconds: int = 120
    market_session_job_reconcile_enabled: bool = True
    market_session_job_reconcile_interval_seconds: int = 300
    market_session_job_reconcile_days_ahead: int = 7
    market_session_job_max_attempts: int = 3
    market_session_job_retry_base_seconds: int = 30
    market_session_job_retry_max_seconds: int = 600
    market_session_job_retention_days: int = 90
    market_session_job_run_retention_days: int = 90
    market_session_cron_wakeup_enabled: bool = True

    # STEP 8-5-16 — EOD Account Settlement
    settlement_enabled: bool = True
    settlement_max_attempts: int = 3
    settlement_retry_base_seconds: int = 60
    settlement_retry_max_seconds: int = 900
    settlement_position_value_tolerance_krw: float = 10.0
    settlement_average_price_tolerance_krw: float = 1.0
    settlement_cash_tolerance_krw: float = 10.0
    settlement_equity_tolerance_krw: float = 100.0
    settlement_price_max_age_seconds: int = 3600
    settlement_pause_account_on_critical_mismatch: bool = True
    upbit_daily_settlement_enabled: bool = True
    upbit_daily_settlement_hour: int = 0
    upbit_daily_settlement_minute: int = 10

    # STEP 8-8A — Post-Fill 재검증
    post_fill_verify_enabled: bool = True
    post_fill_verify_poll_seconds: int = 2
    post_fill_verify_batch_size: int = 20
    post_fill_verify_claim_seconds: int = 30
    post_fill_verify_max_attempts: int = 5
    post_fill_verify_ttl_seconds: int = 60
    # WAITING_SNAPSHOT transient lag — TTL 만료 시 bounded defer (즉시 GLOBAL kill 금지)
    post_fill_verify_snapshot_defer_seconds: int = 120
    post_fill_verify_max_snapshot_defers: int = 3
    # 재시도 간격(초) — 콤마 구분, 하드코딩 금지
    post_fill_verify_retry_delays_seconds: str = "2,5,10,20"
    post_fill_verify_telegram_on_verified: bool = False

    # STEP 8-9 — Upbit 소액 LIVE 스모크
    upbit_live_preflight_ttl_seconds: int = 30
    upbit_live_smoke_allowlist: str = "KRW-BTC,KRW-ETH,KRW-XRP"
    upbit_live_smoke_order_watch_seconds: int = 60
    upbit_live_smoke_auto_cancel: bool = True
    # 스모크 Preflight에서 Scheduler Pause로 인정할지 (운영은 실제 Pause 후 True로)
    upbit_live_smoke_treat_scheduler_paused: bool = False
    upbit_live_smoke_default_amount: float = 5000.0
    upbit_live_smoke_max_amount: float = 10000.0
    # Confirm 발급 시각 기준 one-shot Worker dispatch TTL (ARM TTL과 분리)
    smoke_one_shot_dispatch_ttl_seconds: int = Field(default=90, ge=30, le=300)
    # Smoke 검증 중 autonomous EXIT submission 억제 TTL (초)
    smoke_exit_isolation_ttl_seconds: int = Field(default=600, ge=30, le=3600)
    # STEP 8-9A — Broker 추적 (거래 Scheduler와 분리)
    upbit_live_track_enabled: bool = True
    upbit_live_track_poll_seconds: int = 2
    upbit_live_track_retry_delays_seconds: str = "1,2,5,10,20"
    upbit_live_track_max_attempts: int = 8

    # STEP 8-11 — Operations Monitoring Dashboard stale / TTL
    ops_dashboard_broker_health_stale_seconds: int = 60
    ops_dashboard_scheduler_stale_seconds: int = 120
    ops_dashboard_runtime_stale_seconds: int = 60
    ops_dashboard_position_stale_seconds: int = 60
    ops_dashboard_readiness_stale_seconds: int = 30
    ops_dashboard_broker_balance_ttl_seconds: int = 20

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
    # UPBIT LIVE 확장 — 기본 OFF (실 운영 START는 후속 controlled step)
    position_exit_monitor_live_upbit_enabled: bool = False
    # KIWOOM LIVE — strategy-owned OPEN binding 만. 기본 OFF (runbook에서 ON)
    position_exit_monitor_live_kiwoom_enabled: bool = False

    # 백업 디렉터리 (머신 고정 경로 제거 — env로 주입)
    backup_dir: str = Field(default="backups")

    model_config = SettingsConfigDict(
        # 기본 env_file 은 __init__ 에서 resolve (import 시점 경로 고정 금지)
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    def __init__(self, **values: object) -> None:
        # _env_file 미지정 시 현재 resolve 결과 사용.
        # 테스트는 _env_file=None 으로 파일 로드를 끈다.
        if "_env_file" not in values:
            values["_env_file"] = resolve_env_file()
        super().__init__(**values)

    @model_validator(mode="after")
    def _warn_deprecated_jwt_secret_key(self) -> "Settings":
        """JWT_SECRET 없이 JWT_SECRET_KEY 만 있으면 호환 경고."""

        has_official = bool((os.environ.get("JWT_SECRET") or "").strip())
        has_legacy = bool((os.environ.get("JWT_SECRET_KEY") or "").strip())
        if has_legacy and not has_official and self.jwt_secret.strip():
            _logger.warning(
                "JWT_SECRET_KEY 는 deprecated 입니다. "
                "JWT_SECRET 으로 이름을 통일하세요."
            )
        return self

    @model_validator(mode="after")
    def _validate_recovery_distributed_lock(self) -> "Settings":
        """분산 Lock Lease/Heartbeat 설정 검증."""

        lease = int(self.recovery_lock_lease_seconds)
        hb = int(self.recovery_lock_heartbeat_seconds)
        timeout = float(self.recovery_lock_acquire_timeout_seconds)
        ns = (self.recovery_lock_namespace or "").strip()
        if lease <= 0:
            raise ValueError("recovery_lock_lease_seconds must be > 0")
        if hb <= 0:
            raise ValueError(
                "recovery_lock_heartbeat_seconds must be > 0"
            )
        if hb >= lease:
            raise ValueError(
                "recovery_lock_heartbeat_seconds must be "
                "< recovery_lock_lease_seconds"
            )
        if timeout < 0:
            raise ValueError(
                "recovery_lock_acquire_timeout_seconds must be >= 0"
            )
        if not ns:
            raise ValueError("recovery_lock_namespace must be non-empty")
        if (
            not self.recovery_distributed_lock_enabled
            and self.is_production_env
        ):
            _logger.warning(
                "RECOVERY_DISTRIBUTED_LOCK_ENABLED=false 는 "
                "개발/테스트 전용입니다. 운영에서는 활성화하세요."
            )
        return self

    @model_validator(mode="after")
    def _validate_krx_calendar_settings(self) -> "Settings":
        if int(self.krx_calendar_required_future_days) <= 0:
            raise ValueError(
                "krx_calendar_required_future_days must be > 0"
            )
        if self.krx_calendar_allow_weekday_fallback:
            _logger.warning(
                "KRX_CALENDAR_ALLOW_WEEKDAY_FALLBACK=true — "
                "개발/테스트 전용. 운영 LIVE 거래는 Fail Closed를 권장합니다."
            )
            if self.is_production_env:
                _logger.error(
                    "운영 환경에서 WEEKDAY_FALLBACK이 활성화되어 있습니다. "
                    "LIVE 자동매매 신뢰성을 보장할 수 없습니다."
                )
        # STEP 8-5-13 offset validation
        for name in (
            "krx_preopen_minutes_before_open",
            "krx_recovery_preopen_minutes_before_open",
            "krx_new_entry_cutoff_minutes_before_close",
            "krx_recovery_postclose_minutes_after_close",
            "krx_snapshot_minutes_after_close",
            "krx_settlement_minutes_after_close",
            "krx_ai_analysis_minutes_after_close",
            "krx_cron_fallback_early_tolerance_minutes",
            "krx_cron_fallback_late_tolerance_minutes",
        ):
            if int(getattr(self, name)) < 0:
                raise ValueError(f"{name} must be >= 0")
        if self.krx_cron_fallback_late_tolerance_minutes <= 0:
            raise ValueError(
                "krx_cron_fallback_late_tolerance_minutes must be > 0"
            )
        if (
            not self.krx_dynamic_session_jobs_enabled
            and self.is_production_env
        ):
            _logger.warning(
                "KRX_DYNAMIC_SESSION_JOBS_ENABLED=false in production"
            )
        return self

    @model_validator(mode="after")
    def _validate_upbit_retry_settings(self) -> "Settings":
        if self.upbit_retry_max_attempts_read < 0:
            raise ValueError("upbit_retry_max_attempts_read must be >= 0")
        if self.upbit_retry_max_attempts_write < 0:
            raise ValueError("upbit_retry_max_attempts_write must be >= 0")
        if self.upbit_retry_base_delay_seconds < 0:
            raise ValueError("upbit_retry_base_delay_seconds must be >= 0")
        if (
            self.upbit_retry_max_delay_seconds
            < self.upbit_retry_base_delay_seconds
        ):
            raise ValueError(
                "upbit_retry_max_delay_seconds must be "
                ">= upbit_retry_base_delay_seconds"
            )
        if not 0 <= self.upbit_retry_jitter_ratio <= 1:
            raise ValueError("upbit_retry_jitter_ratio must be in [0, 1]")
        if self.upbit_retry_after_max_seconds <= 0:
            raise ValueError("upbit_retry_after_max_seconds must be > 0")
        if self.upbit_418_default_block_seconds <= 0:
            raise ValueError("upbit_418_default_block_seconds must be > 0")
        if (
            not self.upbit_rate_limit_coordinator_enabled
            and self.is_production_env
        ):
            _logger.warning(
                "UPBIT_RATE_LIMIT_COORDINATOR_ENABLED=false "
                "in production"
            )
        if self.upbit_ambiguous_lookup_initial_delay_seconds < 0:
            raise ValueError(
                "upbit_ambiguous_lookup_initial_delay_seconds must be >= 0"
            )
        if self.upbit_ambiguous_lookup_max_attempts < 1:
            raise ValueError(
                "upbit_ambiguous_lookup_max_attempts must be >= 1"
            )
        if self.upbit_ambiguous_lookup_max_age_seconds <= 0:
            raise ValueError(
                "upbit_ambiguous_lookup_max_age_seconds must be > 0"
            )
        if self.upbit_ambiguous_lookup_backoff_seconds <= 0:
            raise ValueError(
                "upbit_ambiguous_lookup_backoff_seconds must be > 0"
            )
        if self.upbit_order_idempotency_ttl_hours <= 0:
            raise ValueError(
                "upbit_order_idempotency_ttl_hours must be > 0"
            )
        if (
            not self.upbit_client_order_identifier_enabled
            and self.upbit_live_order_enabled
        ):
            _logger.warning(
                "UPBIT_CLIENT_ORDER_IDENTIFIER_ENABLED=false while "
                "LIVE orders enabled — Ambiguous resolve weakened"
            )
        if self.upbit_order_auto_resubmit_enabled:
            _logger.warning(
                "UPBIT_ORDER_AUTO_RESUBMIT_ENABLED=true — "
                "운영 기본은 false (수동 승인 권장)"
            )
        if self.upbit_ambiguous_resolver_poll_seconds < 1:
            raise ValueError(
                "upbit_ambiguous_resolver_poll_seconds must be >= 1"
            )
        if self.upbit_ambiguous_resolver_batch_size <= 0:
            raise ValueError(
                "upbit_ambiguous_resolver_batch_size must be > 0"
            )
        if self.upbit_ambiguous_resolver_claim_seconds < 30:
            raise ValueError(
                "upbit_ambiguous_resolver_claim_seconds must be >= 30"
            )
        if self.upbit_ambiguous_max_orders_per_account_per_run <= 0:
            raise ValueError(
                "upbit_ambiguous_max_orders_per_account_per_run must be > 0"
            )
        if self.upbit_ambiguous_lookup_max_interval_seconds <= 0:
            raise ValueError(
                "upbit_ambiguous_lookup_max_interval_seconds must be > 0"
            )
        if self.upbit_ambiguous_resolver_run_history_days <= 0:
            raise ValueError(
                "upbit_ambiguous_resolver_run_history_days must be > 0"
            )
        return self

    @model_validator(mode="after")
    def _validate_market_session_job_settings(self) -> "Settings":
        """STEP 8-5-15 — 영속 Market Session Job Dispatcher/Reconcile 설정."""

        if self.market_session_job_dispatcher_poll_seconds < 1:
            raise ValueError(
                "market_session_job_dispatcher_poll_seconds must be >= 1"
            )
        if self.market_session_job_batch_size <= 0:
            raise ValueError(
                "market_session_job_batch_size must be > 0"
            )
        if self.market_session_job_claim_seconds < 30:
            raise ValueError(
                "market_session_job_claim_seconds must be >= 30"
            )
        if self.market_session_job_reconcile_interval_seconds < 30:
            raise ValueError(
                "market_session_job_reconcile_interval_seconds must be >= 30"
            )
        if self.market_session_job_reconcile_days_ahead < 0:
            raise ValueError(
                "market_session_job_reconcile_days_ahead must be >= 0"
            )
        if self.market_session_job_max_attempts < 1:
            raise ValueError(
                "market_session_job_max_attempts must be >= 1"
            )
        if self.market_session_job_retry_base_seconds < 1:
            raise ValueError(
                "market_session_job_retry_base_seconds must be >= 1"
            )
        if (
            self.market_session_job_retry_max_seconds
            < self.market_session_job_retry_base_seconds
        ):
            raise ValueError(
                "market_session_job_retry_max_seconds must be "
                ">= market_session_job_retry_base_seconds"
            )
        if self.market_session_job_retention_days < 1:
            raise ValueError(
                "market_session_job_retention_days must be >= 1"
            )
        if self.market_session_job_run_retention_days < 1:
            raise ValueError(
                "market_session_job_run_retention_days must be >= 1"
            )
        return self

    @model_validator(mode="after")
    def _validate_settlement_settings(self) -> "Settings":
        if self.settlement_max_attempts < 1:
            raise ValueError("settlement_max_attempts must be >= 1")
        if self.post_fill_verify_poll_seconds < 1:
            raise ValueError("post_fill_verify_poll_seconds must be >= 1")
        if self.post_fill_verify_max_attempts < 1:
            raise ValueError("post_fill_verify_max_attempts must be >= 1")
        if self.post_fill_verify_ttl_seconds < 1:
            raise ValueError("post_fill_verify_ttl_seconds must be >= 1")
        if self.post_fill_verify_snapshot_defer_seconds < 1:
            raise ValueError(
                "post_fill_verify_snapshot_defer_seconds must be >= 1"
            )
        if self.post_fill_verify_max_snapshot_defers < 0:
            raise ValueError(
                "post_fill_verify_max_snapshot_defers must be >= 0"
            )
        if self.post_fill_verify_claim_seconds < 5:
            raise ValueError("post_fill_verify_claim_seconds must be >= 5")
        if self.post_fill_verify_batch_size <= 0:
            raise ValueError("post_fill_verify_batch_size must be > 0")
        if self.settlement_retry_base_seconds < 1:
            raise ValueError("settlement_retry_base_seconds must be >= 1")
        if (
            self.settlement_retry_max_seconds
            < self.settlement_retry_base_seconds
        ):
            raise ValueError(
                "settlement_retry_max_seconds must be "
                ">= settlement_retry_base_seconds"
            )
        for name in (
            "settlement_position_value_tolerance_krw",
            "settlement_average_price_tolerance_krw",
            "settlement_cash_tolerance_krw",
            "settlement_equity_tolerance_krw",
        ):
            if float(getattr(self, name)) < 0:
                raise ValueError(f"{name} must be >= 0")
        if self.settlement_price_max_age_seconds <= 0:
            raise ValueError("settlement_price_max_age_seconds must be > 0")
        if not (0 <= int(self.upbit_daily_settlement_hour) <= 23):
            raise ValueError("upbit_daily_settlement_hour must be 0..23")
        if not (0 <= int(self.upbit_daily_settlement_minute) <= 59):
            raise ValueError("upbit_daily_settlement_minute must be 0..59")
        if not self.settlement_enabled and self.is_production_env:
            _logger.warning(
                "SETTLEMENT_ENABLED=false in production"
            )
        return self

    @model_validator(mode="after")
    def _validate_realtime_hub_settings(self) -> "Settings":
        if self.realtime_event_max_age_seconds <= 0:
            raise ValueError("realtime_event_max_age_seconds must be > 0")
        if self.realtime_reconnect_base_seconds < 0:
            raise ValueError("realtime_reconnect_base_seconds must be >= 0")
        if (
            self.realtime_reconnect_max_seconds
            < self.realtime_reconnect_base_seconds
        ):
            raise ValueError(
                "realtime_reconnect_max_seconds must be "
                ">= realtime_reconnect_base_seconds"
            )
        if not 0 <= self.realtime_reconnect_jitter_ratio <= 1:
            raise ValueError(
                "realtime_reconnect_jitter_ratio must be in [0, 1]"
            )
        if self.realtime_signal_cooldown_seconds < 0:
            raise ValueError(
                "realtime_signal_cooldown_seconds must be >= 0"
            )
        if self.realtime_warmup_timeout_seconds <= 0:
            raise ValueError("realtime_warmup_timeout_seconds must be > 0")
        if self.realtime_max_scopes_per_symbol <= 0:
            raise ValueError("realtime_max_scopes_per_symbol must be > 0")
        if not self.realtime_hub_enabled and self.is_production_env:
            _logger.warning(
                "REALTIME_HUB_ENABLED=false in production — "
                "LIVE scoped realtime signals will not dispatch"
            )
        return self

    @property
    def resolved_disclosure_summary_model(self) -> str:
        """사용자 공시 요약 모델 — 전용 설정 우선, 없으면 ollama_model."""

        custom = (self.ai_disclosure_summary_model or "").strip()
        return custom or self.ollama_model

    @property
    def resolved_analysis_llm_model(self) -> str:
        """ANALYSIS_LLM — 기본 qwen3:1.7b. ollama_model(4b)은 reference 유지."""

        return (self.analysis_llm_model or "").strip() or "qwen3:1.7b"

    @property
    def resolved_autotrading_ai_analysis_model(self) -> str:
        """Scanner/주기 차트 AI Gate 모델 — Analysis 역할(1.7b)과 정렬.

        명시 autotrading_ai_analysis_model 이 있으면 존중.
        비어 있으면 resolved_analysis_llm_model (Teacher 4b로 조용히 fallback 금지).
        """

        custom = (self.autotrading_ai_analysis_model or "").strip()
        if custom:
            return custom
        return self.resolved_analysis_llm_model

    @property
    def resolved_trading_llm_model(self) -> str:
        """TRADING_LLM SHADOW — 기본 qwen3.5:2b. REAL 미배선."""

        return (self.trading_llm_model or "").strip() or "qwen3.5:2b"

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
    def kiwoom_market_data_is_mock(self) -> bool:
        """시세 WS REAL/MOCK SoT. 주문 credential.is_mock과 독립."""

        if self.kiwoom_market_data_use_mock is None:
            return bool(self.kiwoom_use_mock)
        return bool(self.kiwoom_market_data_use_mock)

    @property
    def kiwoom_market_ws_default_url(self) -> str:
        if self.kiwoom_market_data_is_mock:
            return "wss://mockapi.kiwoom.com:10000"
        return "wss://api.kiwoom.com:10000"

    @property
    def kiwoom_ws_url_resolved(self) -> str:
        return self.kiwoom_ws_url.strip() or self.kiwoom_ws_default_url

    @property
    def kiwoom_market_ws_url_resolved(self) -> str:
        return self.kiwoom_ws_url.strip() or self.kiwoom_market_ws_default_url

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
                "고정 Secret이 필요하면 JWT_SECRET 을 설정하세요."
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
        """서버 기동 시 필수 설정을 검증한다. import 시점에는 호출하지 말 것."""

        # Option D: KIWOOM_USE_MOCK 은 shared market/WS SoT.
        # 실주문 eligibility 는 UBA credential / Activation / LIVE / ARM 게이트.
        # 기동 시 DB/credential 조회를 하지 않으므로 LIVE+shared MOCK 조합은 허용.
        if self.upbit_live_order_enabled and self.upbit_use_mock:
            raise ValueError(
                "UPBIT_LIVE_ORDER_ENABLED cannot be true "
                "when UPBIT_USE_MOCK is true"
            )
        if self.global_live_order_enabled and (
            self.kiwoom_live_order_enabled or self.upbit_live_order_enabled
        ):
            # 전역 라이브는 허용하되, 둘 다 mock이면 무의미하므로 경고성 검증은 생략
            pass
        if self.kiwoom_live_order_enabled and not self.global_live_order_enabled:
            # 키움 라이브도 전역 게이트 필요 (점진 도입 — 기동은 허용, factory에서 차단)
            pass
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

    def validate_upbit_credentials(self) -> None:
        """Private API 호출 전 Access/Secret 검증 (mock이면 스킵)."""

        if self.upbit_use_mock:
            return
        missing: list[str] = []
        if not self.upbit_access_key.strip():
            missing.append("UPBIT_ACCESS_KEY")
        if not self.upbit_secret_key.strip():
            missing.append("UPBIT_SECRET_KEY")
        if missing:
            raise ValueError(
                f"Missing Upbit credentials: {', '.join(missing)}"
            )

    def upbit_allowed_market_set(self) -> set[str]:
        raw = self.upbit_allowed_markets.strip()
        if not raw:
            return set()
        return {
            item.strip().upper()
            for item in raw.split(",")
            if item.strip()
        }

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
    """캐시된 Settings. 파일 경로는 호출 시점에 resolve 한다."""

    env_file = resolve_env_file()
    if env_file is None:
        return Settings(_env_file=None)
    return Settings(_env_file=env_file)


def clear_settings_cache() -> None:
    """테스트·핫리로드용 캐시 무효화."""

    get_settings.cache_clear()
