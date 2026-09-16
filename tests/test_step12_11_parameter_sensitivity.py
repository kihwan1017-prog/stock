"""STEP 12-11 — Parameter Sensitivity Analysis.

기존 STEP12-7 Backtest 실행 경로/STEP12-8 Performance Analytics/STEP12-6
Executable Specification만 재사용한다. 원본 Strategy Definition은 절대
수정하지 않으며, 최고 수익 파라미터 자동 탐색/자동 최적화는 하지 않는다.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from stock_platform.ai.strategy_draft.service import StrategyDraftService
from stock_platform.ai.strategy_draft_approval.parameter_sensitivity import (
    MAX_COMBINATIONS,
    ParameterDescriptor,
    ParameterSensitivityError,
    _compute_stable_range,
    _detect_performance_cliffs,
    _determine_sensitivity_status,
    build_combinations,
    extract_numeric_parameters,
    generate_variations,
    get_parameter_sensitivity_report,
    run_parameter_sensitivity,
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
_MARKER = "STEP12_11_TEST"
_FINGERPRINT = "e1" * 32
_TEST_SYMBOL = "STEP1211T"
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
            text("SELECT result_id FROM strategy.candidate_result ORDER BY result_id LIMIT 1")
        ).fetchall()
        ids = [int(r[0]) for r in rows]
        if not ids:
            pytest.skip("strategy.candidate_result에 테스트용 행이 없어 스킵")
        return ids
    finally:
        s.close()


_CLEANUP_SQL = [
    "DELETE FROM trading.parameter_sensitivity_report WHERE strategy_id IN "
    "(SELECT strategy_id FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))",
    "DELETE FROM trading.strategy_quality_gate_report WHERE strategy_id IN "
    "(SELECT strategy_id FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))",
    "DELETE FROM trading.walk_forward_window_metric WHERE strategy_performance_run_id IN "
    "(SELECT strategy_performance_run_id FROM trading.strategy_performance_run "
    "WHERE strategy_code LIKE 'DEFINITION_%' AND parameter_payload->>'requested_by' LIKE 'STEP12_11%')",
    "DELETE FROM trading.strategy_performance_metric WHERE strategy_performance_run_id IN "
    "(SELECT strategy_performance_run_id FROM trading.strategy_performance_run "
    "WHERE strategy_code LIKE 'DEFINITION_%' AND parameter_payload->>'requested_by' LIKE 'STEP12_11%')",
    "DELETE FROM trading.strategy_performance_run WHERE strategy_code LIKE 'DEFINITION_%' "
    "AND parameter_payload->>'requested_by' LIKE 'STEP12_11%'",
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
            VALUES ('STOCK', :exchange, :symbol, 'STEP12-11 Test')
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
                VALUES (:iid, :td, :c, :c, :c, :c, 1000, 'STEP12_11_TEST')
                """
            ),
            {"iid": instrument_id, "td": trade_date, "c": Decimal(str(close))},
        )
    session.commit()


def _triangle_wave(num_days: int, *, period: int = 30, low: float = 50.0, high: float = 100.0) -> list[float]:
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


def _seed_and_approve(session) -> dict:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    approval = _approve(session, request["strategy_request_id"])
    closes = _triangle_wave(140, period=30)
    _seed_prices(session, closes, start=date(2024, 1, 1))
    return approval


