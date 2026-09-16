"""품질 telemetry. 전략 차단이 아니라 관찰 기록만."""

from __future__ import annotations

from typing import Any

# 하드코딩 차단 목록이 아님. 품질 관찰용 라벨만.
PEGGED_OR_STABLE_SUFFIXES = (
    "USDT",
    "USDC",
    "USDS",
    "USD1",
    "DAI",
    "TUSD",
    "USDP",
    "FDUSD",
    "XAUT",
    "PAXG",
)


def classify_quality(
    *,
    symbol: str,
    change_rate: float | None,
    range_pct: float | None,
    fee_churn_risk: str | None,
    recommendation: str | None,
) -> dict[str, Any]:
    """왜 ALLOW/HOLD가 나왔는지 나중에 볼 수 있게 기록."""

    base = str(symbol or "").upper().replace("KRW-", "")
    stable = any(base == suffix or base.endswith(suffix) for suffix in PEGGED_OR_STABLE_SUFFIXES)
    low_vol = False
    if change_rate is not None and range_pct is not None:
        low_vol = abs(change_rate) < 0.008 and range_pct < 0.02
    elif change_rate is not None:
        low_vol = abs(change_rate) < 0.008
    rec = str(recommendation or "").upper()
    return {
        "stable_or_pegged_asset": stable,
        "low_volatility": low_vol,
        "low_expected_edge": bool(stable or low_vol),
        "fee_churn_risk": str(fee_churn_risk or "").upper() or None,
        "recommendation": rec or None,
        "low_volatility_allow": bool(low_vol and rec == "ALLOW"),
        "blocked_by_hardcode": False,
    }
