"""Trailing forward shadow — research constants (REAL trailing 정책 불변)."""

from __future__ import annotations

from datetime import datetime, timezone

RULE_VERSION = "trailing_forward_shadow_v1"
MARKET_UPBIT = "UPBIT"
RESEARCH_ONLY_LABEL = "RESEARCH_ONLY"

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

SAMPLE_TARGET_INITIAL = 10
SAMPLE_TARGET_NEXT = 25
SAMPLE_TARGET_PRIMARY = 50

HISTORICAL_TRAILING_REPLAY_AVAILABLE = False

# 5519e85 trailing shadow feature deploy (UTC) — enroll now() fallback 금지
FEATURE_KEY = "upbit_trailing_forward_shadow"
FEATURE_DEPLOY_EPOCH = datetime(2026, 8, 27, 11, 12, 0, tzinfo=timezone.utc)
FEATURE_DEPLOY_EPOCH_SOURCE = "feature_commit_5519e85_deploy_utc"