def _default_runtime_input(**overrides) -> dict:
    base = {
        "symbol": _TEST_SYMBOL, "exchange_code": _TEST_EXCHANGE,
        "start_date": date(2024, 1, 1), "end_date": date(2024, 4, 30),
        "initial_capital": Decimal("1000000"), "fee_ratio": Decimal("0.00015"),
        "sell_tax_ratio": Decimal("0.0018"), "slippage_ratio": Decimal("0"),
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# A: Parameter Variation
# ---------------------------------------------------------------------------


def test_variation_includes_base_value() -> None:
    d = ParameterDescriptor(name="x", path=("stop_loss_rule", "value"), value=Decimal("5"), kind="PERCENT_STOP_LOSS")
    variations = generate_variations(d)
    assert Decimal("5.00") in variations


def test_variation_order_is_deterministic() -> None:
    d = ParameterDescriptor(name="x", path=("stop_loss_rule", "value"), value=Decimal("5"), kind="PERCENT_STOP_LOSS")
    v1 = generate_variations(d)
    v2 = generate_variations(d)
    assert v1 == v2
    assert v1 == sorted(v1)  # 단조 증가 변환이므로 오름차순과 일치해야 한다.


def test_variation_period_deterministic_rounding_and_dedup() -> None:
    d = ParameterDescriptor(name="lookback", path=("entry_rules", 0, "lookback"), value=Decimal("2"), kind="PERIOD")
    variations = generate_variations(d)
    # raw = 1.6, 1.8, 2.0, 2.2, 2.4 -> HALF_UP 반올림 -> 2,2,2,2,2 -> dedup -> [2]
    assert variations == [Decimal("2")]


def test_variation_period_minimum_is_one() -> None:
    d = ParameterDescriptor(name="lookback", path=("entry_rules", 0, "lookback"), value=Decimal("1"), kind="PERIOD")
    variations = generate_variations(d)
    assert all(v >= Decimal("1") for v in variations)


def test_variation_percent_clamped_to_valid_range() -> None:
    # base=28(stop loss), +20% = 33.6 > MAX_STOP_LOSS_PERCENT(30) -> clamp
    d = ParameterDescriptor(name="x", path=("stop_loss_rule", "value"), value=Decimal("28"), kind="PERCENT_STOP_LOSS")
    variations = generate_variations(d)
    assert all(v <= Decimal("30") for v in variations)
    assert all(v > Decimal("0") for v in variations)


def test_variation_ratio_clamped_to_valid_range() -> None:
    d = ParameterDescriptor(
        name="position_sizing_rule.value", path=("position_sizing_rule", "value"),
        value=Decimal("0.95"), kind="RATIO_POSITION_SIZE",
    )
    variations = generate_variations(d)
    assert all(v <= Decimal("1.0") for v in variations)


def test_variation_unsupported_kind_blocked() -> None:
    d = ParameterDescriptor(name="x", path=("a",), value=Decimal("1"), kind="ENUM_FIELD")
    with pytest.raises(ParameterSensitivityError) as exc_info:
        generate_variations(d)
    assert exc_info.value.code == "UNSUPPORTED_PARAMETER"


# ---------------------------------------------------------------------------
# B: Combination
# ---------------------------------------------------------------------------


def test_combination_single_parameter() -> None:
    combos = build_combinations({"a": [Decimal("1"), Decimal("2"), Decimal("3")]})
    assert len(combos) == 3


def test_combination_two_parameters() -> None:
    combos = build_combinations({"a": [Decimal("1"), Decimal("2")], "b": [Decimal("10"), Decimal("20"), Decimal("30")]})
    assert len(combos) == 6


def test_combination_at_exactly_max() -> None:
    combos = build_combinations(
        {"a": [Decimal(i) for i in range(5)], "b": [Decimal(i) for i in range(5)]},
        max_combinations=MAX_COMBINATIONS,
    )
    assert len(combos) == MAX_COMBINATIONS


def test_combination_exceeding_max_blocked() -> None:
    with pytest.raises(ParameterSensitivityError) as exc_info:
        build_combinations(
            {"a": [Decimal(i) for i in range(6)], "b": [Decimal(i) for i in range(6)]},
            max_combinations=MAX_COMBINATIONS,
        )
    assert exc_info.value.code == "COMBINATION_LIMIT_EXCEEDED"


# ---------------------------------------------------------------------------
# D: Analytics(순수 함수) — Stable Range / Performance Cliff / Sensitivity Status
# ---------------------------------------------------------------------------


def _var(value, *, status="SUCCESS", score=None, mdd=Decimal("10"), trade_count=5, ret=Decimal("10")):
    return {
        "parameter_value": Decimal(str(value)), "status": status, "strategy_score": score,
        "maximum_drawdown_rate": mdd, "trade_count": trade_count, "total_return_rate": ret,
    }


def test_stable_range_includes_base_when_all_close() -> None:
    ordered = [_var(4, score=Decimal("80")), _var(5, score=Decimal("85")), _var(6, score=Decimal("82"))]
    base_summary = {"strategy_score": Decimal("85"), "maximum_drawdown_rate": Decimal("10")}
    result = _compute_stable_range(
        parameter_name="x", base_value=Decimal("5"), ordered_variations=ordered, base_summary=base_summary,
    )
    assert result["includes_base"] is True
    assert result["min_value"] == Decimal("4")
    assert result["max_value"] == Decimal("6")


def test_stable_range_excludes_base_when_unstable() -> None:
    ordered = [_var(4, score=Decimal("80")), _var(5, score=Decimal("85"), trade_count=1), _var(6, score=Decimal("82"))]
    base_summary = {"strategy_score": Decimal("85"), "maximum_drawdown_rate": Decimal("10")}
    result = _compute_stable_range(
        parameter_name="x", base_value=Decimal("5"), ordered_variations=ordered, base_summary=base_summary,
    )
    # trade_count=1 < 최소 기준(3) -> 기준값 자체가 불안정
    assert result["includes_base"] is False


def test_stable_range_breaks_on_score_drop_outside_tolerance() -> None:
    ordered = [_var(4, score=Decimal("30")), _var(5, score=Decimal("85")), _var(6, score=Decimal("82"))]
    base_summary = {"strategy_score": Decimal("85"), "maximum_drawdown_rate": Decimal("10")}
    result = _compute_stable_range(
        parameter_name="x", base_value=Decimal("5"), ordered_variations=ordered, base_summary=base_summary,
    )
    # 4의 score=30은 기준(85) 대비 55점 하락 -> 허용치(20) 초과 -> 안정 구간에서 제외
    assert result["min_value"] == Decimal("5")


def test_performance_cliff_detects_high_severity_score_drop() -> None:
    ordered = [_var(4, score=Decimal("90")), _var(5, score=Decimal("20"))]
    cliffs = _detect_performance_cliffs(ordered)
    assert len(cliffs) == 1
    assert cliffs[0]["severity"] == "HIGH"


def test_performance_cliff_no_cliff_when_stable() -> None:
    ordered = [_var(4, score=Decimal("80")), _var(5, score=Decimal("82"))]
    cliffs = _detect_performance_cliffs(ordered)
    assert cliffs == []


def test_performance_cliff_severity_boundaries() -> None:
    from stock_platform.ai.strategy_draft_approval.parameter_sensitivity import _severity_for, _CLIFF_THRESHOLDS

    assert _severity_for(Decimal("50"), _CLIFF_THRESHOLDS["score"]) == "HIGH"
    assert _severity_for(Decimal("49.99"), _CLIFF_THRESHOLDS["score"]) == "MEDIUM"
    assert _severity_for(Decimal("30"), _CLIFF_THRESHOLDS["score"]) == "MEDIUM"
    assert _severity_for(Decimal("29.99"), _CLIFF_THRESHOLDS["score"]) == "LOW"
    assert _severity_for(Decimal("15"), _CLIFF_THRESHOLDS["score"]) == "LOW"
    assert _severity_for(Decimal("14.99"), _CLIFF_THRESHOLDS["score"]) is None


def test_sensitivity_status_insufficient_data_below_minimum_successful() -> None:
    status, reason = _determine_sensitivity_status(
        successful_count=2, robustness_score=Decimal("90"), stable_range=None, performance_cliffs=[],
        single_param=True,
    )
    assert status == "INSUFFICIENT_DATA"


def test_sensitivity_status_robust() -> None:
    stable_range = {"includes_base": True}
    status, reason = _determine_sensitivity_status(
        successful_count=5, robustness_score=Decimal("75"), stable_range=stable_range,
        performance_cliffs=[], single_param=True,
    )
    assert status == "ROBUST"


def test_sensitivity_status_fragile_on_high_cliff() -> None:
    stable_range = {"includes_base": True}
    status, reason = _determine_sensitivity_status(
        successful_count=5, robustness_score=Decimal("75"), stable_range=stable_range,
        performance_cliffs=[{"severity": "HIGH"}], single_param=True,
    )
    assert status == "FRAGILE"


def test_sensitivity_status_fragile_when_base_not_in_stable_range() -> None:
    status, reason = _determine_sensitivity_status(
        successful_count=5, robustness_score=Decimal("75"), stable_range={"includes_base": False},
        performance_cliffs=[], single_param=True,
    )
    assert status == "FRAGILE"


def test_sensitivity_status_acceptable_middle_score() -> None:
    stable_range = {"includes_base": True}
    status, reason = _determine_sensitivity_status(
        successful_count=5, robustness_score=Decimal("55"), stable_range=stable_range,
        performance_cliffs=[], single_param=True,
    )
    assert status == "ACCEPTABLE"


def test_sensitivity_status_two_param_cannot_be_robust() -> None:
    # 다중 파라미터는 Stable Range를 계산하지 않으므로(stable_range=None)
    # includes_base가 항상 False -> ROBUST에는 도달할 수 없다(문서화된 제약).
    status, reason = _determine_sensitivity_status(
        successful_count=10, robustness_score=Decimal("95"), stable_range=None,
        performance_cliffs=[], single_param=False,
    )
    assert status != "ROBUST"


# ---------------------------------------------------------------------------
# C/D: run_parameter_sensitivity 종단 간(합성 데이터)
# ---------------------------------------------------------------------------


def test_run_parameter_sensitivity_single_parameter_success(session) -> None:
    approval = _seed_and_approve(session)
    result = run_parameter_sensitivity(
        session, approval["strategy_definition_id"],
        parameter_names=["stop_loss_rule.value"], runtime_input=_default_runtime_input(),
        actor="STEP12_11_TEST:admin",
    )
    assert result["sensitivity_status"] in {"ROBUST", "ACCEPTABLE", "FRAGILE", "INSUFFICIENT_DATA"}
    assert len(result["variation_results"]) == 5  # 기본 5개 ratio
    assert result["successful_variation_count"] + result["failed_variation_count"] == 5


def test_run_parameter_sensitivity_two_parameters(session) -> None:
    approval = _seed_and_approve(session)
    result = run_parameter_sensitivity(
        session, approval["strategy_definition_id"],
        parameter_names=["stop_loss_rule.value", "take_profit_rule.value"],
        runtime_input=_default_runtime_input(), actor="STEP12_11_TEST:admin",
    )
    assert len(result["variation_results"]) == 25
    assert result["stable_range"] is None  # 다중 파라미터는 계산하지 않음


def test_run_parameter_sensitivity_unsupported_parameter_blocked(session) -> None:
    approval = _seed_and_approve(session)
    with pytest.raises(ParameterSensitivityError) as exc_info:
        run_parameter_sensitivity(
            session, approval["strategy_definition_id"],
            parameter_names=["entry_rules[0].indicator"],  # 문자열 필드 -> 추출되지 않음
            runtime_input=_default_runtime_input(), actor="STEP12_11_TEST:admin",
        )
    assert exc_info.value.code == "UNSUPPORTED_PARAMETER"


def test_run_parameter_sensitivity_too_many_parameters_blocked(session) -> None:
    approval = _seed_and_approve(session)
    with pytest.raises(ParameterSensitivityError) as exc_info:
        run_parameter_sensitivity(
            session, approval["strategy_definition_id"],
            parameter_names=["stop_loss_rule.value", "take_profit_rule.value", "position_sizing_rule.value"],
            runtime_input=_default_runtime_input(), actor="STEP12_11_TEST:admin",
        )
    assert exc_info.value.code == "TOO_MANY_PARAMETERS"


def test_run_parameter_sensitivity_definition_not_ready_blocked(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = StrategyDraftService(session).create(
        strategy_request_id=request["strategy_request_id"], **_manual_draft_kwargs()
    )
    svc = StrategyDraftApprovalService(session)
    approval = svc.approve(draft["draft_id"], actor="admin:7", reason="승인")
    svc.revoke(approval["approval_id"], actor="admin:9", reason="취소")
    with pytest.raises(ParameterSensitivityError) as exc_info:
        run_parameter_sensitivity(
            session, approval["strategy_definition_id"], parameter_names=["stop_loss_rule.value"],
            runtime_input=_default_runtime_input(), actor="STEP12_11_TEST:admin",
        )
    assert exc_info.value.code == "DEFINITION_NOT_READY"


def test_run_parameter_sensitivity_does_not_mutate_definition(session) -> None:
    approval = _seed_and_approve(session)
    definition_before = session.get(StrategyDefinitionEntity, approval["strategy_definition_id"])
    hash_before = definition_before.definition_hash
    payload_before = dict(definition_before.parameter_payload)

    run_parameter_sensitivity(
        session, approval["strategy_definition_id"], parameter_names=["stop_loss_rule.value"],
        runtime_input=_default_runtime_input(), actor="STEP12_11_TEST:admin",
    )
    session.expire_all()
    definition_after = session.get(StrategyDefinitionEntity, approval["strategy_definition_id"])
    assert definition_after.definition_hash == hash_before
    assert dict(definition_after.parameter_payload) == payload_before


def test_run_parameter_sensitivity_runtime_input_hash_consistent_across_variations(session) -> None:
    approval = _seed_and_approve(session)
    result = run_parameter_sensitivity(
        session, approval["strategy_definition_id"], parameter_names=["stop_loss_rule.value"],
        runtime_input=_default_runtime_input(), actor="STEP12_11_TEST:admin",
    )
    hashes = {v["runtime_input_hash"] for v in result["variation_results"] if v["status"] == "SUCCESS"}
    assert len(hashes) == 1  # 동일 Runtime Input이므로 모든 Variation에서 동일해야 한다.


def test_execution_input_hash_differs_across_variations_but_report_hash_is_singular(session) -> None:
    """STEP12-12 인수 조건 확인 — execution_input_hash(Variation별 실제
    실행 입력+override 반영)는 override 값이 다르면 달라져야 하고,
    report 전체의 input_hash(report_input_hash 개념)는 요청 1건당 1개만
    존재해야 한다. runtime_input_hash만으로는 이를 구별할 수 없었던
    STEP12-11 당시의 갭을 수정한 결과를 검증한다."""
    approval = _seed_and_approve(session)
    result = run_parameter_sensitivity(
        session, approval["strategy_definition_id"], parameter_names=["stop_loss_rule.value"],
        runtime_input=_default_runtime_input(), actor="STEP12_11_TEST:admin",
    )
    successful = [v for v in result["variation_results"] if v["status"] == "SUCCESS"]
    assert len(successful) >= 2
    execution_hashes = {v["execution_input_hash"] for v in successful}
    executable_hashes = {v["executable_hash"] for v in successful}
    # 서로 다른 stop_loss 값이면 executable_hash/execution_input_hash가 달라야 한다.
    assert len(executable_hashes) == len(successful)
    assert len(execution_hashes) == len(successful)
    # 반면 report 전체의 input_hash는 요청 1건당 정확히 1개다.
    assert isinstance(result["input_hash"], str) and len(result["input_hash"]) == 64


def test_run_parameter_sensitivity_individual_failure_is_fail_soft(session) -> None:
    approval = _seed_and_approve(session)
    # RSI period를 극단적으로 크게 만들면(+20%) 데이터 부족으로 그 Variation만
    # 실패하되 전체 실행은 계속돼야 한다(신뢰할 수 있게 재현하기는 어려우므로
    # 실행 결과 구조 자체 — status 필드가 존재하는지만 확인).
    result = run_parameter_sensitivity(
        session, approval["strategy_definition_id"], parameter_names=["entry_rules[0].lookback"],
        runtime_input=_default_runtime_input(), actor="STEP12_11_TEST:admin",
    )
    assert all(v["status"] in {"SUCCESS", "FAILED"} for v in result["variation_results"])


# ---------------------------------------------------------------------------
# E: Persistence / Idempotency
# ---------------------------------------------------------------------------


def test_run_parameter_sensitivity_persists_and_immutable(session) -> None:
    approval = _seed_and_approve(session)
    result = run_parameter_sensitivity(
        session, approval["strategy_definition_id"], parameter_names=["stop_loss_rule.value"],
        runtime_input=_default_runtime_input(), actor="STEP12_11_TEST:admin",
    )
    fetched = get_parameter_sensitivity_report(session, result["parameter_sensitivity_report_id"])
    assert fetched["sensitivity_status"] == result["sensitivity_status"]
    assert fetched["variation_results"] == result["variation_results"]


def test_run_parameter_sensitivity_rerun_creates_new_report(session) -> None:
    approval = _seed_and_approve(session)
    r1 = run_parameter_sensitivity(
        session, approval["strategy_definition_id"], parameter_names=["stop_loss_rule.value"],
        runtime_input=_default_runtime_input(), actor="STEP12_11_TEST:admin",
    )
    r2 = run_parameter_sensitivity(
        session, approval["strategy_definition_id"], parameter_names=["stop_loss_rule.value"],
        runtime_input=_default_runtime_input(), actor="STEP12_11_TEST:admin",
    )
    assert r1["parameter_sensitivity_report_id"] != r2["parameter_sensitivity_report_id"]


def test_run_parameter_sensitivity_idempotency_replay(session) -> None:
    approval = _seed_and_approve(session)
    r1 = run_parameter_sensitivity(
        session, approval["strategy_definition_id"], parameter_names=["stop_loss_rule.value"],
        runtime_input=_default_runtime_input(), actor="STEP12_11_TEST:admin",
        idempotency_key="step12-11-idem-1",
    )
    r2 = run_parameter_sensitivity(
        session, approval["strategy_definition_id"], parameter_names=["stop_loss_rule.value"],
        runtime_input=_default_runtime_input(), actor="STEP12_11_TEST:admin",
        idempotency_key="step12-11-idem-1",
    )
    assert r1["parameter_sensitivity_report_id"] == r2["parameter_sensitivity_report_id"]
    assert r2["idempotent_replay"] is True


def test_get_parameter_sensitivity_report_rejects_cross_strategy(session) -> None:
    approval = _seed_and_approve(session)
    result = run_parameter_sensitivity(
        session, approval["strategy_definition_id"], parameter_names=["stop_loss_rule.value"],
        runtime_input=_default_runtime_input(), actor="STEP12_11_TEST:admin",
    )
    with pytest.raises(ParameterSensitivityError) as exc_info:
        get_parameter_sensitivity_report(
            session, result["parameter_sensitivity_report_id"],
            strategy_definition_id=approval["strategy_definition_id"] + 999_999,
        )
    assert exc_info.value.code == "NOT_FOUND"


def test_get_parameter_sensitivity_report_not_found(session) -> None:
    with pytest.raises(ParameterSensitivityError) as exc_info:
        get_parameter_sensitivity_report(session, 999_999_999)
    assert exc_info.value.code == "NOT_FOUND"


# ---------------------------------------------------------------------------
# F: API / Auth
# ---------------------------------------------------------------------------


def test_parameter_sensitivity_api_requires_admin() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        "/api/v1/admin/strategies/1/parameter-sensitivity",
        json={
            "symbol": "X", "exchange_code": "KRX", "start_date": "2024-01-01", "end_date": "2024-04-30",
            "initial_capital": "1000000", "parameter_names": ["stop_loss_rule.value"],
        },
    )
    assert resp.status_code == 401


def test_parameter_sensitivity_api_success_and_get(session) -> None:
    approval = _seed_and_approve(session)
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        f"/api/v1/admin/strategies/{approval['strategy_definition_id']}/parameter-sensitivity",
        json={
            "symbol": _TEST_SYMBOL, "exchange_code": _TEST_EXCHANGE,
            "start_date": "2024-01-01", "end_date": "2024-04-30",
            "initial_capital": "1000000", "parameter_names": ["stop_loss_rule.value"],
        },
        headers={"X-Admin-API-Key": admin_key},
    )
    assert resp.status_code == 201
    report_id = resp.json()["parameter_sensitivity_report_id"]

    get_resp = client.get(
        f"/api/v1/admin/strategies/{approval['strategy_definition_id']}/parameter-sensitivity/{report_id}",
        headers={"X-Admin-API-Key": admin_key},
    )
    assert get_resp.status_code == 200

    summary_resp = client.get(
        f"/api/v1/admin/strategies/{approval['strategy_definition_id']}/parameter-sensitivity/{report_id}/summary",
        headers={"X-Admin-API-Key": admin_key},
    )
    assert summary_resp.status_code == 200
    assert "sensitivity_status" in summary_resp.json()

    variations_resp = client.get(
        f"/api/v1/admin/strategies/{approval['strategy_definition_id']}/parameter-sensitivity/{report_id}/variations",
        headers={"X-Admin-API-Key": admin_key},
    )
    assert variations_resp.status_code == 200
    assert len(variations_resp.json()["variation_results"]) == 5


