"""STEP 12-13 — Portfolio Validation.

복수의 승인된 Strategy Definition과 기존 Backtest 결과(이미 완료됨)만
조합한다. 새 Backtest를 실행하지 않고, Weight를 자동 최적화하지 않으며,
실제 Portfolio/자금 배분을 생성하지 않는다."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from stock_platform.ai.strategy_draft.service import StrategyDraftService
from stock_platform.ai.strategy_draft_approval.portfolio_validation import (
    MAX_STRATEGIES,
    METHODOLOGY_NOTE,
    MIN_STRATEGIES,
    PortfolioValidationError,
    StrategyBacktestBundle,
    align_equity_curves,
    compute_concentration,
    compute_correlation_matrix,
    compute_diversification_benefit,
    compute_pairwise_correlation,
    compute_portfolio_equity_curve,
    compute_portfolio_kpi,
    compute_portfolio_returns,
    compute_portfolio_robustness_score,
    compute_report_input_hash,
    compute_return_series,
    compute_risk_contribution,
    detect_duplicate_exposures,
    determine_validation_status,
    find_highly_correlated_pairs,
    get_portfolio_validation_report,
    resolve_weights,
    run_portfolio_validation,
    validate_strategy_count_and_uniqueness,
)
from stock_platform.ai.strategy_draft_approval.service import (
    StrategyDraftApprovalService,
)
from stock_platform.ai.strategy_request.service import StrategyRequestService
from stock_platform.api.main import app
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory
from stock_platform.performance.backtest_analytics import EquityPoint

pytestmark = pytest.mark.integration

_REQUESTER_USER_ID = 8
_REVIEWER_USER_ID = 7
_MARKER = "STEP12_13_TEST"
_TEST_EXCHANGE = "KRX"


@pytest.fixture()
def result_ids() -> list[int]:
    Session = get_session_factory()
    s = Session()
    try:
        rows = s.execute(
            text("SELECT result_id FROM strategy.candidate_result ORDER BY result_id LIMIT 5")
        ).fetchall()
        ids = [int(r[0]) for r in rows]
        if len(ids) < 2:
            pytest.skip("strategy.candidate_result에 2개 이상의 테스트용 행이 없어 스킵")
        return ids
    finally:
        s.close()


_CLEANUP_SQL = [
    # API를 통해 생성된 행은 requested_by가 테스트 마커가 아니라 실제
    # admin 사용자명이라(§ STEP12-14 작업 중 발견) 패턴 매칭이 아니라
    # Strategy 소유 체인으로 걸러야 한다.
    "DELETE FROM trading.portfolio_validation_report pvr WHERE EXISTS ("
    "SELECT 1 FROM jsonb_array_elements(pvr.strategy_definition_ids) AS elem "
    "WHERE (elem.value)::bigint IN ("
    "SELECT strategy_id FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker)))",
    "DELETE FROM trading.monte_carlo_simulation_report WHERE strategy_id IN "
    "(SELECT strategy_id FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))",
    "DELETE FROM trading.parameter_sensitivity_report WHERE strategy_id IN "
    "(SELECT strategy_id FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))",
    "DELETE FROM trading.strategy_quality_gate_report WHERE strategy_id IN "
    "(SELECT strategy_id FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))",
    "DELETE FROM backtest.backtest_trade WHERE backtest_run_id IN "
    "(SELECT backtest_run_id FROM backtest.backtest_run WHERE strategy_definition_id IN "
    "(SELECT strategy_id FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker)))",
    "DELETE FROM backtest.backtest_equity WHERE backtest_run_id IN "
    "(SELECT backtest_run_id FROM backtest.backtest_run WHERE strategy_definition_id IN "
    "(SELECT strategy_id FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker)))",
    "DELETE FROM backtest.backtest_run WHERE strategy_definition_id IN "
    "(SELECT strategy_id FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))",
    "DELETE FROM ai.strategy_draft_approval_history WHERE approval_id IN "
    "(SELECT approval_id FROM ai.strategy_draft_approval WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))",
    "UPDATE trading.strategy_definition SET approval_id = NULL WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker)",
    "DELETE FROM ai.strategy_draft_approval WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker)",
    "DELETE FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker)",
    "DELETE FROM ai.strategy_draft_history WHERE draft_id IN "
    "(SELECT draft_id FROM ai.strategy_draft WHERE strategy_request_id IN "
    "(SELECT strategy_request_id FROM ai.strategy_request WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker)))",
    "DELETE FROM ai.strategy_draft WHERE strategy_request_id IN "
    "(SELECT strategy_request_id FROM ai.strategy_request WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))",
    "DELETE FROM ai.strategy_request_history WHERE strategy_request_id IN "
    "(SELECT strategy_request_id FROM ai.strategy_request WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))",
    "DELETE FROM ai.strategy_request WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker)",
    "DELETE FROM ai.candidate_lifecycle WHERE created_by = :marker",
    "DELETE FROM strategy.candidate_result WHERE symbol LIKE 'STEP1213SYN%'",
    "DELETE FROM market.price_daily WHERE instrument_id IN "
    "(SELECT instrument_id FROM market.instrument WHERE symbol LIKE 'STEP1213%')",
    "DELETE FROM market.instrument WHERE symbol LIKE 'STEP1213%'",
]


def _cleanup(s) -> None:
    for sql in _CLEANUP_SQL:
        s.execute(text(sql), {"marker": _MARKER})
    s.commit()


@pytest.fixture()
def session(result_ids: list[int]):
    Session = get_session_factory()
    s = Session()
    try:
        s.info["result_ids"] = result_ids
        _cleanup(s)
        yield s
    finally:
        s.rollback()
        _cleanup(s)
        s.close()


def _seed_prices(session, symbol: str, closes: list[float], *, start: date) -> None:
    instrument_id = session.execute(
        text(
            """
            INSERT INTO market.instrument (asset_type, exchange_code, symbol, name)
            VALUES ('STOCK', :exchange, :symbol, 'STEP12-13 Test')
            RETURNING instrument_id
            """
        ),
        {"exchange": _TEST_EXCHANGE, "symbol": symbol},
    ).scalar_one()
    for i, close in enumerate(closes):
        trade_date = start + timedelta(days=i)
        session.execute(
            text(
                """
                INSERT INTO market.price_daily
                (instrument_id, trade_date, open_price, high_price, low_price, close_price, volume, source)
                VALUES (:iid, :td, :c, :c, :c, :c, 1000, 'STEP12_13_TEST')
                """
            ),
            {"iid": instrument_id, "td": trade_date, "c": Decimal(str(close))},
        )
    session.commit()


def _triangle_wave(num_days: int, *, period: int = 30, low: float = 50.0, high: float = 100.0, phase_shift: int = 0) -> list[float]:
    half = period // 2
    closes: list[float] = []
    for i in range(num_days):
        phase = (i + phase_shift) % period
        if phase < half:
            value = low + (high - low) * (phase / half)
        else:
            value = high - (high - low) * ((phase - half) / half)
        closes.append(round(value, 2))
    return closes


def _create_candidate(session, *, result_id: int) -> int:
    candidate_id = session.execute(
        text(
            """
            INSERT INTO ai.candidate_lifecycle
            (candidate_id, lifecycle_status, health_status, source_fingerprint, created_by, updated_by)
            VALUES (:cid, 'PROMOTED', 'UNKNOWN', :fp, :marker, :marker)
            RETURNING candidate_id
            """
        ),
        {"cid": result_id, "fp": f"{result_id:064d}", "marker": _MARKER},
    ).scalar_one()
    session.commit()
    return int(candidate_id)


def _create_approved_request(session, *, result_id: int) -> dict:
    candidate_id = _create_candidate(session, result_id=result_id)
    req = StrategyRequestService(session).create(
        candidate_id=candidate_id, user_id=_REQUESTER_USER_ID, request_note=None,
        actor=f"user:{_REQUESTER_USER_ID}",
    )
    return StrategyRequestService(session).approve(
        req["strategy_request_id"], reviewer_user_id=_REVIEWER_USER_ID, review_note="ok",
        actor=f"admin:{_REVIEWER_USER_ID}",
    )


def _approve(session, strategy_request_id: int, *, entry_threshold: float = 30, exit_threshold: float = 70) -> dict:
    draft = StrategyDraftService(session).create(
        strategy_request_id=strategy_request_id, actor="admin:7", title="수동 초안",
        timeframe="1D", market_type="KR_STOCK",
        entry_rule=f'[{{"indicator":"RSI","operator":"LT","threshold":{entry_threshold},"lookback":14}}]',
        exit_rule=f'[{{"indicator":"RSI","operator":"GT","threshold":{exit_threshold},"lookback":14}}]',
        stop_loss_rule='{"type":"PERCENT","value":5}', take_profit_rule='{"type":"PERCENT","value":10}',
        position_sizing_rule='{"method":"FIXED_PERCENT","value":0.1}',
    )
    return StrategyDraftApprovalService(session).approve(draft["draft_id"], actor="admin:7", reason="승인")


def _run_backtest(session, strategy_definition_id: int, symbol: str, num_days: int) -> int:
    from stock_platform.ai.strategy_draft_approval.backtest_execution import (
        run_definition_backtest,
    )

    result = run_definition_backtest(
        session, strategy_definition_id,
        runtime_input={
            "symbol": symbol, "exchange_code": _TEST_EXCHANGE,
            "start_date": date(2024, 1, 1), "end_date": date(2024, 1, 1) + timedelta(days=num_days),
            "initial_capital": Decimal("1000000"), "fee_ratio": Decimal("0.00015"),
            "sell_tax_ratio": Decimal("0.0018"), "slippage_ratio": Decimal("0"),
        },
        actor="STEP12_13_TEST:admin",
    )
    return result["backtest_run_id"]


def _synthesize_candidate_result_ids(session, count: int, *, base_rank_no: int = 900) -> list[int]:
    """STEP12-13 인수 조건 §5 — dev DB의 실제 strategy.candidate_result 행
    수(정확히 2개)에 의존하지 않고 3~10개 Strategy 통합 테스트를 만들기
    위해, 기존 candidate_run(run_id=1, 어떤 candidate_result도 아직
    참조하지 않음)에 새 candidate_result 행을 결정적으로 추가한다. 기존
    운영 데이터(run_id/기존 result 2건)는 전혀 건드리지 않는다."""
    run_id = 1
    ids: list[int] = []
    for i in range(count):
        result_id = session.execute(
            text(
                """
                INSERT INTO strategy.candidate_result
                (run_id, rank_no, exchange_code, symbol, trade_date, total_score,
                 rules_passed_count, all_rules_passed, rule_result, score_breakdown)
                VALUES (:run_id, :rank_no, 'KRX', :symbol, :trade_date, 50,
                        1, true, '{}'::jsonb, '{}'::jsonb)
                RETURNING result_id
                """
            ),
            {
                "run_id": run_id,
                "rank_no": base_rank_no + i,
                "symbol": f"STEP1213SYN{i}",
                "trade_date": date(2026, 7, 14),
            },
        ).scalar_one()
        ids.append(int(result_id))
    session.commit()
    return ids


def _seed_n_correlated_strategies(session, n: int) -> tuple[list[int], list[int]]:
    """전략 n개를 전부 동일 Symbol+동일 Rule로 만들어 모든 Pair가 동시에
    HIGH Correlation과 HIGH Duplicate Exposure를 갖도록 한다(3~10개
    경계값과 "복수 고상관 Pair"/"복수 HIGH Duplicate Exposure"를 최소
    구성으로 동시에 재현)."""
    ids = _synthesize_candidate_result_ids(session, n)
    num_days = 160
    _seed_prices(session, "STEP1213SYN", _triangle_wave(num_days, period=30), start=date(2024, 1, 1))

    strategy_ids: list[int] = []
    backtest_ids: list[int] = []
    for result_id in ids:
        req = _create_approved_request(session, result_id=result_id)
        approval = _approve(session, req["strategy_request_id"], entry_threshold=30, exit_threshold=70)
        run_id = _run_backtest(session, approval["strategy_definition_id"], "STEP1213SYN", num_days)
        strategy_ids.append(approval["strategy_definition_id"])
        backtest_ids.append(run_id)
    return strategy_ids, backtest_ids


def _seed_two_strategies(session) -> tuple[list[int], list[int]]:
    """전략 A/B는 동일 Symbol+동일 Rule(중복 노출 HIGH 재현용). dev DB의
    strategy.candidate_result가 정확히 2개 행만 갖고 있어(조사 결과)
    MIN_STRATEGIES=2 경계값 자체를 검증하는 구성으로 둔다."""
    ids = session.info["result_ids"]
    num_days = 160

    _seed_prices(session, "STEP1213A", _triangle_wave(num_days, period=30), start=date(2024, 1, 1))

    req_a = _create_approved_request(session, result_id=ids[0])
    approval_a = _approve(session, req_a["strategy_request_id"], entry_threshold=30, exit_threshold=70)
    run_a = _run_backtest(session, approval_a["strategy_definition_id"], "STEP1213A", num_days)

    req_b = _create_approved_request(session, result_id=ids[1])
    approval_b = _approve(session, req_b["strategy_request_id"], entry_threshold=30, exit_threshold=70)
    run_b = _run_backtest(session, approval_b["strategy_definition_id"], "STEP1213A", num_days)

    strategy_ids = [approval_a["strategy_definition_id"], approval_b["strategy_definition_id"]]
    backtest_ids = [run_a, run_b]
    return strategy_ids, backtest_ids


# ---------------------------------------------------------------------------
# A: Weight Validation
# ---------------------------------------------------------------------------


def test_equal_weight_sums_to_exactly_one() -> None:
    weights = resolve_weights(strategy_definition_ids=[5, 3, 8, 1], weighting_method="EQUAL_WEIGHT", strategy_weights=None)
    assert sum(weights.values()) == Decimal("1")
    assert len(weights) == 4


def test_equal_weight_deterministic_regardless_of_input_order() -> None:
    w1 = resolve_weights(strategy_definition_ids=[1, 2, 3], weighting_method="EQUAL_WEIGHT", strategy_weights=None)
    w2 = resolve_weights(strategy_definition_ids=[3, 1, 2], weighting_method="EQUAL_WEIGHT", strategy_weights=None)
    assert w1 == w2


def test_custom_weight_valid_sum_accepted() -> None:
    weights = resolve_weights(
        strategy_definition_ids=[1, 2], weighting_method="CUSTOM_WEIGHT",
        strategy_weights={1: Decimal("0.6"), 2: Decimal("0.4")},
    )
    assert weights == {1: Decimal("0.6"), 2: Decimal("0.4")}


def test_custom_weight_missing_strategy_blocked() -> None:
    with pytest.raises(PortfolioValidationError) as exc_info:
        resolve_weights(
            strategy_definition_ids=[1, 2, 3], weighting_method="CUSTOM_WEIGHT",
            strategy_weights={1: Decimal("0.5"), 2: Decimal("0.5")},
        )
    assert exc_info.value.code == "MISSING_WEIGHT"


def test_custom_weight_zero_or_negative_blocked() -> None:
    with pytest.raises(PortfolioValidationError) as exc_info:
        resolve_weights(
            strategy_definition_ids=[1, 2], weighting_method="CUSTOM_WEIGHT",
            strategy_weights={1: Decimal("1.0"), 2: Decimal("0")},
        )
    assert exc_info.value.code == "INVALID_WEIGHT"


def test_custom_weight_bad_sum_blocked_not_silently_normalized() -> None:
    with pytest.raises(PortfolioValidationError) as exc_info:
        resolve_weights(
            strategy_definition_ids=[1, 2], weighting_method="CUSTOM_WEIGHT",
            strategy_weights={1: Decimal("0.5"), 2: Decimal("0.6")},
        )
    assert exc_info.value.code == "INVALID_WEIGHT_SUM"


def test_strategy_count_boundaries() -> None:
    validate_strategy_count_and_uniqueness([1, 2], [10, 20])
    validate_strategy_count_and_uniqueness(list(range(MAX_STRATEGIES)), list(range(100, 100 + MAX_STRATEGIES)))
    with pytest.raises(PortfolioValidationError) as exc_info:
        validate_strategy_count_and_uniqueness([1], [10])
    assert exc_info.value.code == "TOO_FEW_STRATEGIES"
    with pytest.raises(PortfolioValidationError) as exc_info:
        validate_strategy_count_and_uniqueness(list(range(MAX_STRATEGIES + 1)), list(range(100, 100 + MAX_STRATEGIES + 1)))
    assert exc_info.value.code == "TOO_MANY_STRATEGIES"


def test_duplicate_strategy_blocked() -> None:
    with pytest.raises(PortfolioValidationError) as exc_info:
        validate_strategy_count_and_uniqueness([1, 1], [10, 20])
    assert exc_info.value.code == "DUPLICATE_STRATEGY"


def test_duplicate_backtest_run_blocked() -> None:
    with pytest.raises(PortfolioValidationError) as exc_info:
        validate_strategy_count_and_uniqueness([1, 2], [10, 10])
    assert exc_info.value.code == "DUPLICATE_BACKTEST_RUN"


# ---------------------------------------------------------------------------
# B: Return Series / Portfolio Equity
# ---------------------------------------------------------------------------


def test_return_series_actual_values_and_excludes_first() -> None:
    returns = compute_return_series([Decimal("100"), Decimal("110"), Decimal("99")])
    assert returns == [Decimal("0.1"), Decimal("-0.1")]


def test_return_series_blocks_non_positive_equity() -> None:
    with pytest.raises(PortfolioValidationError) as exc_info:
        compute_return_series([Decimal("100"), Decimal("0"), Decimal("50")])
    assert exc_info.value.code == "INVALID_EQUITY_VALUE"


def test_portfolio_returns_weighted_sum() -> None:
    returns = {1: [Decimal("0.1"), Decimal("-0.05")], 2: [Decimal("0.02"), Decimal("0.03")]}
    weights = {1: Decimal("0.6"), 2: Decimal("0.4")}
    result = compute_portfolio_returns(strategy_returns=returns, weights=weights)
    assert result[0] == Decimal("0.1") * Decimal("0.6") + Decimal("0.02") * Decimal("0.4")
    assert result[1] == Decimal("-0.05") * Decimal("0.6") + Decimal("0.03") * Decimal("0.4")


def test_portfolio_equity_curve_daily_rebalancing() -> None:
    dates = [date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3)]
    curve = compute_portfolio_equity_curve(
        initial_capital=Decimal("1000000"), portfolio_returns=[Decimal("0.1"), Decimal("-0.05")], dates=dates,
    )
    assert curve[0].equity_value == Decimal("1000000")
    assert curve[1].equity_value == Decimal("1100000.0")
    assert curve[2].equity_value == Decimal("1100000.0") * Decimal("0.95")


def test_portfolio_kpi_total_return_and_cagr_exact_365_days() -> None:
    curve = [
        EquityPoint(date(2023, 1, 1), Decimal("1000")),
        EquityPoint(date(2024, 1, 1), Decimal("1200")),
    ]
    kpi = compute_portfolio_kpi(curve, Decimal("1000"))
    assert kpi["total_return"] == Decimal("20.0000")
    assert kpi["cagr"] == Decimal("20.0000")
    assert kpi["profit_factor"] is None
    assert kpi["trade_count"] is None


# ---------------------------------------------------------------------------
# C: Correlation
# ---------------------------------------------------------------------------


def test_correlation_self_is_one_and_symmetric() -> None:
    returns = {
        1: [Decimal("0.01"), Decimal("0.02"), Decimal("-0.01"), Decimal("0.03")],
        2: [Decimal("0.02"), Decimal("0.04"), Decimal("-0.02"), Decimal("0.06")],
    }
    result = compute_correlation_matrix([1, 2], returns)
    assert result["matrix"][1][1] == str(Decimal("1"))
    assert result["matrix"][1][2] == result["matrix"][2][1]


def test_correlation_perfect_positive_and_negative() -> None:
    a = [Decimal("0.01"), Decimal("0.02"), Decimal("-0.01"), Decimal("0.03")]
    b = [Decimal(v) * 2 for v in a]
    c = [Decimal(v) * -1 for v in a]
    assert compute_pairwise_correlation(a, b) == Decimal("1.0000")
    assert compute_pairwise_correlation(a, c) == Decimal("-1.0000")


def test_correlation_zero_variance_returns_none_not_zero() -> None:
    a = [Decimal("0.01"), Decimal("0.02"), Decimal("-0.01")]
    flat = [Decimal("0.01"), Decimal("0.01"), Decimal("0.01")]
    assert compute_pairwise_correlation(a, flat) is None


def test_highly_correlated_pairs_threshold() -> None:
    pairs = [
        {"strategy_a": 1, "strategy_b": 2, "correlation": Decimal("0.9")},
        {"strategy_a": 1, "strategy_b": 3, "correlation": Decimal("0.3")},
        {"strategy_a": 2, "strategy_b": 3, "correlation": None},
    ]
    result = find_highly_correlated_pairs(pairs, correlation_threshold=Decimal("0.7"))
    assert len(result) == 1
    assert result[0]["strategy_a"] == 1


# ---------------------------------------------------------------------------
# D: Concentration
# ---------------------------------------------------------------------------


def test_concentration_hhi_and_effective_number() -> None:
    result = compute_concentration({1: Decimal("0.5"), 2: Decimal("0.3"), 3: Decimal("0.2")})
    assert result["herfindahl_hirschman_index"] == Decimal("0.3800")
    assert result["largest_strategy_weight"] == Decimal("0.5")
    assert result["top2_weight_sum"] == Decimal("0.8")


def test_concentration_status_boundaries() -> None:
    low = compute_concentration({i: Decimal("0.1") for i in range(10)})
    assert low["concentration_status"] == "LOW"
    high = compute_concentration({1: Decimal("0.7"), 2: Decimal("0.3")})
    assert high["concentration_status"] == "HIGH"


def test_concentration_uses_custom_threshold() -> None:
    """이전에는 concentration_threshold 파라미터가 받아지기만 하고 전혀
    사용되지 않던 버그를 수정했다 — 실제로 판정에 영향을 줘야 한다."""
    weights = {1: Decimal("0.3"), 2: Decimal("0.3"), 3: Decimal("0.4")}
    default_result = compute_concentration(weights)
    strict_result = compute_concentration(weights, concentration_threshold=Decimal("0.30"))
    assert strict_result["concentration_status"] != default_result["concentration_status"] or strict_result["concentration_status"] == "HIGH"


# ---------------------------------------------------------------------------
# E: Risk Contribution
# ---------------------------------------------------------------------------


def test_risk_contribution_sums_to_approximately_100_percent() -> None:
    returns = {
        1: [Decimal("0.01"), Decimal("0.02"), Decimal("-0.01"), Decimal("0.03"), Decimal("0.01")],
        2: [Decimal("0.02"), Decimal("0.01"), Decimal("-0.02"), Decimal("0.01"), Decimal("0.02")],
        3: [Decimal("-0.01"), Decimal("0.03"), Decimal("0.01"), Decimal("-0.02"), Decimal("0.01")],
    }
    weights = {1: Decimal("0.5"), 2: Decimal("0.3"), 3: Decimal("0.2")}
    result = compute_risk_contribution([1, 2, 3], weights, returns)
    assert abs(result["total_risk_contribution_percent"] - Decimal("100")) < Decimal("0.5")


def test_risk_contribution_none_when_variance_zero() -> None:
    returns = {1: [Decimal("0"), Decimal("0"), Decimal("0")], 2: [Decimal("0"), Decimal("0"), Decimal("0")]}
    weights = {1: Decimal("0.5"), 2: Decimal("0.5")}
    result = compute_risk_contribution([1, 2], weights, returns)
    assert result["portfolio_variance"] is None
    assert all(c["risk_contribution_percent"] is None for c in result["contributions"])


# ---------------------------------------------------------------------------
# F: Diversification Benefit
# ---------------------------------------------------------------------------


def test_diversification_benefit_positive_when_portfolio_less_volatile() -> None:
    result = compute_diversification_benefit(
        weights={1: Decimal("0.5"), 2: Decimal("0.5")},
        standalone_volatility={1: Decimal("20"), 2: Decimal("20")},
        portfolio_volatility=Decimal("15"),
        standalone_mdd={1: Decimal("10"), 2: Decimal("10")},
        portfolio_mdd=Decimal("8"),
    )
    assert result["diversification_benefit"] == Decimal("0.2500")
    assert result["maximum_drawdown_reduction"] == Decimal("2.0000")


def test_diversification_benefit_can_be_negative() -> None:
    result = compute_diversification_benefit(
        weights={1: Decimal("0.5"), 2: Decimal("0.5")},
        standalone_volatility={1: Decimal("10"), 2: Decimal("10")},
        portfolio_volatility=Decimal("15"),
        standalone_mdd={1: Decimal("5"), 2: Decimal("5")},
        portfolio_mdd=Decimal("8"),
    )
    assert result["diversification_benefit"] < Decimal("0")


# ---------------------------------------------------------------------------
# G: Robustness Score / Status
# ---------------------------------------------------------------------------


def test_robustness_score_renormalizes_when_missing() -> None:
    result = compute_portfolio_robustness_score(
        diversification_benefit=None, average_pairwise_correlation=None, maximum_pairwise_correlation=None,
        concentration_hhi=None, risk_contribution_stdev_percent=None, portfolio_mdd_percent=None,
        strategy_count=2, duplicate_exposure_severities=[], valid_observation_ratio_percent=Decimal("100"),
    )
    included = [b for b in result["breakdown"] if b["included"]]
    assert {b["name"] for b in included} == {"strategy_count", "duplicate_exposure_severity", "valid_observation_ratio"}
    assert result["score"] is not None


def test_status_insufficient_data_below_minimum_observations() -> None:
    status, _ = determine_validation_status(
        observation_count=10, robustness_score=Decimal("90"), portfolio_mdd_percent=Decimal("5"),
        risk_contribution_max_percent=Decimal("40"), duplicate_exposure_severities=[],
        average_pairwise_correlation=Decimal("0.1"), diversification_benefit=Decimal("0.3"),
        concentration_status="LOW",
    )
    assert status == "INSUFFICIENT_DATA"


def test_status_high_risk_on_severe_drawdown() -> None:
    status, _ = determine_validation_status(
        observation_count=100, robustness_score=Decimal("60"), portfolio_mdd_percent=Decimal("60"),
        risk_contribution_max_percent=Decimal("40"), duplicate_exposure_severities=[],
        average_pairwise_correlation=Decimal("0.1"), diversification_benefit=Decimal("0.3"),
        concentration_status="LOW",
    )
    assert status == "HIGH_RISK"


def test_status_highly_correlated() -> None:
    status, _ = determine_validation_status(
        observation_count=100, robustness_score=Decimal("60"), portfolio_mdd_percent=Decimal("10"),
        risk_contribution_max_percent=Decimal("40"), duplicate_exposure_severities=[],
        average_pairwise_correlation=Decimal("0.8"), diversification_benefit=Decimal("0.3"),
        concentration_status="LOW",
    )
    assert status == "HIGHLY_CORRELATED"


def test_status_concentrated() -> None:
    status, _ = determine_validation_status(
        observation_count=100, robustness_score=Decimal("60"), portfolio_mdd_percent=Decimal("10"),
        risk_contribution_max_percent=Decimal("40"), duplicate_exposure_severities=[],
        average_pairwise_correlation=Decimal("0.1"), diversification_benefit=Decimal("0.3"),
        concentration_status="HIGH",
    )
    assert status == "CONCENTRATED"


def test_status_diversified() -> None:
    status, _ = determine_validation_status(
        observation_count=100, robustness_score=Decimal("80"), portfolio_mdd_percent=Decimal("5"),
        risk_contribution_max_percent=Decimal("40"), duplicate_exposure_severities=[],
        average_pairwise_correlation=Decimal("0.1"), diversification_benefit=Decimal("0.3"),
        concentration_status="LOW",
    )
    assert status == "DIVERSIFIED"


def test_status_acceptable_fallback() -> None:
    status, _ = determine_validation_status(
        observation_count=100, robustness_score=Decimal("50"), portfolio_mdd_percent=Decimal("15"),
        risk_contribution_max_percent=Decimal("40"), duplicate_exposure_severities=[],
        average_pairwise_correlation=Decimal("0.5"), diversification_benefit=Decimal("0.1"),
        concentration_status="MEDIUM",
    )
    assert status == "ACCEPTABLE"


# ---------------------------------------------------------------------------
# G2: Provenance / Report Input Hash — Decimal 파라미터가 실제 산출값에
# 영향을 주면서도 해시에서 빠지는 회귀를 순수 함수 단위로 검증한다(이전에는
# initial_capital/correlation_threshold/concentration_threshold/
# minimum_overlap_days가 canonical payload에서 빠져 있어, 이 값들만 다른
# 두 요청이 같은 report_input_hash로 충돌 감지를 피해갈 수 있었다 — 수정함).
# ---------------------------------------------------------------------------


def _base_hash_kwargs() -> dict:
    return dict(
        strategy_definition_ids=[1, 2],
        backtest_run_ids=[10, 20],
        executable_hashes={1: "hash-a", 2: "hash-b"},
        runtime_input_hashes={1: "rih-a", 2: "rih-b"},
        equity_curve_hashes={1: "ech-a", 2: "ech-b"},
        weights={1: Decimal("0.5"), 2: Decimal("0.5")},
        weighting_method="EQUAL_WEIGHT",
        alignment_policy="INTERSECTION",
        common_start_date=date(2024, 1, 1),
        common_end_date=date(2024, 6, 1),
        observation_count=100,
        minimum_overlap_days=60,
        initial_capital=Decimal("10000000"),
        correlation_threshold=Decimal("0.7"),
        concentration_threshold=Decimal("0.40"),
    )


def test_report_input_hash_sensitive_to_initial_capital() -> None:
    base = compute_report_input_hash(**_base_hash_kwargs())
    changed = compute_report_input_hash(**{**_base_hash_kwargs(), "initial_capital": Decimal("20000000")})
    assert base != changed


def test_report_input_hash_sensitive_to_correlation_threshold() -> None:
    base = compute_report_input_hash(**_base_hash_kwargs())
    changed = compute_report_input_hash(**{**_base_hash_kwargs(), "correlation_threshold": Decimal("0.5")})
    assert base != changed


def test_report_input_hash_sensitive_to_concentration_threshold() -> None:
    base = compute_report_input_hash(**_base_hash_kwargs())
    changed = compute_report_input_hash(**{**_base_hash_kwargs(), "concentration_threshold": Decimal("0.25")})
    assert base != changed


def test_report_input_hash_sensitive_to_minimum_overlap_days() -> None:
    base = compute_report_input_hash(**_base_hash_kwargs())
    changed = compute_report_input_hash(**{**_base_hash_kwargs(), "minimum_overlap_days": 90})
    assert base != changed


def test_report_input_hash_stable_for_identical_input() -> None:
    assert compute_report_input_hash(**_base_hash_kwargs()) == compute_report_input_hash(**_base_hash_kwargs())


# ---------------------------------------------------------------------------
# H: 종단 간 실행 + Persistence + API + Audit(합성 데이터, 2개 전략 —
# dev DB의 strategy.candidate_result 행 수 제약으로 MIN_STRATEGIES=2
# 경계값 구성을 그대로 사용)
# ---------------------------------------------------------------------------


def test_run_portfolio_validation_success(session) -> None:
    strategy_ids, backtest_ids = _seed_two_strategies(session)
    result = run_portfolio_validation(
        session, strategy_definition_ids=strategy_ids, backtest_run_ids=backtest_ids,
        weighting_method="EQUAL_WEIGHT", strategy_weights=None, alignment_policy="INTERSECTION",
        minimum_overlap_days=60, initial_capital=Decimal("10000000"),
        correlation_threshold=Decimal("0.7"), concentration_threshold=Decimal("0.40"),
        actor="STEP12_13_TEST:admin",
    )
    assert result["validation_status"] in {"DIVERSIFIED", "ACCEPTABLE", "CONCENTRATED", "HIGHLY_CORRELATED", "HIGH_RISK", "INSUFFICIENT_DATA"}
    assert result["strategy_count"] == 2


def test_run_portfolio_validation_detects_high_duplicate_exposure(session) -> None:
    strategy_ids, backtest_ids = _seed_two_strategies(session)
    result = run_portfolio_validation(
        session, strategy_definition_ids=strategy_ids, backtest_run_ids=backtest_ids,
        weighting_method="EQUAL_WEIGHT", strategy_weights=None, alignment_policy="INTERSECTION",
        minimum_overlap_days=60, initial_capital=Decimal("10000000"),
        correlation_threshold=Decimal("0.7"), concentration_threshold=Decimal("0.40"),
        actor="STEP12_13_TEST:admin",
    )
    exposures = result["duplicate_exposure_payload"]
    # 전략 A/B는 동일 Symbol+동일 Rule -> HIGH 노출이 최소 1건 있어야 한다.
    assert any(e["severity"] == "HIGH" for e in exposures)


def test_run_portfolio_validation_union_forward_fill_blocked(session) -> None:
    strategy_ids, backtest_ids = _seed_two_strategies(session)
    with pytest.raises(PortfolioValidationError) as exc_info:
        run_portfolio_validation(
            session, strategy_definition_ids=strategy_ids, backtest_run_ids=backtest_ids,
            weighting_method="EQUAL_WEIGHT", strategy_weights=None, alignment_policy="UNION_FORWARD_FILL",
            minimum_overlap_days=60, initial_capital=Decimal("10000000"),
            correlation_threshold=Decimal("0.7"), concentration_threshold=Decimal("0.40"),
            actor="STEP12_13_TEST:admin",
        )
    assert exc_info.value.code == "UNSUPPORTED_ALIGNMENT_POLICY"


def test_run_portfolio_validation_ownership_mismatch(session) -> None:
    strategy_ids, backtest_ids = _seed_two_strategies(session)
    swapped = [backtest_ids[1], backtest_ids[0]]
    with pytest.raises(PortfolioValidationError) as exc_info:
        run_portfolio_validation(
            session, strategy_definition_ids=strategy_ids, backtest_run_ids=swapped,
            weighting_method="EQUAL_WEIGHT", strategy_weights=None, alignment_policy="INTERSECTION",
            minimum_overlap_days=60, initial_capital=Decimal("10000000"),
            correlation_threshold=Decimal("0.7"), concentration_threshold=Decimal("0.40"),
            actor="STEP12_13_TEST:admin",
        )
    assert exc_info.value.code == "OWNERSHIP_MISMATCH"


def test_run_portfolio_validation_persists_and_immutable(session) -> None:
    strategy_ids, backtest_ids = _seed_two_strategies(session)
    result = run_portfolio_validation(
        session, strategy_definition_ids=strategy_ids, backtest_run_ids=backtest_ids,
        weighting_method="EQUAL_WEIGHT", strategy_weights=None, alignment_policy="INTERSECTION",
        minimum_overlap_days=60, initial_capital=Decimal("10000000"),
        correlation_threshold=Decimal("0.7"), concentration_threshold=Decimal("0.40"),
        actor="STEP12_13_TEST:admin",
    )
    fetched = get_portfolio_validation_report(session, result["portfolio_validation_report_id"])
    assert fetched["validation_status"] == result["validation_status"]
    assert fetched["portfolio_kpi_payload"] == result["portfolio_kpi_payload"]


def test_run_portfolio_validation_report_hash_order_invariant(session) -> None:
    strategy_ids, backtest_ids = _seed_two_strategies(session)
    r1 = run_portfolio_validation(
        session, strategy_definition_ids=strategy_ids, backtest_run_ids=backtest_ids,
        weighting_method="EQUAL_WEIGHT", strategy_weights=None, alignment_policy="INTERSECTION",
        minimum_overlap_days=60, initial_capital=Decimal("10000000"),
        correlation_threshold=Decimal("0.7"), concentration_threshold=Decimal("0.40"),
        actor="STEP12_13_TEST:admin",
    )
    reordered_strategy_ids = [strategy_ids[1], strategy_ids[0]]
    reordered_backtest_ids = [backtest_ids[1], backtest_ids[0]]
    r2 = run_portfolio_validation(
        session, strategy_definition_ids=reordered_strategy_ids, backtest_run_ids=reordered_backtest_ids,
        weighting_method="EQUAL_WEIGHT", strategy_weights=None, alignment_policy="INTERSECTION",
        minimum_overlap_days=60, initial_capital=Decimal("10000000"),
        correlation_threshold=Decimal("0.7"), concentration_threshold=Decimal("0.40"),
        actor="STEP12_13_TEST:admin",
    )
    r1_report = get_portfolio_validation_report(session, r1["portfolio_validation_report_id"])
    r2_report = get_portfolio_validation_report(session, r2["portfolio_validation_report_id"])
    assert r1_report["report_input_hash"] == r2_report["report_input_hash"]


def test_run_portfolio_validation_idempotency_replay(session) -> None:
    strategy_ids, backtest_ids = _seed_two_strategies(session)
    r1 = run_portfolio_validation(
        session, strategy_definition_ids=strategy_ids, backtest_run_ids=backtest_ids,
        weighting_method="EQUAL_WEIGHT", strategy_weights=None, alignment_policy="INTERSECTION",
        minimum_overlap_days=60, initial_capital=Decimal("10000000"),
        correlation_threshold=Decimal("0.7"), concentration_threshold=Decimal("0.40"),
        actor="STEP12_13_TEST:admin", idempotency_key="step12-13-idem-1",
    )
    r2 = run_portfolio_validation(
        session, strategy_definition_ids=strategy_ids, backtest_run_ids=backtest_ids,
        weighting_method="EQUAL_WEIGHT", strategy_weights=None, alignment_policy="INTERSECTION",
        minimum_overlap_days=60, initial_capital=Decimal("10000000"),
        correlation_threshold=Decimal("0.7"), concentration_threshold=Decimal("0.40"),
        actor="STEP12_13_TEST:admin", idempotency_key="step12-13-idem-1",
    )
    assert r1["portfolio_validation_report_id"] == r2["portfolio_validation_report_id"]
    assert r2["idempotent_replay"] is True


def test_run_portfolio_validation_idempotency_conflict(session) -> None:
    strategy_ids, backtest_ids = _seed_two_strategies(session)
    run_portfolio_validation(
        session, strategy_definition_ids=strategy_ids, backtest_run_ids=backtest_ids,
        weighting_method="EQUAL_WEIGHT", strategy_weights=None, alignment_policy="INTERSECTION",
        minimum_overlap_days=60, initial_capital=Decimal("10000000"),
        correlation_threshold=Decimal("0.7"), concentration_threshold=Decimal("0.40"),
        actor="STEP12_13_TEST:admin", idempotency_key="step12-13-conflict",
    )
    with pytest.raises(PortfolioValidationError) as exc_info:
        run_portfolio_validation(
            session, strategy_definition_ids=strategy_ids, backtest_run_ids=backtest_ids,
            weighting_method="EQUAL_WEIGHT", strategy_weights=None, alignment_policy="INTERSECTION",
            minimum_overlap_days=60, initial_capital=Decimal("20000000"),  # 다른 입력
            correlation_threshold=Decimal("0.7"), concentration_threshold=Decimal("0.40"),
            actor="STEP12_13_TEST:admin", idempotency_key="step12-13-conflict",
        )
    assert exc_info.value.code == "IDEMPOTENCY_CONFLICT"


def test_run_portfolio_validation_rerun_creates_new_report(session) -> None:
    strategy_ids, backtest_ids = _seed_two_strategies(session)
    r1 = run_portfolio_validation(
        session, strategy_definition_ids=strategy_ids, backtest_run_ids=backtest_ids,
        weighting_method="EQUAL_WEIGHT", strategy_weights=None, alignment_policy="INTERSECTION",
        minimum_overlap_days=60, initial_capital=Decimal("10000000"),
        correlation_threshold=Decimal("0.7"), concentration_threshold=Decimal("0.40"),
        actor="STEP12_13_TEST:admin",
    )
    r2 = run_portfolio_validation(
        session, strategy_definition_ids=strategy_ids, backtest_run_ids=backtest_ids,
        weighting_method="EQUAL_WEIGHT", strategy_weights=None, alignment_policy="INTERSECTION",
        minimum_overlap_days=60, initial_capital=Decimal("10000000"),
        correlation_threshold=Decimal("0.7"), concentration_threshold=Decimal("0.40"),
        actor="STEP12_13_TEST:admin",
    )
    assert r1["portfolio_validation_report_id"] != r2["portfolio_validation_report_id"]


def test_run_portfolio_validation_existing_summary_included(session) -> None:
    strategy_ids, backtest_ids = _seed_two_strategies(session)
    result = run_portfolio_validation(
        session, strategy_definition_ids=strategy_ids, backtest_run_ids=backtest_ids,
        weighting_method="EQUAL_WEIGHT", strategy_weights=None, alignment_policy="INTERSECTION",
        minimum_overlap_days=60, initial_capital=Decimal("10000000"),
        correlation_threshold=Decimal("0.7"), concentration_threshold=Decimal("0.40"),
        actor="STEP12_13_TEST:admin",
    )
    summary = result["existing_validation_summary_payload"]
    for sid in strategy_ids:
        assert summary[str(sid)]["quality_gate_recommendation"] == "NOT_AVAILABLE"


# ---------------------------------------------------------------------------
# I: API / Auth / Audit
# ---------------------------------------------------------------------------


def test_portfolio_validation_api_requires_admin() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        "/api/v1/admin/portfolio-validations",
        json={"strategy_definition_ids": [1, 2], "backtest_run_ids": [1, 2]},
    )
    assert resp.status_code == 401


def test_portfolio_validation_api_success_and_views(session) -> None:
    strategy_ids, backtest_ids = _seed_two_strategies(session)
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        "/api/v1/admin/portfolio-validations",
        json={"strategy_definition_ids": strategy_ids, "backtest_run_ids": backtest_ids, "minimum_overlap_days": 60},
        headers={"X-Admin-API-Key": admin_key},
    )
    assert resp.status_code == 201
    report_id = resp.json()["report_id"]

    for suffix in ("", "/summary", "/correlations", "/risk-contributions", "/exposures"):
        r = client.get(
            f"/api/v1/admin/portfolio-validations/{report_id}{suffix}", headers={"X-Admin-API-Key": admin_key},
        )
        assert r.status_code == 200


def test_portfolio_validation_api_invalid_weight_count(session) -> None:
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        "/api/v1/admin/portfolio-validations",
        json={"strategy_definition_ids": [1], "backtest_run_ids": [1]},
        headers={"X-Admin-API-Key": admin_key},
    )
    assert resp.status_code == 422  # Pydantic min_length 위반


def test_portfolio_validation_api_not_found(session) -> None:
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get(
        "/api/v1/admin/portfolio-validations/999999999", headers={"X-Admin-API-Key": admin_key},
    )
    assert resp.status_code == 404


def test_portfolio_validation_audit_events(session) -> None:
    from sqlalchemy import select

    from stock_platform.operation.audit_models import AuditEvent

    strategy_ids, backtest_ids = _seed_two_strategies(session)
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        "/api/v1/admin/portfolio-validations",
        json={"strategy_definition_ids": strategy_ids, "backtest_run_ids": backtest_ids, "minimum_overlap_days": 60},
        headers={"X-Admin-API-Key": admin_key},
    )
    report_id = resp.json()["report_id"]
    client.get(f"/api/v1/admin/portfolio-validations/{report_id}", headers={"X-Admin-API-Key": admin_key})
    events = session.execute(
        select(AuditEvent.event_type)
        .where(AuditEvent.event_type.like("PORTFOLIO_VALIDATION_%"))
        .order_by(AuditEvent.audit_event_id.desc())
        .limit(10)
    ).all()
    event_types = {e[0] for e in events}
    assert "PORTFOLIO_VALIDATION_STARTED" in event_types
    assert "PORTFOLIO_VALIDATION_COMPLETED" in event_types
    assert "PORTFOLIO_VALIDATION_VIEWED" in event_types


# ---------------------------------------------------------------------------
# J: Regression — STEP12-12 / STEP12-11 / STEP12-10 / STEP12-9 / STEP12-8
# ---------------------------------------------------------------------------


def test_step12_12_monte_carlo_regression(session) -> None:
    from stock_platform.ai.strategy_draft_approval.monte_carlo import run_monte_carlo_simulation

    strategy_ids, backtest_ids = _seed_two_strategies(session)
    result = run_monte_carlo_simulation(
        session, strategy_ids[0], backtest_run_id=backtest_ids[0],
        simulation_method="TRADE_ORDER_SHUFFLE", actor="STEP12_13_TEST:admin", simulation_count=100,
    )
    assert result["monte_carlo_status"] in {"RESILIENT", "ACCEPTABLE", "FRAGILE", "HIGH_RISK", "INSUFFICIENT_DATA"}


def test_step12_10_quality_gate_regression(session) -> None:
    from stock_platform.ai.strategy_draft_approval.quality_gate import run_quality_gate

    strategy_ids, backtest_ids = _seed_two_strategies(session)
    result = run_quality_gate(session, strategy_ids[0], actor="STEP12_13_TEST:admin")
    assert result["recommendation"] in {"APPROVE", "MANUAL_REVIEW", "REJECT"}


def test_moving_average_backtest_engine_regression() -> None:
    from stock_platform.backtest.engine import BacktestEngine
    from stock_platform.backtest.models import BacktestPrice
    from stock_platform.backtest.strategy import (
        MovingAverageCrossStrategy,
        MovingAverageStrategyConfig,
    )

    prices = [
        BacktestPrice(
            date(2024, 1, 1) + timedelta(days=i), Decimal(v), Decimal(v), Decimal(v), Decimal(v), Decimal(1)
        )
        for i, v in enumerate([100.0] * 25 + [110.0] * 10)
    ]
    strategy = MovingAverageCrossStrategy(MovingAverageStrategyConfig(short_window=5, long_window=20))
    result = BacktestEngine(strategy).run(
        exchange_code="KRX", symbol="005930", prices=prices, initial_capital=Decimal("1000000"),
    )
    assert result.summary.initial_capital == Decimal("1000000")


# ---------------------------------------------------------------------------
# K: STEP12-14 착수 전 STEP12-13 인수 조건 확인 및 보완.
# ---------------------------------------------------------------------------


def test_minimum_overlap_days_is_return_observation_count_not_equity_count() -> None:
    """§4 — 이전에는 minimum_overlap_days가 Equity Observation Count
    기준이라 Return 계산 시 항상 실제 관측치가 1개 적었다. 이제 Equity
    포인트가 정확히 minimum_overlap_days+1개일 때만 통과해야 한다(Return
    Observation Count == minimum_overlap_days)."""

    def _make_bundle(strategy_id: int, num_equity_points: int) -> StrategyBacktestBundle:
        curve = [
            EquityPoint(date(2024, 1, 1) + timedelta(days=i), Decimal("1000") + Decimal(i))
            for i in range(num_equity_points)
        ]
        return StrategyBacktestBundle(
            strategy_definition_id=strategy_id, backtest_run_id=strategy_id, run=None,
            equity_curve=curve, executable_hash="h", runtime_input_hash="r",
            market_type="KR_STOCK", timeframe="1D", symbol="X", exchange_code="KRX",
            signal_signature_hash="s",
        )

    bundles_exact = [_make_bundle(1, 61), _make_bundle(2, 61)]
    common_dates, _ = align_equity_curves(bundles=bundles_exact, alignment_policy="INTERSECTION", minimum_overlap_days=60)
    assert len(common_dates) - 1 == 60

    bundles_one_short = [_make_bundle(1, 60), _make_bundle(2, 60)]
    with pytest.raises(PortfolioValidationError) as exc_info:
        align_equity_curves(bundles=bundles_one_short, alignment_policy="INTERSECTION", minimum_overlap_days=60)
    assert exc_info.value.code == "INSUFFICIENT_OVERLAP"


def test_methodology_note_present_and_documents_daily_rebalancing(session) -> None:
    """§3 — Portfolio 결과가 Daily Rebalanced Hypothetical Portfolio 가정임을
    Report/API 응답에 항상 명시한다(실제 체결 기반 Buy-and-Hold로 오해 방지)."""
    strategy_ids, backtest_ids = _seed_two_strategies(session)
    result = run_portfolio_validation(
        session, strategy_definition_ids=strategy_ids, backtest_run_ids=backtest_ids,
        weighting_method="EQUAL_WEIGHT", strategy_weights=None, alignment_policy="INTERSECTION",
        minimum_overlap_days=60, initial_capital=Decimal("10000000"),
        correlation_threshold=Decimal("0.7"), concentration_threshold=Decimal("0.40"),
        actor="STEP12_13_TEST:admin",
    )
    assert result["methodology_note"] == METHODOLOGY_NOTE
    assert "Daily Rebalanced" in result["methodology_note"]
    fetched = get_portfolio_validation_report(session, result["portfolio_validation_report_id"])
    assert fetched["methodology_note"] == METHODOLOGY_NOTE


def test_portfolio_validation_report_immutable_after_source_backtest_reanalyzed(session) -> None:
    """§2 — 원본 Backtest Run의 STEP12-8 Performance Analytics를 재계산해도
    (analyze_backtest_run()은 backtest_run.parameters를 다시 써 넣는
    기존 동작이 있다) 이미 생성된 불변 Portfolio Validation Report의
    저장된 Evidence Snapshot은 전혀 변하지 않아야 한다."""
    from stock_platform.performance.backtest_analytics import analyze_backtest_run

    strategy_ids, backtest_ids = _seed_two_strategies(session)
    result = run_portfolio_validation(
        session, strategy_definition_ids=strategy_ids, backtest_run_ids=backtest_ids,
        weighting_method="EQUAL_WEIGHT", strategy_weights=None, alignment_policy="INTERSECTION",
        minimum_overlap_days=60, initial_capital=Decimal("10000000"),
        correlation_threshold=Decimal("0.7"), concentration_threshold=Decimal("0.40"),
        actor="STEP12_13_TEST:admin",
    )
    before = get_portfolio_validation_report(session, result["portfolio_validation_report_id"])

    # 원본 Backtest Run의 STEP12-8 분석을 재실행(원본 데이터 "변경" 시뮬레이션).
    analyze_backtest_run(session, backtest_ids[0])
    analyze_backtest_run(session, backtest_ids[1])

    after = get_portfolio_validation_report(session, result["portfolio_validation_report_id"])
    assert after["portfolio_kpi_payload"] == before["portfolio_kpi_payload"]
    assert after["correlation_payload"] == before["correlation_payload"]
    assert after["report_input_hash"] == before["report_input_hash"]
    assert after["created_at"] == before["created_at"]


def test_run_portfolio_validation_three_strategies_multiple_high_correlation_and_exposure(session) -> None:
    """§5 — dev DB 실제 행 수에 의존하지 않는 합성 Fixture로 3개 Strategy를
    구성한다(전부 동일 Symbol+동일 Rule -> 모든 Pair가 동시에 HIGH
    Correlation과 HIGH Duplicate Exposure를 가져야 한다)."""
    strategy_ids, backtest_ids = _seed_n_correlated_strategies(session, 3)
    result = run_portfolio_validation(
        session, strategy_definition_ids=strategy_ids, backtest_run_ids=backtest_ids,
        weighting_method="EQUAL_WEIGHT", strategy_weights=None, alignment_policy="INTERSECTION",
        minimum_overlap_days=60, initial_capital=Decimal("10000000"),
        correlation_threshold=Decimal("0.7"), concentration_threshold=Decimal("0.40"),
        actor="STEP12_13_TEST:admin",
    )
    assert result["strategy_count"] == 3
    highly_correlated = result["correlation_payload"]["highly_correlated_pairs"]
    assert len(highly_correlated) == 3  # C(3,2)
    high_exposures = [e for e in result["duplicate_exposure_payload"] if e["severity"] == "HIGH"]
    assert len(high_exposures) == 3  # C(3,2)


def test_run_portfolio_validation_ten_strategies_boundary(session) -> None:
    """§5 — MAX_STRATEGIES=10 경계값을 실제 DB 종단 테스트로 확인한다."""
    strategy_ids, backtest_ids = _seed_n_correlated_strategies(session, 10)
    result = run_portfolio_validation(
        session, strategy_definition_ids=strategy_ids, backtest_run_ids=backtest_ids,
        weighting_method="EQUAL_WEIGHT", strategy_weights=None, alignment_policy="INTERSECTION",
        minimum_overlap_days=60, initial_capital=Decimal("10000000"),
        correlation_threshold=Decimal("0.7"), concentration_threshold=Decimal("0.40"),
        actor="STEP12_13_TEST:admin",
    )
    assert result["strategy_count"] == 10
    assert result["robustness_score"] is not None
    high_exposures = [e for e in result["duplicate_exposure_payload"] if e["severity"] == "HIGH"]
    assert len(high_exposures) == 45  # C(10,2)


def test_run_portfolio_validation_input_order_invariant_ten_strategies(session) -> None:
    """§5 — 입력 순서를 바꿔도 동일 report_input_hash가 나와야 한다(10개
    규모에서도 결정성이 유지되는지 확인)."""
    strategy_ids, backtest_ids = _seed_n_correlated_strategies(session, 10)
    r1 = run_portfolio_validation(
        session, strategy_definition_ids=strategy_ids, backtest_run_ids=backtest_ids,
        weighting_method="EQUAL_WEIGHT", strategy_weights=None, alignment_policy="INTERSECTION",
        minimum_overlap_days=60, initial_capital=Decimal("10000000"),
        correlation_threshold=Decimal("0.7"), concentration_threshold=Decimal("0.40"),
        actor="STEP12_13_TEST:admin",
    )
    paired = list(zip(strategy_ids, backtest_ids))
    paired.reverse()
    reordered_strategy_ids = [p[0] for p in paired]
    reordered_backtest_ids = [p[1] for p in paired]
    r2 = run_portfolio_validation(
        session, strategy_definition_ids=reordered_strategy_ids, backtest_run_ids=reordered_backtest_ids,
        weighting_method="EQUAL_WEIGHT", strategy_weights=None, alignment_policy="INTERSECTION",
        minimum_overlap_days=60, initial_capital=Decimal("10000000"),
        correlation_threshold=Decimal("0.7"), concentration_threshold=Decimal("0.40"),
        actor="STEP12_13_TEST:admin",
    )
    r1_report = get_portfolio_validation_report(session, r1["portfolio_validation_report_id"])
    r2_report = get_portfolio_validation_report(session, r2["portfolio_validation_report_id"])
    assert r1_report["report_input_hash"] == r2_report["report_input_hash"]
