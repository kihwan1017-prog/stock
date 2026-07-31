"""STEP 12-12 — Monte Carlo Simulation.

이미 완료된 Backtest의 실제 Trade 손익(net_profit_loss, Fee/Tax 이미
반영됨)만 재사용해 메모리에서 재표본화한다. 새 Backtest를 실행하지 않고
Strategy Definition을 수정하지 않는다."""

from __future__ import annotations

import random
import time
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from stock_platform.ai.strategy_draft.service import StrategyDraftService
from stock_platform.ai.strategy_draft_approval.monte_carlo import (
    BLOCK_SIZE_DEFAULT,
    MIN_TRADE_COUNT,
    MonteCarloError,
    block_bootstrap_trades,
    bootstrap_trades,
    compute_confidence_interval,
    compute_distribution,
    compute_report_input_hash,
    compute_risk_of_ruin,
    compute_robustness_score,
    compute_trade_pnl_hash,
    determine_monte_carlo_status,
    extract_trade_pnls,
    get_monte_carlo_report,
    percentile,
    run_monte_carlo_simulation,
    select_representatives,
    shuffle_trades,
    simulate_path,
    validate_simulation_inputs,
)
from stock_platform.ai.strategy_draft_approval.service import (
    StrategyDraftApprovalService,
)
from stock_platform.ai.strategy_request.service import StrategyRequestService
from stock_platform.api.main import app
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory
from stock_platform.strategy_deployment.definition_entities import (
    StrategyDefinitionEntity,
)

pytestmark = pytest.mark.integration

_REQUESTER_USER_ID = 8
_REVIEWER_USER_ID = 7
_MARKER = "STEP12_12_TEST"
_FINGERPRINT = "f2" * 32
_TEST_SYMBOL = "STEP1212T"
_TEST_EXCHANGE = "KRX"

_VALID_ENTRY = '[{"indicator":"RSI","operator":"LT","threshold":30,"lookback":14}]'
_VALID_EXIT = '[{"indicator":"RSI","operator":"GT","threshold":70,"lookback":14}]'
_VALID_STOP_LOSS = '{"type":"PERCENT","value":5}'
_VALID_TAKE_PROFIT = '{"type":"PERCENT","value":10}'
_VALID_POSITION_SIZING = '{"method":"FIXED_PERCENT","value":0.1}'


@pytest.fixture()
def result_ids() -> list[int]:
    Session = get_session_factory()
    s = Session()
    try:
        rows = s.execute(
            text("SELECT result_id FROM strategy.candidate_result ORDER BY result_id LIMIT 5")
        ).fetchall()
        ids = [int(r[0]) for r in rows]
        if not ids:
            pytest.skip("strategy.candidate_result에 테스트용 행이 없어 스킵")
        return ids
    finally:
        s.close()


_CLEANUP_SQL = [
    "DELETE FROM trading.monte_carlo_simulation_report WHERE strategy_id IN "
    "(SELECT strategy_id FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))",
    "DELETE FROM trading.parameter_sensitivity_report WHERE strategy_id IN "
    "(SELECT strategy_id FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))",
    "DELETE FROM trading.strategy_quality_gate_report WHERE strategy_id IN "
    "(SELECT strategy_id FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))",
    "DELETE FROM trading.walk_forward_window_metric WHERE strategy_performance_run_id IN "
    "(SELECT strategy_performance_run_id FROM trading.strategy_performance_run "
    "WHERE strategy_code LIKE 'DEFINITION_%' AND parameter_payload->>'requested_by' LIKE 'STEP12_12%')",
    "DELETE FROM trading.strategy_performance_metric WHERE strategy_performance_run_id IN "
    "(SELECT strategy_performance_run_id FROM trading.strategy_performance_run "
    "WHERE strategy_code LIKE 'DEFINITION_%' AND parameter_payload->>'requested_by' LIKE 'STEP12_12%')",
    "DELETE FROM trading.strategy_performance_run WHERE strategy_code LIKE 'DEFINITION_%' "
    "AND parameter_payload->>'requested_by' LIKE 'STEP12_12%'",
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
    "DELETE FROM market.price_daily WHERE instrument_id IN "
    "(SELECT instrument_id FROM market.instrument WHERE symbol = :test_symbol)",
    "DELETE FROM market.instrument WHERE symbol = :test_symbol",
]


def _cleanup(s) -> None:
    for sql in _CLEANUP_SQL:
        s.execute(text(sql), {"marker": _MARKER, "test_symbol": _TEST_SYMBOL})
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


def _seed_prices(session, closes: list[float], *, start: date) -> None:
    instrument_id = session.execute(
        text(
            """
            INSERT INTO market.instrument (asset_type, exchange_code, symbol, name)
            VALUES ('STOCK', :exchange, :symbol, 'STEP12-12 Test')
            RETURNING instrument_id
            """
        ),
        {"exchange": _TEST_EXCHANGE, "symbol": _TEST_SYMBOL},
    ).scalar_one()
    for i, close in enumerate(closes):
        trade_date = start + timedelta(days=i)
        session.execute(
            text(
                """
                INSERT INTO market.price_daily
                (instrument_id, trade_date, open_price, high_price, low_price, close_price, volume, source)
                VALUES (:iid, :td, :c, :c, :c, :c, 1000, 'STEP12_12_TEST')
                """
            ),
            {"iid": instrument_id, "td": trade_date, "c": Decimal(str(close))},
        )
    session.commit()


def _triangle_wave(num_days: int, *, period: int = 20, low: float = 50.0, high: float = 100.0) -> list[float]:
    half = period // 2
    closes: list[float] = []
    for i in range(num_days):
        phase = i % period
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
        {"cid": result_id, "fp": _FINGERPRINT, "marker": _MARKER},
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


def _manual_draft_kwargs(**overrides) -> dict:
    base = {
        "actor": "admin:7", "title": "수동 초안", "timeframe": "1D", "market_type": "KR_STOCK",
        "entry_rule": _VALID_ENTRY, "exit_rule": _VALID_EXIT, "stop_loss_rule": _VALID_STOP_LOSS,
        "take_profit_rule": _VALID_TAKE_PROFIT, "position_sizing_rule": _VALID_POSITION_SIZING,
    }
    base.update(overrides)
    return base


def _approve(session, strategy_request_id: int, **draft_overrides) -> dict:
    draft = StrategyDraftService(session).create(
        strategy_request_id=strategy_request_id, **_manual_draft_kwargs(**draft_overrides)
    )
    return StrategyDraftApprovalService(session).approve(draft["draft_id"], actor="admin:7", reason="승인")


