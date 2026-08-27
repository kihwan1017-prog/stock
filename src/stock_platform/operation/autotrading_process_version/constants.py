"""AutoTrading Process Version — constants (OBSERVABILITY ONLY)."""

from __future__ import annotations

SCHEMA = "operation"

STATUS_ACTIVE = "ACTIVE"
STATUS_RETIRED = "RETIRED"
STATUS_DRAFT = "DRAFT"

CHANGE_LOGIC = "LOGIC_CHANGE"
CHANGE_CONFIG = "CONFIG_CHANGE"
CHANGE_RELIABILITY = "RELIABILITY_CHANGE"
CHANGE_OBSERVABILITY = "OBSERVABILITY_ONLY"
CHANGE_UI = "UI_ONLY"
CHANGE_RESEARCH = "RESEARCH_ONLY"

TRACE_FULL = "FULL"
TRACE_PARTIAL = "PARTIAL"
TRACE_UNKNOWN = "UNKNOWN"

# Process map stages (canonical order)
UPBIT_STAGES: list[dict[str, str]] = [
    {"id": "MARKET_DATA", "label": "시세", "desc": "실시간 시세와 캔들을 수집합니다."},
    {"id": "SCANNER", "label": "Scanner", "desc": "거래 가능한 종목을 찾습니다."},
    {"id": "CANDIDATE", "label": "후보", "desc": "기술·유동성 조건을 통과한 후보입니다."},
    {"id": "ANALYSIS_LLM", "label": "AI 분석", "desc": "분석 LLM이 ALLOW/HOLD 등을 권고합니다."},
    {"id": "SELECTION", "label": "Selection", "desc": "상위 후보를 선정합니다."},
    {"id": "WAITING", "label": "WAITING", "desc": "매수 조건을 만족할 때까지 슬롯에서 대기합니다."},
    {"id": "REVALIDATION", "label": "진입 재검증", "desc": "대기 중 MA/RSI/Volume을 다시 확인합니다."},
    {"id": "ENTRY_SIGNAL", "label": "Entry Signal", "desc": "PORTFOLIO_BULLISH 진입 신호를 평가합니다."},
    {"id": "TRADING_LLM", "label": "Trading LLM", "desc": "Trading LLM은 SHADOW만 (REAL gate OFF)."},
    {"id": "RISK", "label": "Risk", "desc": "주문 전 위험·계좌 상태를 확인합니다."},
    {"id": "ADMISSION", "label": "Admission", "desc": "일일 진입 한도를 확인합니다."},
    {"id": "ORDER", "label": "BUY 주문", "desc": "실주문을 생성·전송합니다."},
    {"id": "FILL", "label": "체결", "desc": "브로커 체결을 반영합니다."},
    {"id": "POSITION", "label": "포지션", "desc": "슬롯을 OPEN으로 유지합니다."},
    {"id": "EXIT_MONITOR", "label": "Exit Monitor", "desc": "손절·익절·추세 이탈을 감시합니다."},
    {"id": "EXIT_SIGNAL", "label": "Exit Signal", "desc": "매도 신호를 확정합니다."},
    {"id": "SELL_ORDER", "label": "SELL 주문", "desc": "매도 주문을 전송합니다."},
    {"id": "BINDING_FINALIZER", "label": "Finalize", "desc": "바인딩·손익을 확정합니다."},
    {"id": "PNL", "label": "손익", "desc": "실현 손익을 집계합니다."},
    {"id": "WATCHDOG", "label": "Watchdog", "desc": "파이프라인 장애를 감시·복구합니다."},
]

