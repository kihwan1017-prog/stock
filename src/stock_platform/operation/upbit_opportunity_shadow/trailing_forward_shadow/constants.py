"""Trailing forward shadow — research constants (REAL trailing 정책 불변)."""

from __future__ import annotations

from datetime import datetime, timezone

RULE_VERSION = "trailing_forward_shadow_v2"
MARKET_UPBIT = "UPBIT"
RESEARCH_ONLY_LABEL = "RESEARCH_ONLY"
LAB_ID = "EXIT_OPTIMIZATION_SHADOW_LAB_V2"

STATUS_ACTIVE = "ACTIVE"
STATUS_COMPLETED = "COMPLETED"
STATUS_PRE_EXISTING_EXCLUDED = "PRE_EXISTING_POSITION_EXCLUDED"

# T0 = CURRENT REAL (activation: peak>entry, trail 3%)
# Round-trip fee ≈ 0.10% → activation 후보는 fee의 수 배 수준만
VARIANT_T0 = "T0"
VARIANT_T1 = "T1"
VARIANT_T2 = "T2"
VARIANT_T3 = "T3"
VARIANT_T4 = "T4"
# REAL trailing(arm +1.0% / drawdown -0.8%) + min_hold 60s — forward shadow only
VARIANT_T5 = "T5"
VARIANT_TRAILING_MIN_HOLD_60S_V1 = VARIANT_T5
# Exit Optimization Lab V2 — forward-only parallel grid (REAL trailing 불변)
VARIANT_T6 = "T6"  # min_hold 30s, arm+1.0 / dd -0.8
VARIANT_T7 = "T7"  # min_hold 120s, arm+1.0 / dd -0.8
VARIANT_T8 = "T8"  # min_hold 60s, arm+1.0 / dd -1.0

# 보수적 research grid (임의 과격 값 금지)
T0_ACTIVATION_PCT = 0.0  # peak > entry only
T0_TRAIL_PCT = 3.0
T1_ACTIVATION_PCT = 0.5  # min profit before arm
T1_TRAIL_PCT = 3.0
T2_ACTIVATION_PCT = 0.0
T2_TRAIL_PCT = 5.0
T3_ACTIVATION_PCT = 0.5
T3_TRAIL_PCT = 5.0
T4_ACTIVATION_PCT = 0.0
T4_TRAIL_PCT = 3.0
T4_MIN_HOLDING_SECONDS = 180
# REAL UBA trailing_activation_rate=0.01 / trailing_stop_rate=0.008
T5_ACTIVATION_PCT = 1.0
T5_TRAIL_PCT = 0.8
T5_MIN_HOLDING_SECONDS = 60
T6_ACTIVATION_PCT = 1.0
T6_TRAIL_PCT = 0.8
T6_MIN_HOLDING_SECONDS = 30
T7_ACTIVATION_PCT = 1.0
T7_TRAIL_PCT = 0.8
T7_MIN_HOLDING_SECONDS = 120
T8_ACTIVATION_PCT = 1.0
T8_TRAIL_PCT = 1.0
T8_MIN_HOLDING_SECONDS = 60
POLICY_TRAILING_MIN_HOLD_60S_V1 = "TRAILING_MIN_HOLD_60S_V1"
POLICY_TRAILING_MIN_HOLD_30S_V1 = "TRAILING_MIN_HOLD_30S_V1"
POLICY_TRAILING_MIN_HOLD_120S_V1 = "TRAILING_MIN_HOLD_120S_V1"
POLICY_TRAILING_1P0_1P0_MIN60_V1 = "TRAILING_1P0_1P0_MIN60_V1"

SAMPLE_TARGET_INITIAL = 10
SAMPLE_TARGET_NEXT = 25
SAMPLE_TARGET_PRIMARY = 50
EARLY_REVIEW_N = 30
PROMOTION_REVIEW_N = 50

# Lab V2 비교 대상 (T0 baseline + min-hold / drawdown grid)
LAB_COMPARE_VARIANTS = (VARIANT_T0, VARIANT_T5, VARIANT_T6, VARIANT_T7, VARIANT_T8)

HISTORICAL_TRAILING_REPLAY_AVAILABLE = False

# 5519e85 trailing shadow feature deploy (UTC) — enroll now() fallback 금지
FEATURE_KEY = "upbit_trailing_forward_shadow"
FEATURE_DEPLOY_EPOCH = datetime(2026, 8, 27, 11, 12, 0, tzinfo=timezone.utc)
FEATURE_DEPLOY_EPOCH_SOURCE = "feature_commit_5519e85_deploy_utc"
