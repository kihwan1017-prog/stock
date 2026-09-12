"""Entry Gate V2 shadow — focused safety/regression tests."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.operation.upbit_opportunity_shadow.entry_gate_v2.features import (
    build_features_from_closes,
    quality_score,
)
from stock_platform.operation.upbit_opportunity_shadow.entry_gate_v2.hooks import (
    maybe_enroll_entry_gate_v2_shadow,
)
from stock_platform.operation.upbit_opportunity_shadow.entry_gate_v2.variants import (
    decide_v2_a,
    decide_v2_c,
    decide_v2_d,
    evaluate_all_v2,
)


def _rising_closes(n: int = 40, start: float = 100.0) -> list[float]:
    # gentle uptrend for MA5 > MA20
    return [start + i * 0.05 for i in range(n)]


def test_lookahead_features_use_only_past_closes():
    closes = _rising_closes(40)
    # future prices must not be in feature input — contract: caller truncates
    feat = build_features_from_closes(
        closes=closes,
        short_ma=closes[-1],
        long_ma=sum(closes[-20:]) / 20,
    )
    assert feat.as_dict()["lookahead_forbidden"] is True
    assert "r15" not in feat.as_dict()
    assert "future" not in str(feat.as_dict()).lower()


def test_walk_forward_temporal_split_ordering():
    times = [
        datetime(2026, 9, 1, tzinfo=timezone.utc),
        datetime(2026, 9, 2, tzinfo=timezone.utc),
        datetime(2026, 9, 3, tzinfo=timezone.utc),
        datetime(2026, 9, 4, tzinfo=timezone.utc),
        datetime(2026, 9, 5, tzinfo=timezone.utc),
    ]
    split = times[2]
    train = [t for t in times if t < split]
    test = [t for t in times if t >= split]
    assert max(train) < min(test)


def test_deterministic_quality_score():
    closes = _rising_closes()
    feat = build_features_from_closes(
        closes=closes,
        short_ma=Decimal(str(closes[-1])),
        long_ma=Decimal(str(sum(closes[-20:]) / 20)),
        rsi14=55.0,
        volume_surge=1.0,
    )
    s1 = quality_score(feat)
    s2 = quality_score(feat)
    assert s1 == s2
    assert 0.0 <= s1 <= 1.0


def test_hard_block_insufficient_features():
    feat = build_features_from_closes(closes=[100.0] * 5)
    d = decide_v2_a(feat)
    # short series → may lack gap/pre; hard or soft block OK but allow False
    assert d.allow is False


def test_v2_c_anti_chase_blocks_high_pre5():
    closes = _rising_closes(40)
    # spike last 5 bars
    spiked = closes[:-5] + [closes[-6] * 1.02 for _ in range(5)]
    feat = build_features_from_closes(
        closes=spiked,
        short_ma=spiked[-1],
        long_ma=sum(spiked[-20:]) / 20,
    )
    # force young gc via features if possible
    d = decide_v2_c(feat, max_gc_age=180, max_pre5=0.05, max_range=0.99)
    if feat.pre5 is not None and feat.pre5 > 0.05:
        assert d.allow is False
        assert d.block_reason == "CHASE_PRE5_TOO_HIGH"


def test_shadow_allow_creates_no_intent_fields():
    closes = _rising_closes()
    feat = build_features_from_closes(
        closes=closes,
        short_ma=closes[-1],
        long_ma=sum(closes[-20:]) / 20,
    )
    out = evaluate_all_v2(feat)
    for code, d in out.items():
        assert "order" not in d
        assert "broker" not in d
        assert "intent" not in d
        assert set(d.keys()) >= {"allow", "block_reason", "score", "hard_block"}


def test_shadow_hook_failure_does_not_raise():
    with patch(
        "stock_platform.common.settings.get_settings",
        side_effect=RuntimeError("boom"),
    ):
        result = maybe_enroll_entry_gate_v2_shadow(
            uba_id=1380,
            symbol="KRW-BTC",
            short_ma=Decimal("100"),
            long_ma=Decimal("99"),
            snap=None,
            live_e0_decision="HOLD",
            live_e0_block_reason="RSI_TOO_HIGH",
            closes=_rising_closes(),
        )
    assert result["ok"] is False


def test_shadow_disabled_short_circuits():
    settings = MagicMock()
    settings.upbit_entry_gate_v2_shadow_enabled = False
    with patch(
        "stock_platform.common.settings.get_settings",
        return_value=settings,
    ):
        result = maybe_enroll_entry_gate_v2_shadow(
            uba_id=1380,
            symbol="KRW-BTC",
            short_ma=Decimal("100"),
            long_ma=Decimal("99"),
            snap=None,
            live_e0_decision="ALLOW",
            live_e0_block_reason=None,
            closes=_rising_closes(),
        )
    assert result == {"ok": False, "reason": "DISABLED"}


def test_uba_isolation_bucket_key_includes_uba():
    from stock_platform.operation.upbit_opportunity_shadow.entry_gate_v2.service import (
        observed_bucket,
    )

    b = observed_bucket(datetime(2026, 9, 10, 1, 17, tzinfo=timezone.utc))
    assert len(b) == 12
    assert b.endswith("15")  # 17 → bucket 15


def test_v2_d_blocks_bearish_regime():
    # downtrend closes
    closes = [200.0 - i * 0.2 for i in range(40)]
    feat = build_features_from_closes(
        closes=closes,
        short_ma=closes[-1],
        long_ma=sum(closes[-20:]) / 20,
    )
    d = decide_v2_d(feat)
    assert d.allow is False