KIWOOM_STAGES: list[dict[str, str]] = [
    {"id": "MARKET_DATA", "label": "시세/Feed", "desc": "키움 실시간 시세를 수신합니다."},
    {"id": "UNIVERSE", "label": "Universe", "desc": "전략 고정 유니버스를 구독합니다."},
    {"id": "SCANNER", "label": "Scanner", "desc": "신호 후보를 스캔합니다."},
    {"id": "CANDIDATE", "label": "후보", "desc": "크로스/조건 후보입니다."},
    {"id": "ENTRY_SIGNAL", "label": "Entry Signal", "desc": "MA Golden Cross 등 진입 신호."},
    {"id": "ANALYSIS_LLM", "label": "AI 분석", "desc": "분석 LLM 권고 (있으면)."},
    {"id": "RISK", "label": "Risk", "desc": "리스크·한도를 확인합니다."},
    {"id": "ORDER", "label": "주문", "desc": "실주문을 생성합니다."},
    {"id": "FILL", "label": "체결", "desc": "체결을 반영합니다."},
    {"id": "POSITION", "label": "포지션", "desc": "보유 포지션을 관리합니다."},
    {"id": "EXIT_MONITOR", "label": "Exit Monitor", "desc": "청산 조건을 감시합니다."},
    {"id": "SELL_ORDER", "label": "매도", "desc": "매도 주문을 전송합니다."},
    {"id": "PNL", "label": "손익", "desc": "실현 손익을 집계합니다."},
    {"id": "WATCHDOG", "label": "Watchdog", "desc": "라이프사이클·런타임을 감시합니다."},
]

COMPONENT_TYPES = (
    "MARKET_DATA",
    "SCANNER",
    "CANDIDATE",
    "ANALYSIS_LLM",
    "SELECTION",
    "WAITING",
    "REVALIDATION",
    "ENTRY_SIGNAL",
    "TRADING_LLM",
    "RISK",
    "ADMISSION",
    "ORDER",
    "BROKER",
    "FILL",
    "POSITION",
    "EXIT_MONITOR",
    "EXIT_SIGNAL",
    "SELL_ORDER",
    "BINDING_FINALIZER",
    "PNL",
    "WATCHDOG",
)