def _seed_and_approve_with_backtest(session) -> tuple[dict, int]:
    """승인 Definition + 실제 Backtest Run(Trade 다수 포함)을 만든다."""
    from stock_platform.ai.strategy_draft_approval.backtest_execution import (
        run_definition_backtest,
    )

    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    approval = _approve(session, request["strategy_request_id"])
    closes = _triangle_wave(160, period=30)
    _seed_prices(session, closes, start=date(2024, 1, 1))
    result = run_definition_backtest(
        session, approval["strategy_definition_id"],
        runtime_input={
            "symbol": _TEST_SYMBOL, "exchange_code": _TEST_EXCHANGE,
            "start_date": date(2024, 1, 1), "end_date": date(2024, 1, 1) + timedelta(days=len(closes)),
            "initial_capital": Decimal("1000000"), "fee_ratio": Decimal("0.00015"),
            "sell_tax_ratio": Decimal("0.0018"), "slippage_ratio": Decimal("0"),
        },
        actor="STEP12_12_TEST:admin",
    )
    return approval, result["backtest_run_id"]


def _fake_trade(net_profit_loss) -> SimpleNamespace:
    return SimpleNamespace(net_profit_loss=Decimal(str(net_profit_loss)))


# ---------------------------------------------------------------------------
# A: Input Validation
# ---------------------------------------------------------------------------


def test_validate_supported_methods_ok() -> None:
    for method in ("TRADE_ORDER_SHUFFLE", "BOOTSTRAP_WITH_REPLACEMENT", "BLOCK_BOOTSTRAP"):
        validate_simulation_inputs(
            simulation_method=method, simulation_count=1000, confidence_level=Decimal("0.95"),
            ruin_threshold_percent=Decimal("50"), block_size=5, random_seed=42, trade_count=20,
        )


def test_validate_unsupported_method_blocked() -> None:
    with pytest.raises(MonteCarloError) as exc_info:
        validate_simulation_inputs(
            simulation_method="MONTE_CARLO_MAGIC", simulation_count=1000, confidence_level=Decimal("0.95"),
            ruin_threshold_percent=Decimal("50"), block_size=5, random_seed=42, trade_count=20,
        )
    assert exc_info.value.code == "UNSUPPORTED_METHOD"


def test_validate_simulation_count_boundaries() -> None:
    for count in (99, 10001):
        with pytest.raises(MonteCarloError) as exc_info:
            validate_simulation_inputs(
                simulation_method="TRADE_ORDER_SHUFFLE", simulation_count=count, confidence_level=Decimal("0.95"),
                ruin_threshold_percent=Decimal("50"), block_size=5, random_seed=42, trade_count=20,
            )
        assert exc_info.value.code == "INVALID_SIMULATION_COUNT"
    for count in (100, 10000):
        validate_simulation_inputs(
            simulation_method="TRADE_ORDER_SHUFFLE", simulation_count=count, confidence_level=Decimal("0.95"),
            ruin_threshold_percent=Decimal("50"), block_size=5, random_seed=42, trade_count=20,
        )


def test_validate_confidence_level_allowed_values() -> None:
    for level in (Decimal("0.90"), Decimal("0.95"), Decimal("0.99")):
        validate_simulation_inputs(
            simulation_method="TRADE_ORDER_SHUFFLE", simulation_count=1000, confidence_level=level,
            ruin_threshold_percent=Decimal("50"), block_size=5, random_seed=42, trade_count=20,
        )
    with pytest.raises(MonteCarloError) as exc_info:
        validate_simulation_inputs(
            simulation_method="TRADE_ORDER_SHUFFLE", simulation_count=1000, confidence_level=Decimal("0.80"),
            ruin_threshold_percent=Decimal("50"), block_size=5, random_seed=42, trade_count=20,
        )
    assert exc_info.value.code == "INVALID_CONFIDENCE_LEVEL"


def test_validate_ruin_threshold_range() -> None:
    for bad in (Decimal("0"), Decimal("100")):
        with pytest.raises(MonteCarloError) as exc_info:
            validate_simulation_inputs(
                simulation_method="TRADE_ORDER_SHUFFLE", simulation_count=1000, confidence_level=Decimal("0.95"),
                ruin_threshold_percent=bad, block_size=5, random_seed=42, trade_count=20,
            )
        assert exc_info.value.code == "INVALID_RUIN_THRESHOLD"


def test_validate_random_seed_must_be_int() -> None:
    with pytest.raises(MonteCarloError) as exc_info:
        validate_simulation_inputs(
            simulation_method="TRADE_ORDER_SHUFFLE", simulation_count=1000, confidence_level=Decimal("0.95"),
            ruin_threshold_percent=Decimal("50"), block_size=5, random_seed="42", trade_count=20,
        )
    assert exc_info.value.code == "INVALID_RANDOM_SEED"


def test_validate_block_size_bounds() -> None:
    with pytest.raises(MonteCarloError) as exc_info:
        validate_simulation_inputs(
            simulation_method="BLOCK_BOOTSTRAP", simulation_count=1000, confidence_level=Decimal("0.95"),
            ruin_threshold_percent=Decimal("50"), block_size=0, random_seed=42, trade_count=20,
        )
    assert exc_info.value.code == "INVALID_BLOCK_SIZE"
    with pytest.raises(MonteCarloError) as exc_info:
        validate_simulation_inputs(
            simulation_method="BLOCK_BOOTSTRAP", simulation_count=1000, confidence_level=Decimal("0.95"),
            ruin_threshold_percent=Decimal("50"), block_size=21, random_seed=42, trade_count=20,
        )
    assert exc_info.value.code == "INVALID_BLOCK_SIZE"
    validate_simulation_inputs(
        simulation_method="BLOCK_BOOTSTRAP", simulation_count=1000, confidence_level=Decimal("0.95"),
        ruin_threshold_percent=Decimal("50"), block_size=20, random_seed=42, trade_count=20,
    )


def test_validate_insufficient_trades_blocked() -> None:
    with pytest.raises(MonteCarloError) as exc_info:
        validate_simulation_inputs(
            simulation_method="TRADE_ORDER_SHUFFLE", simulation_count=1000, confidence_level=Decimal("0.95"),
            ruin_threshold_percent=Decimal("50"), block_size=5, random_seed=42, trade_count=MIN_TRADE_COUNT - 1,
        )
    assert exc_info.value.code == "INSUFFICIENT_TRADES"


# ---------------------------------------------------------------------------
# B: Determinism / Random Seed
# ---------------------------------------------------------------------------


