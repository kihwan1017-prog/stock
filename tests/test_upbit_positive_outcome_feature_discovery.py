"""WRK-018 feature discovery unit tests."""

from __future__ import annotations

from stock_platform.operation.upbit_feature_discovery.stats import (
    assign_quintile,
    effect_size,
    period_bucket,
    profit_concentration,
    quintile_edges,
)


def test_effect_size_direction() -> None:
    a = [1.0, 2.0, 3.0, 4.0, 5.0]
    b = [0.0, 0.5, 1.0, 1.5, 2.0]
    d = effect_size(a, b)
    assert d is not None and d > 0


def test_quintile_assignment() -> None:
    xs = list(range(100))
    edges = quintile_edges([float(x) for x in xs])
    assert edges is not None and len(edges) == 4
    assert assign_quintile(0.0, edges) == 1
    assert assign_quintile(99.0, edges) == 5


def test_profit_concentration_and_periods() -> None:
    c = profit_concentration([10.0, 5.0, -2.0, 1.0])
    assert c["top1"] == 10.0 / 16.0
    assert period_bucket(0.1) == "EARLY"
    assert period_bucket(0.5) == "MIDDLE"
    assert period_bucket(0.9) == "LATE"


def test_label_isolation_contract() -> None:
    """Features dict must not include future net keys in naming convention."""

    feat = {"ret_15m": 1.0, "volume_surge": 1.2}
    assert "net_60" not in feat
    assert "mfe_60" not in feat