def test_parameter_sensitivity_api_invalid_parameter_returns_400(session) -> None:
    approval = _seed_and_approve(session)
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        f"/api/v1/admin/strategies/{approval['strategy_definition_id']}/parameter-sensitivity",
        json={
            "symbol": _TEST_SYMBOL, "exchange_code": _TEST_EXCHANGE,
            "start_date": "2024-01-01", "end_date": "2024-04-30",
            "initial_capital": "1000000", "parameter_names": ["not_a_real_parameter"],
        },
        headers={"X-Admin-API-Key": admin_key},
    )
    assert resp.status_code == 400


def test_parameter_sensitivity_api_not_found(session) -> None:
    approval = _seed_and_approve(session)
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get(
        f"/api/v1/admin/strategies/{approval['strategy_definition_id']}/parameter-sensitivity/999999999",
        headers={"X-Admin-API-Key": admin_key},
    )
    assert resp.status_code == 404


def test_parameter_sensitivity_api_blocks_cross_strategy_report(session) -> None:
    approval = _seed_and_approve(session)
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        f"/api/v1/admin/strategies/{approval['strategy_definition_id']}/parameter-sensitivity",
        json={
            "symbol": _TEST_SYMBOL, "exchange_code": _TEST_EXCHANGE,
            "start_date": "2024-01-01", "end_date": "2024-04-30",
            "initial_capital": "1000000", "parameter_names": ["stop_loss_rule.value"],
        },
        headers={"X-Admin-API-Key": admin_key},
    )
    report_id = resp.json()["parameter_sensitivity_report_id"]
    other_id = approval["strategy_definition_id"] + 999_999
    cross_resp = client.get(
        f"/api/v1/admin/strategies/{other_id}/parameter-sensitivity/{report_id}",
        headers={"X-Admin-API-Key": admin_key},
    )
    assert cross_resp.status_code == 404