def test_same_seed_same_shuffle_result() -> None:
    pnls = [Decimal(x) for x in [10, -5, 20, -8, 15, -3, 12]]
    r1 = shuffle_trades(random.Random(42), pnls)
    r2 = shuffle_trades(random.Random(42), pnls)
    assert r1 == r2


def test_different_seed_different_result() -> None:
    pnls = [Decimal(x) for x in [10, -5, 20, -8, 15, -3, 12]]
    r1 = shuffle_trades(random.Random(1), pnls)
    r2 = shuffle_trades(random.Random(2), pnls)
    assert r1 != r2


def test_global_random_state_not_polluted() -> None:
    random.seed(999)
    before = random.random()
    random.seed(999)
    pnls = [Decimal(x) for x in range(10)]
    shuffle_trades(random.Random(1234), pnls)
    bootstrap_trades(random.Random(5678), pnls)
    after = random.random()
    assert before == after  # 전용 RNG만 사용했으므로 전역 random 상태는 그대로여야 한다.


# ---------------------------------------------------------------------------
# C: TRADE_ORDER_SHUFFLE
# ---------------------------------------------------------------------------


def test_shuffle_uses_every_trade_exactly_once() -> None:
    pnls = [Decimal(x) for x in [10, -5, 20, -8, 15]]
    result = shuffle_trades(random.Random(7), pnls)
    assert sorted(result) == sorted(pnls)
    assert len(result) == len(pnls)


def test_shuffle_preserves_total_sum() -> None:
    pnls = [Decimal(x) for x in [10, -5, 20, -8, 15]]
    result = shuffle_trades(random.Random(7), pnls)
    assert sum(result, Decimal("0")) == sum(pnls, Decimal("0"))


def test_shuffle_can_change_order() -> None:
    pnls = [Decimal(x) for x in range(20)]
    result = shuffle_trades(random.Random(1), pnls)
    assert result != pnls  # 실용적으로 20개 순서가 우연히 동일할 확률은 무시 가능


# ---------------------------------------------------------------------------
# D: BOOTSTRAP_WITH_REPLACEMENT
# ---------------------------------------------------------------------------


def test_bootstrap_preserves_original_count() -> None:
    pnls = [Decimal(x) for x in [10, -5, 20, -8, 15]]
    result = bootstrap_trades(random.Random(3), pnls)
    assert len(result) == len(pnls)


def test_bootstrap_allows_duplicates() -> None:
    pnls = [Decimal(x) for x in range(50)]
    result = bootstrap_trades(random.Random(3), pnls)
    assert len(set(result)) < len(result)  # 복원 추출이므로 중복이 있어야 한다(실용적 확률)


def test_bootstrap_deterministic() -> None:
    pnls = [Decimal(x) for x in [10, -5, 20, -8, 15]]
    r1 = bootstrap_trades(random.Random(9), pnls)
    r2 = bootstrap_trades(random.Random(9), pnls)
    assert r1 == r2


# ---------------------------------------------------------------------------
# E: BLOCK_BOOTSTRAP
# ---------------------------------------------------------------------------


def test_block_bootstrap_preserves_original_count() -> None:
    pnls = [Decimal(x) for x in range(10)]
    result = block_bootstrap_trades(random.Random(2), pnls, 3)
    assert len(result) == 10


def test_block_bootstrap_size_one_behaves_like_single_sample_bootstrap() -> None:
    pnls = [Decimal(x) for x in range(10)]
    result = block_bootstrap_trades(random.Random(2), pnls, 1)
    assert len(result) == 10
    assert all(v in pnls for v in result)


def test_block_bootstrap_size_equal_to_trade_count() -> None:
    pnls = [Decimal(x) for x in range(10)]
    result = block_bootstrap_trades(random.Random(2), pnls, 10)
    assert len(result) == 10
    assert sorted(result) == sorted(pnls)  # block_size==n이면 원형 시프트라 전부 정확히 1회씩 등장


def test_block_bootstrap_preserves_contiguous_subsequences() -> None:
    pnls = [Decimal(x) for x in range(20)]
    result = block_bootstrap_trades(random.Random(4), pnls, 5)
    # 결과를 5개씩 끊었을 때 각 조각이 원본에서 연속된(원형) 구간이어야 한다.
    for chunk_start in range(0, 20, 5):
        chunk = result[chunk_start:chunk_start + 5]
        start_idx = pnls.index(chunk[0])
        expected = [pnls[(start_idx + i) % 20] for i in range(5)]
        assert chunk == expected


# ---------------------------------------------------------------------------
# F: Risk Analytics(Equity/Drawdown/Ruin)
# ---------------------------------------------------------------------------


def test_simulate_path_final_equity_and_return() -> None:
    pnls = [Decimal(x) for x in [100000, -50000, 200000]]
    path = simulate_path(0, Decimal("1000000"), pnls, ruin_equity_threshold=Decimal("500000"))
    assert path.final_equity == Decimal("1250000")
    assert path.total_return == Decimal("25.0000")


def test_simulate_path_maximum_drawdown() -> None:
    # 1,000,000 -> 1,200,000(peak) -> 900,000(dd=300000/1200000=25%) -> 1,000,000
    pnls = [Decimal(x) for x in [200000, -300000, 100000]]
    path = simulate_path(0, Decimal("1000000"), pnls, ruin_equity_threshold=Decimal("100"))
    assert path.peak_equity == Decimal("1200000")
    assert path.maximum_drawdown_amount == Decimal("300000")
    assert path.maximum_drawdown_percent == Decimal("25.0000")


def test_simulate_path_consecutive_losses() -> None:
    pnls = [Decimal(x) for x in [-100, -100, 500, -50, -50, -50, 1000]]
    path = simulate_path(0, Decimal("100000"), pnls, ruin_equity_threshold=Decimal("1"))
    assert path.consecutive_losses == 3


def test_simulate_path_ruin_triggered() -> None:
    pnls = [Decimal(x) for x in [-600000]]
    path = simulate_path(0, Decimal("1000000"), pnls, ruin_equity_threshold=Decimal("500000"))
    assert path.ruin is True


def test_simulate_path_no_ruin_when_above_threshold() -> None:
    pnls = [Decimal(x) for x in [-100000]]
    path = simulate_path(0, Decimal("1000000"), pnls, ruin_equity_threshold=Decimal("500000"))
    assert path.ruin is False


def test_risk_of_ruin_actual_value() -> None:
    paths = [
        simulate_path(i, Decimal("1000000"), pnls, ruin_equity_threshold=Decimal("500000"))
        for i, pnls in enumerate(
            [[Decimal("-600000")], [Decimal("-600000")], [Decimal("100000")], [Decimal("50000")]]
        )
    ]
    stats = compute_risk_of_ruin(paths)
    assert stats["risk_of_ruin_percent"] == Decimal("50.00")
    assert stats["ruin_simulation_count"] == 2
    assert stats["valid_simulation_count"] == 4


