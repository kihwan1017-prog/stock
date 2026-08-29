"""UPBIT Exit Strategy Shadow V1 — constants (research grid only)."""

from __future__ import annotations

from decimal import Decimal

RULE_VERSION = "exit_strategy_shadow_v1"
FEATURE_KEY = "upbit_exit_strategy_shadow"

FAMILY_BASELINE_MA = "BASELINE_MA"
FAMILY_STOP_LOSS = "STOP_LOSS"
FAMILY_TAKE_PROFIT = "TAKE_PROFIT"
FAMILY_TRAILING = "TRAILING_STOP"
FAMILY_TIME_EXIT = "TIME_EXIT"

STATUS_ACTIVE = "ACTIVE"
STATUS_TRIGGERED = "TRIGGERED"
STATUS_MATURED = "MATURED"
STATUS_INVALID = "INVALID"
STATUS_CENSORED = "CENSORED"

SAMPLE_NATURAL_AUTO = "NATURAL_AUTO"
SAMPLE_TEST = "TEST"
SAMPLE_MANUAL = "MANUAL"
SAMPLE_HISTORICAL = "HISTORICAL_RESEARCH"
SAMPLE_UNKNOWN = "UNKNOWN"

# research cost (WRK-015~018 canonical)
FEE_TAKER_RATE = Decimal("0.0005")
SLIPPAGE_BPS_EACH_SIDE = Decimal("2")

# Shadow research grid — NOT REAL config
SL_THRESHOLDS = (-0.5, -0.8, -1.0, -1.5)  # pct from entry
TP_THRESHOLDS = (0.8, 1.0, 1.5, 2.0)
TRAIL_THRESHOLDS = (0.4, 0.6, 0.8, 1.0)  # pct from peak
TIME_HORIZONS_MIN = (30, 60, 120, 240)

# MA baseline mirrors production defaults (do not mutate REAL)
MA_EXIT_MIN_SEPARATION_PCT = 0.03
MA_EXIT_MIN_HOLDING_SECONDS = 180

CHECKPOINT_N = (30, 50, 100, 200, 300)

_TEST_TAGS = frozenset(
    {
        "REAL_E2E_SMOKE",
        "REAL_E2E_SMOKE_5500",
        "SMOKE",
        "E2E_TEST",
        "MANUAL_TEST",
    }
)


def classify_checkpoint(n: int) -> str:
    if n < 30:
        return "INSUFFICIENT"
    if n < 50:
        return "SANITY_ONLY"
    if n < 100:
        return "EARLY_SIGNAL"
    if n < 200:
        return "CANDIDATE"
    if n < 300:
        return "VALIDATION"
    return "PROMOTION_REVIEW_ELIGIBLE"


def variant_grid() -> list[dict]:
    """Independent family variants (no Cartesian product)."""

    out: list[dict] = [
        {
            "strategy_family": FAMILY_BASELINE_MA,
            "variant_code": "MA_DEAD_CROSS",
            "threshold_value": None,
            "time_horizon_minutes": None,
        }
    ]
    for t in SL_THRESHOLDS:
        code = f"SL_{str(t).replace('.', '_').replace('-', 'm')}"
        out.append(
            {
                "strategy_family": FAMILY_STOP_LOSS,
                "variant_code": code,
                "threshold_value": Decimal(str(t)),
                "time_horizon_minutes": None,
            }
        )
    for t in TP_THRESHOLDS:
        code = f"TP_{str(t).replace('.', '_')}"
        out.append(
            {
                "strategy_family": FAMILY_TAKE_PROFIT,
                "variant_code": code,
                "threshold_value": Decimal(str(t)),
                "time_horizon_minutes": None,
            }
        )
    for t in TRAIL_THRESHOLDS:
        code = f"TRAIL_{str(t).replace('.', '_')}"
        out.append(
            {
                "strategy_family": FAMILY_TRAILING,
                "variant_code": code,
                "threshold_value": Decimal(str(t)),
                "time_horizon_minutes": None,
            }
        )
    for m in TIME_HORIZONS_MIN:
        out.append(
            {
                "strategy_family": FAMILY_TIME_EXIT,
                "variant_code": f"TIME_{m}M",
                "threshold_value": None,
                "time_horizon_minutes": int(m),
            }
        )
    return out