# Bootstrap from known commits (REAL semantics vs reliability vs research)
BOOTSTRAP_CHANGES: list[dict[str, object]] = [
    {
        "git_commit": "9be7922",
        "market": "KIWOOM",
        "change_type": CHANGE_OBSERVABILITY,
        "component": "MARKET_DATA",
        "summary": "Kiwoom Process Map aligned to funnel/realtime health SoT",
        "change_reason": "하드코딩 FEED_DOWN 제거 — CURRENT vs HISTORY 분리",
        "real_policy_changed": False,
        "research_only": False,
        "evidence": [".run/k_kiwoom_process_map_sot_alignment.json"],
    },
    {
        "git_commit": "e07fe4d",
        "change_type": CHANGE_RELIABILITY,
        "component": "MARKET_DATA",
        "summary": "Kiwoom REAL feed auto-restore + start race/self-heal",
        "change_reason": "connected!=running thrash; REGULAR session startup reconcile; L1 feed",
        "real_policy_changed": False,
        "research_only": False,
        "evidence": [".run/k_kiwoom_market_data_failure_fix.json"],
    },
    {
        "git_commit": "fc46ccb",
        "change_type": CHANGE_RELIABILITY,
        "component": "RECOVERY",
        "summary": "Safe recovery cancel for existing Upbit open orders",
        "change_reason": "LIVE OFF 상태에서 기존 WAIT 주문 cancel-only",
        "real_policy_changed": False,
        "research_only": False,
        "evidence": [".run/k_upbit_order1896_safe_resolution_recovery.json"],
    },
    {
        "git_commit": "6530743",
        "change_type": CHANGE_RELIABILITY,
        "component": "RECOVERY",
        "summary": "Startup open-order reconciliation before unattended restore",
        "change_reason": "PROD restart 시 db_open gate 선행 reconcile",
        "real_policy_changed": False,
        "research_only": False,
        "evidence": [".run/k_upbit_startup_reconciliation_daily_quota.json"],
    },
    {
        "git_commit": "6530743",
        "change_type": CHANGE_LOGIC,
        "component": "ADMISSION",
        "summary": "Daily entry quota — consumed/reserved vs zero-fill cancel",
        "change_reason": "#1896 0-fill CANCELLED가 quota 소비하던 문제",
        "real_policy_changed": True,
        "research_only": False,
        "evidence": [".run/k_upbit_startup_reconciliation_daily_quota.json"],
    },
    {
        "git_commit": "c7eab49",
        "change_type": CHANGE_LOGIC,
        "component": "ADMISSION",
        "summary": "Daily entry limit atomic enforcement",
        "change_reason": "동시 진입 시 daily cap 레이스 방지",
        "real_policy_changed": True,
        "research_only": False,
        "evidence": [".run/k_upbit_daily_entry_limit_atomic_fix.json"],
    },
    {
        "git_commit": "7674b54",
        "change_type": CHANGE_RELIABILITY,
        "component": "EXIT_MONITOR",
        "summary": "Keep open-position quotes fresh for exit",
        "change_reason": "Exit 감시 quote freshness",
        "real_policy_changed": False,
        "research_only": False,
        "evidence": [],
    },
    {
        "git_commit": "df05bc4",
        "change_type": CHANGE_RESEARCH,
        "component": "EXIT_SIGNAL",
        "summary": "MA exit forward shadow experiment",
        "change_reason": "Confirm2 research shadow",
        "real_policy_changed": False,
        "research_only": True,
        "evidence": [],
    },
    {
        "git_commit": "d03999c",
        "change_type": CHANGE_RELIABILITY,
        "component": "WATCHDOG",
        "summary": "Reliability watchdog and self-heal",
        "change_reason": "스택 장애 자동 감지·복구",
        "real_policy_changed": False,
        "research_only": False,
        "evidence": [".run/k_autotrading_reliability_watchdog_selfheal.json"],
    },
    {
        "git_commit": "326f62f",
        "change_type": CHANGE_LOGIC,
        "component": "WAITING",
        "summary": "Prevent waiting slot starvation",
        "change_reason": "WAITING 고갈 방지",
        "real_policy_changed": True,
        "research_only": False,
        "evidence": [],
    },
    {
        "git_commit": "18768c3",
        "change_type": CHANGE_RELIABILITY,
        "component": "WAITING",
        "summary": "Detect waiting starvation from stack components",
        "change_reason": "health_state 오판 방지",
        "real_policy_changed": False,
        "research_only": False,
        "evidence": [],
    },
    {
        "git_commit": "bfa642c",
        "change_type": CHANGE_LOGIC,
        "component": "WAITING",
        "summary": "Preserve waiting age across revalidation",
        "change_reason": "waiting_started_at SoT — 재검증 시 age 리셋 금지",
        "real_policy_changed": True,
        "research_only": False,
        "evidence": [],
    },
    {
        "git_commit": "3a21d5f",
        "change_type": CHANGE_RELIABILITY,
        "component": "WATCHDOG",
        "summary": "Restore full execution stack automatically",
        "change_reason": "Runtime/Worker/Exit/Feed 자동 복구",
        "real_policy_changed": False,
        "research_only": False,
        "evidence": [".run/k_autotrading_full_stack_selfheal_final.json"],
    },
    {
        "git_commit": "ab29698",
        "change_type": CHANGE_RESEARCH,
        "component": "ENTRY_SIGNAL",
        "summary": "Entry signal shadow analysis E0-E4",
        "change_reason": "RESEARCH_ONLY threshold relaxation study",
        "real_policy_changed": False,
        "research_only": True,
        "evidence": [".run/k_upbit_entry_signal_shadow_research.json"],
    },
]

CURRENT_UPBIT_CONFIG_SNAPSHOT = {
    "entry_rule": "PORTFOLIO_BULLISH_STATE_ENTRY",
    "rsi_max": 70.0,
    "min_ma_separation_pct": 0.05,
    "min_volume_surge": 0.8,
    "daily_entry_limit_default": 20,
    "scanner_interval_seconds": 300,
    "trading_llm_real_gate": False,
    "confirm2_real_enabled": False,
    "analysis_llm": "qwen3:1.7b",
    "trading_llm": "qwen3.5:2b",
    "trading_llm_mode": "SHADOW",
    "entry_shadow_research": "entry_signal_shadow_v1",
    "ma_exit_shadow_research": "ma_dead_cross_confirm2_v1",
    "waiting_age_sot": "waiting_started_at",
}

CURRENT_KIWOOM_CONFIG_SNAPSHOT = {
    "entry_rule": "MA_GOLDEN_CROSS",
    "new_cross_required": True,
    "trading_llm_real_gate": False,
    "feed_source": "KIWOOM_MARKET_REALTIME",
    "note": "Process definition excludes transient FEED_DOWN runtime state",
}