def test_risk_of_ruin_none_when_no_valid_simulations() -> None:
    stats = compute_risk_of_ruin([])
    assert stats["risk_of_ruin_percent"] is None


# ---------------------------------------------------------------------------
# G: Distribution / Percentile
# ---------------------------------------------------------------------------


def test_percentile_linear_interpolation_known_values() -> None:
    values = [Decimal(x) for x in [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]]
    # n=10, rank = p/100*9
    assert percentile(sorted(values), Decimal("0")) == Decimal("10")
    assert percentile(sorted(values), Decimal("100")) == Decimal("100")
    assert percentile(sorted(values), Decimal("50")) == Decimal("55")  # rank=4.5 -> interp(50,60)


def test_percentile_single_value() -> None:
    assert percentile([Decimal("42")], Decimal("50")) == Decimal("42")


def test_compute_distribution_has_all_required_percentiles() -> None:
    values = [Decimal(x) for x in range(1, 101)]
    dist = compute_distribution(values)
    for label in ("P01", "P05", "P10", "P25", "P50", "P75", "P90", "P95", "P99"):
        assert label in dist


def test_confidence_interval_95_percent() -> None:
    values = [Decimal(x) for x in range(1, 101)]
    low, high = compute_confidence_interval(values, Decimal("0.95"))
    # alpha=2.5 -> P2.5/P97.5
    ordered = sorted(values)
    assert low == percentile(ordered, Decimal("2.5"))
    assert high == percentile(ordered, Decimal("97.5"))


# ---------------------------------------------------------------------------
# Worst/Median/Best
# ---------------------------------------------------------------------------


def test_select_representatives_worst_median_best() -> None:
    paths = [
        simulate_path(i, Decimal("1000000"), [pnl], ruin_equity_threshold=Decimal("1"))
        for i, pnl in enumerate([Decimal("100000"), Decimal("-100000"), Decimal("50000")])
    ]
    reps = select_representatives(paths)
    assert reps["worst"]["simulation_index"] == 1
    assert reps["best"]["simulation_index"] == 0
    assert reps["median"]["simulation_index"] == 2


def test_select_representatives_tie_break_by_simulation_index() -> None:
    paths = [
        simulate_path(i, Decimal("1000000"), [Decimal("0")], ruin_equity_threshold=Decimal("1"))
        for i in range(3)
    ]
    reps = select_representatives(paths)
    # 전부 동일 final_equity -> simulation_index 오름차순으로 결정적 정렬
    assert reps["worst"]["simulation_index"] == 0
    assert reps["best"]["simulation_index"] == 2


# ---------------------------------------------------------------------------
# H: Robustness Score / Status
# ---------------------------------------------------------------------------


def test_robustness_score_high_quality_inputs() -> None:
    result = compute_robustness_score(
        simulation_method="BOOTSTRAP_WITH_REPLACEMENT",
        risk_of_ruin_percent=Decimal("0"), p05_total_return=Decimal("10"),
        median_total_return=Decimal("15"), p95_max_drawdown_percent=Decimal("5"),
        p95_consecutive_losses=None,
        final_equity_ci_low=Decimal("1000000"), final_equity_ci_high=Decimal("1100000"),
        median_final_equity=Decimal("1050000"), worst_case_recovery=True,
        valid_simulation_ratio_percent=Decimal("100"),
    )
    assert result["score"] > Decimal("70")


def test_robustness_score_renormalizes_when_data_missing() -> None:
    result = compute_robustness_score(
        simulation_method="BOOTSTRAP_WITH_REPLACEMENT",
        risk_of_ruin_percent=None, p05_total_return=None, median_total_return=None,
        p95_max_drawdown_percent=None, p95_consecutive_losses=None,
        final_equity_ci_low=None, final_equity_ci_high=None,
        median_final_equity=None, worst_case_recovery=None,
        valid_simulation_ratio_percent=Decimal("50"),
    )
    # valid_simulation_ratio(가중치 5)만 남으므로 재정규화 후 그대로 50점이어야 한다.
    assert result["score"] == Decimal("50.00")
    included = [b for b in result["breakdown"] if b["included"]]
    assert len(included) == 1
    assert included[0]["name"] == "valid_simulation_ratio"


def test_robustness_score_none_when_all_missing() -> None:
    # valid_simulation_ratio_percent는 항상 계산되는 값이라 완전한 None은
    # 이 함수 시그니처상 불가능하지만(0을 넣어도 점수로 포함됨), 나머지가
    # 전부 없을 때 유일 컴포넌트만으로도 정상 동작하는지 확인한다.
    result = compute_robustness_score(
        simulation_method="BOOTSTRAP_WITH_REPLACEMENT",
        risk_of_ruin_percent=None, p05_total_return=None, median_total_return=None,
        p95_max_drawdown_percent=None, p95_consecutive_losses=None,
        final_equity_ci_low=None, final_equity_ci_high=None,
        median_final_equity=None, worst_case_recovery=None,
        valid_simulation_ratio_percent=Decimal("0"),
    )
    assert result["score"] == Decimal("0.00")


def test_robustness_score_shuffle_excludes_path_independent_components() -> None:
    """STEP12-12 보완 §1 — TRADE_ORDER_SHUFFLE은 P05/Median Total Return,
    Final Equity CI 폭 등 경로-비의존 컴포넌트를 아예 포함하지 않아야 한다."""
    result = compute_robustness_score(
        simulation_method="TRADE_ORDER_SHUFFLE",
        risk_of_ruin_percent=Decimal("0"), p05_total_return=Decimal("10"),
        median_total_return=Decimal("15"), p95_max_drawdown_percent=Decimal("5"),
        p95_consecutive_losses=Decimal("2"),
        final_equity_ci_low=Decimal("1000000"), final_equity_ci_high=Decimal("1100000"),
        median_final_equity=Decimal("1050000"), worst_case_recovery=True,
        valid_simulation_ratio_percent=Decimal("100"),
    )
    names = {b["name"] for b in result["breakdown"]}
    assert names == {
        "risk_of_ruin", "maximum_drawdown_tail", "consecutive_loss_tail",
        "worst_case_recovery", "valid_simulation_ratio",
    }
    assert "p05_total_return" not in names
    assert "median_total_return" not in names
    assert "final_equity_ci_width" not in names
    assert result["score_policy"] == "TRADE_ORDER_SHUFFLE"


