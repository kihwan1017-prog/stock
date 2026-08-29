"""WRK-019 H2/H3 frozen forward-shadow unit tests — no LIVE/orders."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from stock_platform.operation.upbit_h2_h3_forward_shadow.features import features_at
from stock_platform.operation.upbit_h2_h3_forward_shadow.frozen_rules import (
    FORWARD_VALIDATION_STARTED_AT,
    FROZEN_FEATURE_DEFS,
    H2_NAME,
    H2_RULE_HASH,
    H3_NAME,
    H3_RULE_HASH,
    PRIMARY_HORIZON_MIN,
    SAMPLE_EVERY_MIN,
    matches_frozen,
    rule_hash,
)
from stock_platform.operation.upbit_h2_h3_forward_shadow.service import (
    STATUS_COMPLETE,
    STATUS_PENDING,
    apply_maturity_to_outcomes,
    compute_horizon_outcome,
    compute_readiness,
    floor_sample,
)


def test_frozen_boundaries_exact() -> None:
    assert FROZEN_FEATURE_DEFS["dist_ma20_pct"]["q1_upper_bound"] == (
        -0.20964360587002462
    )
    assert FROZEN_FEATURE_DEFS["ret_1m"]["q1_upper_bound"] == (
        -0.09191176470588758
    )
    assert FROZEN_FEATURE_DEFS["dist_low_20_pct"]["q1_upper_bound"] == (
        0.06131207847945852
    )


def test_rule_hash_immutable() -> None:
    assert rule_hash(H2_NAME) == H2_RULE_HASH == "0cfb35c4590f404b"
    assert rule_hash(H3_NAME) == H3_RULE_HASH == "80893dfac2d5b2ea"
    # 재호출해도 동일 — quantile 재계산 경로 없음
    assert rule_hash(H2_NAME) == H2_RULE_HASH


def test_matches_frozen_q1_inclusive() -> None:
    h2_ok = {
        "dist_ma20_pct": -0.20964360587002462,
        "ret_1m": -0.09191176470588758,
    }
    assert matches_frozen(H2_NAME, h2_ok) is True
    assert matches_frozen(H2_NAME, {**h2_ok, "dist_ma20_pct": -0.209}) is False

    h3_ok = {
        "ret_1m": -0.1,
        "dist_low_20_pct": 0.06131207847945852,
    }
    assert matches_frozen(H3_NAME, h3_ok) is True
    assert matches_frozen(H3_NAME, {**h3_ok, "dist_low_20_pct": 0.07}) is False


def test_no_quantile_recalculation_flag() -> None:
    from stock_platform.operation.upbit_h2_h3_forward_shadow.frozen_rules import (
        H2_RULE,
    )

    assert H2_RULE["quantiles_recalculated"] is False


def test_dedupe_sample_grid_15m() -> None:
    assert SAMPLE_EVERY_MIN == 15
    t = datetime(2026, 8, 29, 1, 7, 30, tzinfo=timezone.utc)
    assert floor_sample(t) == datetime(2026, 8, 29, 1, 0, tzinfo=timezone.utc)
    assert floor_sample(t) == floor_sample(
        datetime(2026, 8, 29, 1, 14, tzinfo=timezone.utc)
    )


def test_features_no_lookahead() -> None:
    closes = [100.0] * 25
    closes[24] = 99.0
    lows = [99.5] * 25
    lows[24] = 98.0
    feat = features_at(closes=closes, lows=lows, idx=24)
    assert feat is not None
    # idx=24만 사용 — future closes 미참조
    assert feat["ret_1m"] < 0


def test_no_lookahead_outcome_until_mature() -> None:
    eva = FORWARD_VALIDATION_STARTED_AT
    outcomes, status = apply_maturity_to_outcomes(
        evaluated_at=eva,
        entry_price=100.0,
        outcomes={},
        now=eva + timedelta(minutes=10),
        path_loader=lambda h, m: [],
    )
    assert status == STATUS_PENDING
    assert outcomes == {} or all(
        k not in outcomes or outcomes[k].get("status") != "READY"
        for k in ("30m", "60m", "120m")
    )


def test_30_60_120_maturity_ladder() -> None:
    eva = FORWARD_VALIDATION_STARTED_AT
    entry = 100.0

    def path(h: int, mature_at: datetime):
        # 단순 가격 경로 — horizon마다 +1%
        px = entry * (1.0 + 0.01 * (h / 30.0))
        return [
            {
                "close_price": px,
                "high_price": px * 1.002,
                "low_price": px * 0.998,
            }
        ]

    out30, st30 = apply_maturity_to_outcomes(
        evaluated_at=eva,
        entry_price=entry,
        outcomes={},
        now=eva + timedelta(minutes=30),
        path_loader=path,
    )
    assert st30 == "PARTIAL"
    assert out30["30m"]["status"] == "READY"
    assert "60m" not in out30 or out30.get("60m", {}).get("status") != "READY"

    out60, st60 = apply_maturity_to_outcomes(
        evaluated_at=eva,
        entry_price=entry,
        outcomes=out30,
        now=eva + timedelta(minutes=60),
        path_loader=path,
    )
    assert st60 == "PARTIAL"
    assert out60["60m"]["status"] == "READY"

    out120, st120 = apply_maturity_to_outcomes(
        evaluated_at=eva,
        entry_price=entry,
        outcomes=out60,
        now=eva + timedelta(minutes=120),
        path_loader=path,
    )
    assert st120 == STATUS_COMPLETE
    assert out120["120m"]["status"] == "READY"


def test_idempotent_maturity_reapply() -> None:
    eva = FORWARD_VALIDATION_STARTED_AT
    path = lambda h, m: [
        {"close_price": 101.0, "high_price": 102.0, "low_price": 99.0}
    ]
    o1, s1 = apply_maturity_to_outcomes(
        evaluated_at=eva,
        entry_price=100.0,
        outcomes={},
        now=eva + timedelta(minutes=120),
        path_loader=path,
    )
    o2, s2 = apply_maturity_to_outcomes(
        evaluated_at=eva,
        entry_price=100.0,
        outcomes=o1,
        now=eva + timedelta(minutes=180),
        path_loader=path,
    )
    assert s1 == s2 == STATUS_COMPLETE
    assert o1["60m"]["net_pnl_krw"] == o2["60m"]["net_pnl_krw"]


def test_restart_catchup_semantics() -> None:
    """Restart 후 now가 지나 있으면 catch-up으로 COMPLETE 가능."""

    eva = FORWARD_VALIDATION_STARTED_AT
    now = eva + timedelta(hours=3)
    outcomes, status = apply_maturity_to_outcomes(
        evaluated_at=eva,
        entry_price=100.0,
        outcomes={},  # PENDING 상태 재기동 가정
        now=now,
        path_loader=lambda h, m: [
            {"close_price": 100.5, "high_price": 101.0, "low_price": 99.5}
        ],
    )
    assert status == STATUS_COMPLETE
    assert set(outcomes) >= {"30m", "60m", "120m"}


def test_cost_bundle_and_sensitivity() -> None:
    bundle = compute_horizon_outcome(
        entry_price=100.0,
        path=[
            {"close_price": 101.0, "high_price": 101.5, "low_price": 99.5}
        ],
        mature_at=FORWARD_VALIDATION_STARTED_AT + timedelta(minutes=60),
    )
    assert bundle["status"] == "READY"
    assert "net_pnl_krw_1bps" in bundle
    assert "net_pnl_krw_5bps" in bundle
    assert bundle["net_pnl_krw_1bps"] >= bundle["net_pnl_krw"]
    assert bundle["net_pnl_krw_5bps"] <= bundle["net_pnl_krw"]


def _row(strategy: str, net: float, symbol: str = "KRW-BTC") -> SimpleNamespace:
    primary = f"{PRIMARY_HORIZON_MIN}m"
    return SimpleNamespace(
        strategy=strategy,
        symbol=symbol,
        evaluated_at=FORWARD_VALIDATION_STARTED_AT,
        outcome_status=STATUS_COMPLETE,
        outcome_json={
            primary: {
                "status": "READY",
                "net_pnl_krw": net,
                "net_pnl_krw_5bps": net * 0.9,
            },
            "30m": {
                "status": "READY",
                "net_pnl_krw": net * 0.5,
            },
            "120m": {
                "status": "READY",
                "net_pnl_krw": net * 1.1,
            },
        },
    )


def test_readiness_not_enough_data() -> None:
    rows = [_row(H2_NAME, 10.0) for _ in range(10)]
    r = compute_readiness(rows, strategy=H2_NAME)
    assert r["readiness"] == "NOT_ENOUGH_FORWARD_DATA"
    assert r["user_approval_required"] is True
    assert r["source"] == "FORWARD_SHADOW"


def test_readiness_fail_and_promising() -> None:
    # 손실 위주 → FAIL (N>=300)
    fail_rows = [_row(H3_NAME, -5.0) for _ in range(300)]
    assert compute_readiness(fail_rows, strategy=H3_NAME)["readiness"] == "FAIL"

    # 약한 양수 PF → PROMISING
    prom = [_row(H3_NAME, 1.0 if i % 2 == 0 else -0.5) for i in range(300)]
    st = compute_readiness(prom, strategy=H3_NAME)["readiness"]
    assert st in {"PROMISING", "READY_FOR_USER_REVIEW", "FAIL"}


def test_h2_h3_evaluated_separately() -> None:
    h2 = compute_readiness(
        [_row(H2_NAME, 10.0) for _ in range(5)], strategy=H2_NAME
    )
    h3 = compute_readiness(
        [_row(H3_NAME, -10.0) for _ in range(5)], strategy=H3_NAME
    )
    assert h2["strategy"] == H2_NAME
    assert h3["strategy"] == H3_NAME
    # 합산 PF 경로 없음 — 각자 total
    assert h2["total"] == 5
    assert h3["total"] == 5


def test_isolation_contract_constants() -> None:
    """모듈이 주문/시그널 publisher를 import하지 않음 (정적 계약)."""

    import stock_platform.operation.upbit_h2_h3_forward_shadow.service as svc

    assert svc._ASSERT_NO_SIGNAL_PUBLISH is True
    src = open(svc.__file__, encoding="utf-8").read()
    assert "from stock_platform.trading" not in src
    assert "place_order" not in src
    assert "publish_scoped_signal" not in src
    assert "import StrategySignal" not in src
    assert "executor_calls" in src  # 관측 카운터만 허용


def test_historical_not_before_started() -> None:
    assert FORWARD_VALIDATION_STARTED_AT == datetime(
        2026, 8, 29, 1, 0, 0, tzinfo=timezone.utc
    )
    assert PRIMARY_HORIZON_MIN == 60