# ---------------------------------------------------------------------------
# G: Audit
# ---------------------------------------------------------------------------


def test_parameter_sensitivity_audit_events(session) -> None:
    from sqlalchemy import select

    from stock_platform.operation.audit_models import AuditEvent

    approval = _seed_and_approve(session)
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        f"/api/v1/admin/strategies/{approval['strategy_definition_id']}/parameter-sensitivity",
        json={
            "symbol": _TEST_SYMBOL, "exchange_code": _TEST_EXCHANGE,
            "start_date": "2024-01-01", "end_date": "2024-04-30",
            "initial_capital": "1000000", "parameter_names": ["stop_loss_rule.value"],
        },
        headers={"X-Admin-API-Key": admin_key},
    )
    report_id = resp.json()["parameter_sensitivity_report_id"]
    client.get(
        f"/api/v1/admin/strategies/{approval['strategy_definition_id']}/parameter-sensitivity/{report_id}",
        headers={"X-Admin-API-Key": admin_key},
    )
    events = session.execute(
        select(AuditEvent.event_type)
        .where(AuditEvent.strategy_id == str(approval["strategy_definition_id"]))
        .where(AuditEvent.event_type.like("PARAMETER_SENSITIVITY_%"))
        .order_by(AuditEvent.audit_event_id.desc())
        .limit(10)
    ).all()
    event_types = {e[0] for e in events}
    assert "PARAMETER_SENSITIVITY_STARTED" in event_types
    assert "PARAMETER_SENSITIVITY_COMPLETED" in event_types
    assert "PARAMETER_SENSITIVITY_VIEWED" in event_types