def test_robustness_score_bootstrap_keeps_distribution_components() -> None:
    result = compute_robustness_score(
        simulation_method="BOOTSTRAP_WITH_REPLACEMENT",
        risk_of_ruin_percent=Decimal("0"), p05_total_return=Decimal("10"),
        median_total_return=Decimal("15"), p95_max_drawdown_percent=Decimal("5"),
        p95_consecutive_losses=Decimal("2"),
        final_equity_ci_low=Decimal("1000000"), final_equity_ci_high=Decimal("1100000"),
        median_final_equity=Decimal("1050000"), worst_case_recovery=True,
        valid_simulation_ratio_percent=Decimal("100"),
    )
    names = {b["name"] for b in result["breakdown"]}
    assert "p05_total_return" in names
    assert "consecutive_loss_tail" not in names
    assert result["score_policy"] == "BOOTSTRAP_WITH_REPLACEMENT"


def test_monte_carlo_status_insufficient_data_below_minimum_valid() -> None:
    status, _ = determine_monte_carlo_status(
        valid_simulation_count=10, robustness_score=Decimal("90"), risk_of_ruin_percent=Decimal("0"),
        p05_total_return=Decimal("10"), p95_max_drawdown_percent=Decimal("5"),
    )
    assert status == "INSUFFICIENT_DATA"


def test_monte_carlo_status_resilient() -> None:
    status, _ = determine_monte_carlo_status(
        valid_simulation_count=1000, robustness_score=Decimal("80"), risk_of_ruin_percent=Decimal("1"),
        p05_total_return=Decimal("5"), p95_max_drawdown_percent=Decimal("20"),
    )
    assert status == "RESILIENT"


def test_monte_carlo_status_high_risk_on_ruin() -> None:
    status, _ = determine_monte_carlo_status(
        valid_simulation_count=1000, robustness_score=Decimal("60"), risk_of_ruin_percent=Decimal("25"),
        p05_total_return=Decimal("5"), p95_max_drawdown_percent=Decimal("20"),
    )
    assert status == "HIGH_RISK"


def test_monte_carlo_status_high_risk_on_tail_loss() -> None:
    status, _ = determine_monte_carlo_status(
        valid_simulation_count=1000, robustness_score=Decimal("60"), risk_of_ruin_percent=Decimal("5"),
        p05_total_return=Decimal("-60"), p95_max_drawdown_percent=Decimal("20"),
    )
    assert status == "HIGH_RISK"


def test_monte_carlo_status_fragile() -> None:
    status, _ = determine_monte_carlo_status(
        valid_simulation_count=1000, robustness_score=Decimal("30"), risk_of_ruin_percent=Decimal("5"),
        p05_total_return=Decimal("5"), p95_max_drawdown_percent=Decimal("20"),
    )
    assert status == "FRAGILE"


def test_monte_carlo_status_acceptable() -> None:
    status, _ = determine_monte_carlo_status(
        valid_simulation_count=1000, robustness_score=Decimal("55"), risk_of_ruin_percent=Decimal("5"),
        p05_total_return=Decimal("5"), p95_max_drawdown_percent=Decimal("20"),
    )
    assert status == "ACCEPTABLE"


# ---------------------------------------------------------------------------
# I: Provenance / Hash
# ---------------------------------------------------------------------------


def test_trade_pnl_extraction_priority_field() -> None:
    trades = [_fake_trade(100), _fake_trade(-50)]
    pnls = extract_trade_pnls(trades)
    assert pnls == [Decimal("100"), Decimal("-50")]


def test_trade_pnl_hash_deterministic() -> None:
    pnls = [Decimal(x) for x in [10, -5, 20]]
    assert compute_trade_pnl_hash(pnls) == compute_trade_pnl_hash(list(pnls))


def test_trade_pnl_hash_changes_with_order() -> None:
    pnls = [Decimal(x) for x in [10, -5, 20]]
    reordered = [Decimal(x) for x in [20, -5, 10]]
    assert compute_trade_pnl_hash(pnls) != compute_trade_pnl_hash(reordered)


def test_report_input_hash_deterministic() -> None:
    kwargs = dict(
        strategy_definition_id=1, backtest_run_id=2, executable_hash="abc", runtime_input_hash="def",
        trade_pnl_hash="ghi", simulation_method="TRADE_ORDER_SHUFFLE", simulation_count=1000,
        random_seed=42, confidence_level=Decimal("0.95"), ruin_threshold_percent=Decimal("50"), block_size=5,
    )
    assert compute_report_input_hash(**kwargs) == compute_report_input_hash(**kwargs)


def test_report_input_hash_differs_from_trade_pnl_hash() -> None:
    """STEP12-11에서 배운 교훈 재적용 확인 — report 전체 입력 해시와
    원본 Trade 순서 해시는 서로 다른 값·다른 목적이어야 한다."""
    pnls = [Decimal(x) for x in [10, -5, 20]]
    trade_hash = compute_trade_pnl_hash(pnls)
    report_hash = compute_report_input_hash(
        strategy_definition_id=1, backtest_run_id=2, executable_hash="abc", runtime_input_hash="def",
        trade_pnl_hash=trade_hash, simulation_method="TRADE_ORDER_SHUFFLE", simulation_count=1000,
        random_seed=42, confidence_level=Decimal("0.95"), ruin_threshold_percent=Decimal("50"), block_size=5,
    )
    assert trade_hash != report_hash


# ---------------------------------------------------------------------------
# J/K/L: 종단 간 실행 + Persistence + API + Audit(합성 데이터)
# ---------------------------------------------------------------------------


def test_run_monte_carlo_simulation_success(session) -> None:
    approval, backtest_run_id = _seed_and_approve_with_backtest(session)
    result = run_monte_carlo_simulation(
        session, approval["strategy_definition_id"], backtest_run_id=backtest_run_id,
        simulation_method="TRADE_ORDER_SHUFFLE", actor="STEP12_12_TEST:admin", simulation_count=200,
    )
    assert result["monte_carlo_status"] in {"RESILIENT", "ACCEPTABLE", "FRAGILE", "HIGH_RISK", "INSUFFICIENT_DATA"}
    assert result["valid_simulation_count"] + result["failed_simulation_count"] == 200


