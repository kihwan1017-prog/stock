"""Entry Signal Shadow — constants (RESEARCH_ONLY)."""

from __future__ import annotations

RULE_VERSION = "entry_signal_shadow_v1"
MARKET = "UPBIT"
RESEARCH_ONLY_LABEL = "RESEARCH_ONLY_NO_REAL_ORDER"

VARIANT_E0 = "E0"
VARIANT_E1 = "E1"
VARIANT_E2 = "E2"
VARIANT_E3 = "E3"
VARIANT_E4 = "E4"
ALL_VARIANTS = (VARIANT_E0, VARIANT_E1, VARIANT_E2, VARIANT_E3, VARIANT_E4)

STATUS_PENDING = "PENDING"
STATUS_COMPLETED = "COMPLETED"
STATUS_INSUFFICIENT_OUTCOME = "INSUFFICIENT_OUTCOME"

# per-horizon outcome (look-ahead 금지 — as-of 시점 이후만 MATURED)
HORIZON_PENDING = "PENDING"
HORIZON_MATURED = "MATURED"
HORIZON_MISSING_DATA = "MISSING_DATA"
HORIZON_INVALID_DATA = "INVALID_DATA"
HORIZON_QUARANTINED = "QUARANTINED"

# future return windows (minutes) — 4h·24h research extension
OUTCOME_WINDOWS_MIN = (5, 15, 30, 60, 240, 1440)

# unique natural opportunity identity (표본 = selection_id / research_opportunity_id)
UPBIT_SAMPLE_IDENTITY = "selection_id"

# fee SoT mirror — UpbitFeePolicy.DEFAULT_TAKER_RATE
FEE_TAKER_RATE = 0.0005
# round-trip fee pct (buy+sell) — same as exit churn research
FEE_RT_PCT = 0.10

FORWARD_SAMPLE_TARGET = 100

SOURCE_REPLAY = "HISTORICAL_REPLAY"
SOURCE_FORWARD = "FORWARD_NATURAL"