def test_parameter_sensitivity_audit_failed_event(session) -> None:
    from sqlalchemy import select

    from stock_platform.operation.audit_models import AuditEvent

    approval = _seed_and_approve(session)
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    client.post(
        f"/api/v1/admin/strategies/{approval['strategy_definition_id']}/parameter-sensitivity",
        json={
            "symbol": _TEST_SYMBOL, "exchange_code": _TEST_EXCHANGE,
            "start_date": "2024-01-01", "end_date": "2024-04-30",
            "initial_capital": "1000000", "parameter_names": ["bogus_parameter"],
        },
        headers={"X-Admin-API-Key": admin_key},
    )
    events = session.execute(
        select(AuditEvent.event_type)
        .where(AuditEvent.strategy_id == str(approval["strategy_definition_id"]))
        .where(AuditEvent.event_type == "PARAMETER_SENSITIVITY_FAILED")
        .order_by(AuditEvent.audit_event_id.desc())
        .limit(5)
    ).all()
    assert len(events) >= 1


# ---------------------------------------------------------------------------
# H: Regression — STEP12-10 / STEP12-9 / STEP12-8 / Backtest Engine
# ---------------------------------------------------------------------------


def test_step12_10_quality_gate_regression(session) -> None:
    from stock_platform.ai.strategy_draft_approval.quality_gate import run_quality_gate

    approval = _seed_and_approve(session)
    from stock_platform.ai.strategy_draft_approval.backtest_execution import (
        run_definition_backtest,
    )

    run_definition_backtest(
        session, approval["strategy_definition_id"], runtime_input=_default_runtime_input(),
        actor="STEP12_11_TEST:admin",
    )
    result = run_quality_gate(session, approval["strategy_definition_id"], actor="STEP12_11_TEST:admin")
    assert result["recommendation"] in {"APPROVE", "MANUAL_REVIEW", "REJECT"}