def test_run_monte_carlo_simulation_deterministic_repeat(session) -> None:
    approval, backtest_run_id = _seed_and_approve_with_backtest(session)
    r1 = run_monte_carlo_simulation(
        session, approval["strategy_definition_id"], backtest_run_id=backtest_run_id,
        simulation_method="BOOTSTRAP_WITH_REPLACEMENT", actor="STEP12_12_TEST:admin",
        simulation_count=200, random_seed=123,
    )
    r2 = run_monte_carlo_simulation(
        session, approval["strategy_definition_id"], backtest_run_id=backtest_run_id,
        simulation_method="BOOTSTRAP_WITH_REPLACEMENT", actor="STEP12_12_TEST:admin",
        simulation_count=200, random_seed=123,
    )
    assert r1["risk_of_ruin_percent"] == r2["risk_of_ruin_percent"]
    assert r1["robustness_score"] == r2["robustness_score"]
    assert r1["percentile_payload"] == r2["percentile_payload"]


def test_run_monte_carlo_ownership_mismatch_blocked(session) -> None:
    if len(session.info["result_ids"]) < 2:
        pytest.skip("두 번째 candidate_result 행이 없어 진짜 소유권 불일치를 재현할 수 없음")
    approval, backtest_run_id = _seed_and_approve_with_backtest(session)
    other_request = _create_approved_request(session, result_id=session.info["result_ids"][1])
    other_approval = _approve(session, other_request["strategy_request_id"])
    with pytest.raises(MonteCarloError) as exc_info:
        run_monte_carlo_simulation(
            session, other_approval["strategy_definition_id"], backtest_run_id=backtest_run_id,
            simulation_method="TRADE_ORDER_SHUFFLE", actor="STEP12_12_TEST:admin", simulation_count=100,
        )
    assert exc_info.value.code == "OWNERSHIP_MISMATCH"


def test_run_monte_carlo_backtest_not_found(session) -> None:
    approval, _ = _seed_and_approve_with_backtest(session)
    with pytest.raises(MonteCarloError) as exc_info:
        run_monte_carlo_simulation(
            session, approval["strategy_definition_id"], backtest_run_id=999_999_999,
            simulation_method="TRADE_ORDER_SHUFFLE", actor="STEP12_12_TEST:admin", simulation_count=100,
        )
    assert exc_info.value.code == "BACKTEST_RUN_NOT_FOUND"


def test_run_monte_carlo_does_not_mutate_definition(session) -> None:
    approval, backtest_run_id = _seed_and_approve_with_backtest(session)
    definition_before = session.get(StrategyDefinitionEntity, approval["strategy_definition_id"])
    hash_before = definition_before.definition_hash
    run_monte_carlo_simulation(
        session, approval["strategy_definition_id"], backtest_run_id=backtest_run_id,
        simulation_method="TRADE_ORDER_SHUFFLE", actor="STEP12_12_TEST:admin", simulation_count=100,
    )
    session.expire_all()
    definition_after = session.get(StrategyDefinitionEntity, approval["strategy_definition_id"])
    assert definition_after.definition_hash == hash_before


def test_run_monte_carlo_persists_and_immutable(session) -> None:
    approval, backtest_run_id = _seed_and_approve_with_backtest(session)
    result = run_monte_carlo_simulation(
        session, approval["strategy_definition_id"], backtest_run_id=backtest_run_id,
        simulation_method="TRADE_ORDER_SHUFFLE", actor="STEP12_12_TEST:admin", simulation_count=150,
    )
    fetched = get_monte_carlo_report(session, result["monte_carlo_report_id"])
    assert fetched["monte_carlo_status"] == result["monte_carlo_status"]
    assert fetched["percentile_payload"] == result["percentile_payload"]


def test_run_monte_carlo_rerun_creates_new_report(session) -> None:
    approval, backtest_run_id = _seed_and_approve_with_backtest(session)
    r1 = run_monte_carlo_simulation(
        session, approval["strategy_definition_id"], backtest_run_id=backtest_run_id,
        simulation_method="TRADE_ORDER_SHUFFLE", actor="STEP12_12_TEST:admin", simulation_count=100,
    )
    r2 = run_monte_carlo_simulation(
        session, approval["strategy_definition_id"], backtest_run_id=backtest_run_id,
        simulation_method="TRADE_ORDER_SHUFFLE", actor="STEP12_12_TEST:admin", simulation_count=100,
    )
    assert r1["monte_carlo_report_id"] != r2["monte_carlo_report_id"]


def test_run_monte_carlo_idempotency_replay(session) -> None:
    approval, backtest_run_id = _seed_and_approve_with_backtest(session)
    r1 = run_monte_carlo_simulation(
        session, approval["strategy_definition_id"], backtest_run_id=backtest_run_id,
        simulation_method="TRADE_ORDER_SHUFFLE", actor="STEP12_12_TEST:admin", simulation_count=100,
        idempotency_key="step12-12-idem-1",
    )
    r2 = run_monte_carlo_simulation(
        session, approval["strategy_definition_id"], backtest_run_id=backtest_run_id,
        simulation_method="TRADE_ORDER_SHUFFLE", actor="STEP12_12_TEST:admin", simulation_count=100,
        idempotency_key="step12-12-idem-1",
    )
    assert r1["monte_carlo_report_id"] == r2["monte_carlo_report_id"]
    assert r2["idempotent_replay"] is True


def test_run_monte_carlo_idempotency_conflict_on_different_request(session) -> None:
    """STEP12-12 보완 §3 — 동일 idempotency_key라도 실제 요청 내용
    (report_input_hash)이 다르면 과거 Report를 그대로 반환하지 않고
    IDEMPOTENCY_CONFLICT로 차단해야 한다."""
    approval, backtest_run_id = _seed_and_approve_with_backtest(session)
    run_monte_carlo_simulation(
        session, approval["strategy_definition_id"], backtest_run_id=backtest_run_id,
        simulation_method="TRADE_ORDER_SHUFFLE", actor="STEP12_12_TEST:admin", simulation_count=100,
        random_seed=1, idempotency_key="step12-12-conflict-key",
    )
    with pytest.raises(MonteCarloError) as exc_info:
        run_monte_carlo_simulation(
            session, approval["strategy_definition_id"], backtest_run_id=backtest_run_id,
            simulation_method="TRADE_ORDER_SHUFFLE", actor="STEP12_12_TEST:admin", simulation_count=100,
            random_seed=2,  # 다른 seed -> 다른 report_input_hash
            idempotency_key="step12-12-conflict-key",
        )
    assert exc_info.value.code == "IDEMPOTENCY_CONFLICT"


