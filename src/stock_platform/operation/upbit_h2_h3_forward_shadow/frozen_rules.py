"""Immutable H2/H3 frozen rules from WRK-018 discovery edges.

QUANTILES_RECALCULATED must stay false — boundaries are fixed numbers.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

# Discovery 60% of WRK-017/018 research dataset (n_disc=54559), SAMPLE_EVERY=15m
# Q1 semantics: feature_value <= q1_upper_bound (inclusive)
FROZEN_FEATURE_DEFS: dict[str, dict[str, Any]] = {
    "dist_ma20_pct": {
        "lookback_ma_short": 5,
        "lookback_ma_long": 20,
        "formula": "(close / ma20 - 1) * 100",
        "q1_upper_bound": -0.20964360587002462,
        "edges_discovery": [
            -0.20964360587002462,
            -0.053531504865067525,
            0.04283179342838839,
            0.19764544126492645,
        ],
    },
    "ret_1m": {
        "lookback_minutes": 1,
        "formula": "(close[t] / close[t-1] - 1) * 100",
        "q1_upper_bound": -0.09191176470588758,
        "edges_discovery": [
            -0.09191176470588758,
            0.0,
            0.0,
            0.08912655971480277,
        ],
    },
    "dist_low_20_pct": {
        "lookback_minutes": 20,
        "formula": "(close / min(low[t-20:t]) - 1) * 100",
        "q1_upper_bound": 0.06131207847945852,
        "edges_discovery": [
            0.06131207847945852,
            0.189969604863216,
            0.38058991436726863,
            0.7597340930674212,
        ],
    },
}

# WRK-018 names
H2_NAME = "H2"
H2_LEGACY_NAME = "IX_dist_ma20_pct_1_ret_1m_1"
H3_NAME = "H3"
H3_LEGACY_NAME = "IX_ret_1m_1_dist_low_20_pct_1"

PRIMARY_HORIZON_MIN = 60  # WRK-018 primary — do not switch
OUTCOME_HORIZONS_MIN = (30, 60, 120)
SAMPLE_EVERY_MIN = 15  # WRK-018 opportunity grid
FEE_RATE = 0.0005
SLIP_BPS_BASELINE = 2.0

# Forward window starts when infrastructure is first activated (UTC).
# Historical discovery/test bars are NOT forward samples.
FORWARD_VALIDATION_STARTED_AT = datetime(2026, 8, 29, 1, 0, 0, tzinfo=timezone.utc)

RULE_VERSION = "wrk018_h2_h3_frozen_v1"


def _rule_payload(strategy: str) -> dict[str, Any]:
    if strategy == H2_NAME:
        return {
            "strategy": H2_NAME,
            "legacy_name": H2_LEGACY_NAME,
            "all_of": [
                {
                    "feature": "dist_ma20_pct",
                    "op": "<=",
                    "bound": FROZEN_FEATURE_DEFS["dist_ma20_pct"]["q1_upper_bound"],
                    "quantile_label": "Q1",
                },
                {
                    "feature": "ret_1m",
                    "op": "<=",
                    "bound": FROZEN_FEATURE_DEFS["ret_1m"]["q1_upper_bound"],
                    "quantile_label": "Q1",
                },
            ],
            "feature_defs": {
                "dist_ma20_pct": FROZEN_FEATURE_DEFS["dist_ma20_pct"],
                "ret_1m": FROZEN_FEATURE_DEFS["ret_1m"],
            },
            "primary_horizon_min": PRIMARY_HORIZON_MIN,
            "sample_every_min": SAMPLE_EVERY_MIN,
            "rule_version": RULE_VERSION,
            "quantiles_recalculated": False,
        }
    if strategy == H3_NAME:
        return {
            "strategy": H3_NAME,
            "legacy_name": H3_LEGACY_NAME,
            "all_of": [
                {
                    "feature": "ret_1m",
                    "op": "<=",
                    "bound": FROZEN_FEATURE_DEFS["ret_1m"]["q1_upper_bound"],
                    "quantile_label": "Q1",
                },
                {
                    "feature": "dist_low_20_pct",
                    "op": "<=",
                    "bound": FROZEN_FEATURE_DEFS["dist_low_20_pct"][
                        "q1_upper_bound"
                    ],
                    "quantile_label": "Q1",
                },
            ],
            "feature_defs": {
                "ret_1m": FROZEN_FEATURE_DEFS["ret_1m"],
                "dist_low_20_pct": FROZEN_FEATURE_DEFS["dist_low_20_pct"],
            },
            "primary_horizon_min": PRIMARY_HORIZON_MIN,
            "sample_every_min": SAMPLE_EVERY_MIN,
            "rule_version": RULE_VERSION,
            "quantiles_recalculated": False,
        }
    raise ValueError(f"unknown strategy {strategy}")


def rule_hash(strategy: str) -> str:
    raw = json.dumps(_rule_payload(strategy), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


H2_RULE = _rule_payload(H2_NAME)
H3_RULE = _rule_payload(H3_NAME)
H2_RULE_HASH = rule_hash(H2_NAME)
H3_RULE_HASH = rule_hash(H3_NAME)


def matches_frozen(strategy: str, features: dict[str, float]) -> bool:
    """Evaluate frozen bounds — never recompute quantiles."""

    payload = _rule_payload(strategy)
    for clause in payload["all_of"]:
        feat = str(clause["feature"])
        bound = float(clause["bound"])
        val = features.get(feat)
        if val is None:
            return False
        if float(val) > bound:  # Q1: x <= bound
            return False
    return True


def frozen_snapshot() -> dict[str, Any]:
    return {
        "H2_RULE": H2_RULE,
        "H2_RULE_HASH": H2_RULE_HASH,
        "H3_RULE": H3_RULE,
        "H3_RULE_HASH": H3_RULE_HASH,
        "FORWARD_VALIDATION_STARTED_AT": FORWARD_VALIDATION_STARTED_AT.isoformat(),
        "QUANTILES_RECALCULATED": False,
        "PRIMARY_HORIZON_MIN": PRIMARY_HORIZON_MIN,
    }