def test_step12_9_walk_forward_regression(session) -> None:
    from stock_platform.ai.strategy_draft_approval.walk_forward import run_walk_forward

    approval = _seed_and_approve(session)
    result = run_walk_forward(
        session, approval["strategy_definition_id"],
        start_date=date(2024, 1, 1), end_date=date(2024, 4, 30),
        train_days=45, test_days=45, scheme="ROLLING",
        symbol=_TEST_SYMBOL, exchange_code=_TEST_EXCHANGE,
        initial_capital=Decimal("1000000"), fee_ratio=Decimal("0.00015"),
        sell_tax_ratio=Decimal("0.0018"), slippage_ratio=Decimal("0"),
        actor="STEP12_11_TEST:admin",
    )
    assert result["completed_window_count"] == 2


def test_step12_8_performance_analytics_regression(session) -> None:
    from stock_platform.ai.strategy_draft_approval.backtest_execution import (
        run_definition_backtest,
    )
    from stock_platform.performance.backtest_analytics import analyze_backtest_run

    approval = _seed_and_approve(session)
    result = run_definition_backtest(
        session, approval["strategy_definition_id"], runtime_input=_default_runtime_input(),
        actor="STEP12_11_TEST:admin",
    )
    analysis = analyze_backtest_run(session, result["backtest_run_id"])
    assert "kpi" in analysis and "score" in analysis


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