def test_run_monte_carlo_backtest_not_completed_blocked(session) -> None:
    """STEP12-12 보완 §4 — Backtest 상태(status_code)가 완료(SUCCESS)가
    아니면 실행을 차단해야 한다."""
    approval, backtest_run_id = _seed_and_approve_with_backtest(session)
    session.execute(
        text("UPDATE backtest.backtest_run SET status_code = 'FAILED' WHERE backtest_run_id = :rid"),
        {"rid": backtest_run_id},
    )
    session.commit()
    with pytest.raises(MonteCarloError) as exc_info:
        run_monte_carlo_simulation(
            session, approval["strategy_definition_id"], backtest_run_id=backtest_run_id,
            simulation_method="TRADE_ORDER_SHUFFLE", actor="STEP12_12_TEST:admin", simulation_count=100,
        )
    assert exc_info.value.code == "BACKTEST_NOT_COMPLETED"


def test_run_monte_carlo_missing_executable_hash_blocked(session) -> None:
    """STEP12-12 보완 §4 — executable_hash가 없는 Backtest Run은 차단."""
    approval, backtest_run_id = _seed_and_approve_with_backtest(session)
    session.execute(
        text(
            "UPDATE backtest.backtest_run SET parameters = parameters - 'executable_hash' "
            "WHERE backtest_run_id = :rid"
        ),
        {"rid": backtest_run_id},
    )
    session.commit()
    with pytest.raises(MonteCarloError) as exc_info:
        run_monte_carlo_simulation(
            session, approval["strategy_definition_id"], backtest_run_id=backtest_run_id,
            simulation_method="TRADE_ORDER_SHUFFLE", actor="STEP12_12_TEST:admin", simulation_count=100,
        )
    assert exc_info.value.code == "EXECUTABLE_HASH_MISSING"


def test_representative_curves_are_real_equity_paths(session) -> None:
    """STEP12-12 보완 §2 — Worst/Median/Best는 시작/끝/최고/최저 요약이
    아니라 실제 거래 순서별(trade_index) Equity Curve를 가져야 한다."""
    approval, backtest_run_id = _seed_and_approve_with_backtest(session)
    result = run_monte_carlo_simulation(
        session, approval["strategy_definition_id"], backtest_run_id=backtest_run_id,
        simulation_method="TRADE_ORDER_SHUFFLE", actor="STEP12_12_TEST:admin", simulation_count=100,
    )
    reps = result["representative_payload"]
    for key in ("worst", "median", "best"):
        rep = reps[key]
        assert "equity_curve" in rep
        curve = rep["equity_curve"]
        assert len(curve) >= 2
        assert curve[0]["trade_index"] == 0
        # trade_index가 0,1,2...로 연속 증가해야 한다(요약값이 아닌 실제 순서열).
        indices = [point["trade_index"] for point in curve]
        assert indices == sorted(indices)
        assert "downsampling" in rep


def test_representative_curve_deterministic_replay(session) -> None:
    approval, backtest_run_id = _seed_and_approve_with_backtest(session)
    r1 = run_monte_carlo_simulation(
        session, approval["strategy_definition_id"], backtest_run_id=backtest_run_id,
        simulation_method="BOOTSTRAP_WITH_REPLACEMENT", actor="STEP12_12_TEST:admin",
        simulation_count=100, random_seed=77,
    )
    r2 = run_monte_carlo_simulation(
        session, approval["strategy_definition_id"], backtest_run_id=backtest_run_id,
        simulation_method="BOOTSTRAP_WITH_REPLACEMENT", actor="STEP12_12_TEST:admin",
        simulation_count=100, random_seed=77,
    )
    assert r1["representative_payload"] == r2["representative_payload"]


def test_downsample_curve_deterministic_and_includes_required_points() -> None:
    from stock_platform.ai.strategy_draft_approval.monte_carlo import _downsample_curve

    curve = [{"trade_index": i, "equity": Decimal(1000 - i if i != 50 else 100)} for i in range(300)]
    downsampled1, meta1 = _downsample_curve(curve, max_points=50)
    downsampled2, meta2 = _downsample_curve(curve, max_points=50)
    assert downsampled1 == downsampled2
    assert meta1 == meta2
    assert meta1["applied"] is True
    assert len(downsampled1) <= 50
    indices = {p["trade_index"] for p in downsampled1}
    assert 0 in indices  # 첫 지점
    assert 299 in indices  # 마지막 지점
    assert 50 in indices  # 최저 Equity 지점(index 50, equity=100)


def test_downsample_curve_not_applied_when_within_limit() -> None:
    from stock_platform.ai.strategy_draft_approval.monte_carlo import _downsample_curve

    curve = [{"trade_index": i, "equity": Decimal(i)} for i in range(10)]
    downsampled, meta = _downsample_curve(curve, max_points=200)
    assert downsampled == curve
    assert meta["applied"] is False


def test_get_monte_carlo_report_rejects_cross_strategy(session) -> None:
    approval, backtest_run_id = _seed_and_approve_with_backtest(session)
    result = run_monte_carlo_simulation(
        session, approval["strategy_definition_id"], backtest_run_id=backtest_run_id,
        simulation_method="TRADE_ORDER_SHUFFLE", actor="STEP12_12_TEST:admin", simulation_count=100,
    )
    with pytest.raises(MonteCarloError) as exc_info:
        get_monte_carlo_report(
            session, result["monte_carlo_report_id"],
            strategy_definition_id=approval["strategy_definition_id"] + 999_999,
        )
    assert exc_info.value.code == "NOT_FOUND"


def test_run_monte_carlo_does_not_store_all_raw_simulations(session) -> None:
    approval, backtest_run_id = _seed_and_approve_with_backtest(session)
    result = run_monte_carlo_simulation(
        session, approval["strategy_definition_id"], backtest_run_id=backtest_run_id,
        simulation_method="TRADE_ORDER_SHUFFLE", actor="STEP12_12_TEST:admin", simulation_count=500,
    )
    # representative_payload에는 worst/median/best 3개만 있어야 한다(500개 원본 미저장).
    reps = result["representative_payload"]
    assert set(reps.keys()) == {"worst", "median", "best"}


# ---------------------------------------------------------------------------
# API / Auth / Audit
# ---------------------------------------------------------------------------


def test_monte_carlo_api_requires_admin() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        "/api/v1/admin/strategies/1/monte-carlo",
        json={"backtest_run_id": 1, "simulation_method": "TRADE_ORDER_SHUFFLE"},
    )
    assert resp.status_code == 401


def test_monte_carlo_api_success_and_views(session) -> None:
    approval, backtest_run_id = _seed_and_approve_with_backtest(session)
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        f"/api/v1/admin/strategies/{approval['strategy_definition_id']}/monte-carlo",
        json={
            "backtest_run_id": backtest_run_id, "simulation_method": "TRADE_ORDER_SHUFFLE",
            "simulation_count": 150,
        },
        headers={"X-Admin-API-Key": admin_key},
    )
    assert resp.status_code == 201
    report_id = resp.json()["report_id"]

    for suffix in ("", "/summary", "/distribution", "/representatives"):
        r = client.get(
            f"/api/v1/admin/strategies/{approval['strategy_definition_id']}/monte-carlo/{report_id}{suffix}",
            headers={"X-Admin-API-Key": admin_key},
        )
        assert r.status_code == 200


def test_monte_carlo_api_invalid_method_returns_400(session) -> None:
    approval, backtest_run_id = _seed_and_approve_with_backtest(session)
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        f"/api/v1/admin/strategies/{approval['strategy_definition_id']}/monte-carlo",
        json={"backtest_run_id": backtest_run_id, "simulation_method": "BOGUS_METHOD"},
        headers={"X-Admin-API-Key": admin_key},
    )
    assert resp.status_code == 400


def test_monte_carlo_api_not_found(session) -> None:
    approval, _ = _seed_and_approve_with_backtest(session)
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get(
        f"/api/v1/admin/strategies/{approval['strategy_definition_id']}/monte-carlo/999999999",
        headers={"X-Admin-API-Key": admin_key},
    )
    assert resp.status_code == 404


def test_monte_carlo_api_blocks_cross_strategy(session) -> None:
    approval, backtest_run_id = _seed_and_approve_with_backtest(session)
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        f"/api/v1/admin/strategies/{approval['strategy_definition_id']}/monte-carlo",
        json={"backtest_run_id": backtest_run_id, "simulation_method": "TRADE_ORDER_SHUFFLE", "simulation_count": 100},
        headers={"X-Admin-API-Key": admin_key},
    )
    report_id = resp.json()["report_id"]
    other_id = approval["strategy_definition_id"] + 999_999
    cross_resp = client.get(
        f"/api/v1/admin/strategies/{other_id}/monte-carlo/{report_id}",
        headers={"X-Admin-API-Key": admin_key},
    )
    assert cross_resp.status_code == 404


def test_monte_carlo_audit_events(session) -> None:
    from sqlalchemy import select

    from stock_platform.operation.audit_models import AuditEvent

    approval, backtest_run_id = _seed_and_approve_with_backtest(session)
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        f"/api/v1/admin/strategies/{approval['strategy_definition_id']}/monte-carlo",
        json={"backtest_run_id": backtest_run_id, "simulation_method": "TRADE_ORDER_SHUFFLE", "simulation_count": 100},
        headers={"X-Admin-API-Key": admin_key},
    )
    report_id = resp.json()["report_id"]
    client.get(
        f"/api/v1/admin/strategies/{approval['strategy_definition_id']}/monte-carlo/{report_id}",
        headers={"X-Admin-API-Key": admin_key},
    )
    events = session.execute(
        select(AuditEvent.event_type)
        .where(AuditEvent.strategy_id == str(approval["strategy_definition_id"]))
        .where(AuditEvent.event_type.like("MONTE_CARLO_%"))
        .order_by(AuditEvent.audit_event_id.desc())
        .limit(10)
    ).all()
    event_types = {e[0] for e in events}
    assert "MONTE_CARLO_STARTED" in event_types
    assert "MONTE_CARLO_COMPLETED" in event_types
    assert "MONTE_CARLO_VIEWED" in event_types


# ---------------------------------------------------------------------------
# Performance
# ---------------------------------------------------------------------------


def test_monte_carlo_1000_simulations_completes_quickly(session) -> None:
    approval, backtest_run_id = _seed_and_approve_with_backtest(session)
    start = time.monotonic()
    result = run_monte_carlo_simulation(
        session, approval["strategy_definition_id"], backtest_run_id=backtest_run_id,
        simulation_method="BLOCK_BOOTSTRAP", actor="STEP12_12_TEST:admin", simulation_count=1000,
    )
    elapsed = time.monotonic() - start
    assert result["valid_simulation_count"] == 1000
    assert elapsed < 15.0  # 일반 개발 PC 기준 실용적 시간(넉넉한 상한)


# ---------------------------------------------------------------------------
# Regression — STEP12-11 / STEP12-10 / STEP12-9 / STEP12-8 / Backtest
# ---------------------------------------------------------------------------


def test_step12_11_parameter_sensitivity_regression(session) -> None:
    from stock_platform.ai.strategy_draft_approval.parameter_sensitivity import (
        run_parameter_sensitivity,
    )

    approval, _ = _seed_and_approve_with_backtest(session)
    result = run_parameter_sensitivity(
        session, approval["strategy_definition_id"], parameter_names=["stop_loss_rule.value"],
        runtime_input={
            "symbol": _TEST_SYMBOL, "exchange_code": _TEST_EXCHANGE,
            "start_date": date(2024, 1, 1), "end_date": date(2024, 1, 1) + timedelta(days=160),
            "initial_capital": Decimal("1000000"), "fee_ratio": Decimal("0.00015"),
            "sell_tax_ratio": Decimal("0.0018"), "slippage_ratio": Decimal("0"),
        },
        actor="STEP12_12_TEST:admin",
    )
    assert result["sensitivity_status"] in {"ROBUST", "ACCEPTABLE", "FRAGILE", "INSUFFICIENT_DATA"}


def test_step12_10_quality_gate_regression(session) -> None:
    from stock_platform.ai.strategy_draft_approval.quality_gate import run_quality_gate

    approval, _ = _seed_and_approve_with_backtest(session)
    result = run_quality_gate(session, approval["strategy_definition_id"], actor="STEP12_12_TEST:admin")
    assert result["recommendation"] in {"APPROVE", "MANUAL_REVIEW", "REJECT"}


def test_step12_9_walk_forward_regression(session) -> None:
    from stock_platform.ai.strategy_draft_approval.walk_forward import run_walk_forward

    approval = _create_approved_request(session, result_id=session.info["result_ids"][0])
    approval = _approve(session, approval["strategy_request_id"])
    closes = _triangle_wave(140, period=30)
    _seed_prices(session, closes, start=date(2024, 1, 1))
    result = run_walk_forward(
        session, approval["strategy_definition_id"],
        start_date=date(2024, 1, 1), end_date=date(2024, 4, 30),
        train_days=45, test_days=45, scheme="ROLLING",
        symbol=_TEST_SYMBOL, exchange_code=_TEST_EXCHANGE,
        initial_capital=Decimal("1000000"), fee_ratio=Decimal("0.00015"),
        sell_tax_ratio=Decimal("0.0018"), slippage_ratio=Decimal("0"),
        actor="STEP12_12_TEST:admin",
    )
    assert result["completed_window_count"] == 2


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
