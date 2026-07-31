"""STEP 12-14 — Strategy Explainability & Decision Evidence Layer.

이미 승인된 Strategy Definition과 이미 완료된 검증 Report(Backtest/
Performance/Walk-Forward/Quality Gate/Parameter Sensitivity/Monte Carlo/
Portfolio Validation)만 읽어 사람이 이해할 수 있는 설명 + Evidence
Reference로 재구성한다. 새 Backtest/검증 계산을 수행하지 않고, 자동
승인·반려·Promotion을 수행하지 않는다."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from stock_platform.ai.strategy_draft.service import StrategyDraftService
from stock_platform.ai.strategy_draft_approval.backtest_execution import (
    get_latest_primary_backtest_run_id,
)
from stock_platform.ai.strategy_draft_approval.explainability import (
    BASE_EVIDENCE_WEIGHTS,
    MONTE_CARLO_RISK_OF_RUIN_THRESHOLD_PERCENT,
    ExplainabilityError,
    _build_decision_checklist,
    _build_decision_summary,
    _CategoryOutcome,
    _compute_completeness,
    _rule_sentence,
    compute_report_input_hash,
    get_explainability_report,
    run_generate_explainability,
)
from stock_platform.ai.strategy_draft_approval.monte_carlo import (
    run_monte_carlo_simulation,
)
from stock_platform.ai.strategy_draft_approval.parameter_sensitivity import (
    run_parameter_sensitivity,
)
from stock_platform.ai.strategy_draft_approval.portfolio_validation import (
    run_portfolio_validation,
)
from stock_platform.ai.strategy_draft_approval.quality_gate import run_quality_gate
from stock_platform.ai.strategy_draft_approval.service import (
    StrategyDraftApprovalService,
)
from stock_platform.ai.strategy_draft_approval.walk_forward import run_walk_forward
from stock_platform.ai.strategy_request.service import StrategyRequestService
from stock_platform.api.main import app
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory

pytestmark = pytest.mark.integration

_REQUESTER_USER_ID = 8
_REVIEWER_USER_ID = 7
_MARKER = "STEP12_14_TEST"
_TEST_EXCHANGE = "KRX"
_TEST_SYMBOL = "STEP1214A"


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
    # API를 통해 생성된 행은 requested_by가 테스트 마커가 아니라 실제 admin
    # 사용자명이라 패턴 매칭이 아니라 Strategy 소유 체인으로 걸러야 한다.
    "DELETE FROM trading.strategy_explainability_report WHERE strategy_id IN "
    "(SELECT strategy_id FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))",
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
    "DELETE FROM trading.walk_forward_window_metric WHERE strategy_performance_run_id IN "
    "(SELECT strategy_performance_run_id FROM trading.strategy_performance_run "
    "WHERE strategy_code LIKE 'DEFINITION_%' AND parameter_payload->>'requested_by' LIKE 'STEP12_14%')",
    "DELETE FROM trading.strategy_performance_metric WHERE strategy_performance_run_id IN "
    "(SELECT strategy_performance_run_id FROM trading.strategy_performance_run "
    "WHERE strategy_code LIKE 'DEFINITION_%' AND parameter_payload->>'requested_by' LIKE 'STEP12_14%')",
    "DELETE FROM trading.strategy_performance_run WHERE strategy_code LIKE 'DEFINITION_%' "
    "AND parameter_payload->>'requested_by' LIKE 'STEP12_14%'",
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
    "DELETE FROM strategy.candidate_result WHERE symbol = 'STEP1214SYN'",
    "DELETE FROM market.price_daily WHERE instrument_id IN "
    "(SELECT instrument_id FROM market.instrument WHERE symbol LIKE 'STEP1214%')",
    "DELETE FROM market.instrument WHERE symbol LIKE 'STEP1214%'",
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
            VALUES ('STOCK', :exchange, :symbol, 'STEP12-14 Test')
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
                VALUES (:iid, :td, :c, :c, :c, :c, 1000, 'STEP12_14_TEST')
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


def _synthesize_candidate_result_id(session, *, base_rank_no: int = 900) -> int:
    """dev DB의 strategy.candidate_result 실제 행 수에 의존하지 않도록,
    기존 candidate_run(run_id=1, 다른 candidate_result가 참조하지 않음)에
    새 candidate_result 행을 결정적으로 추가한다(STEP12-13과 동일 기법).
    기존 운영 데이터는 전혀 건드리지 않는다."""
    result_id = session.execute(
        text(
            """
            INSERT INTO strategy.candidate_result
            (run_id, rank_no, exchange_code, symbol, trade_date, total_score,
             rules_passed_count, all_rules_passed, rule_result, score_breakdown)
            VALUES (1, :rank_no, 'KRX', :symbol, :trade_date, 50, 1, true, '{}'::jsonb, '{}'::jsonb)
            RETURNING result_id
            """
        ),
        {"rank_no": base_rank_no, "symbol": "STEP1214SYN", "trade_date": date(2026, 7, 14)},
    ).scalar_one()
    session.commit()
    return int(result_id)


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


def _approve(session, strategy_request_id: int) -> dict:
    draft = StrategyDraftService(session).create(
        strategy_request_id=strategy_request_id, actor="admin:7", title="수동 초안",
        timeframe="1D", market_type="KR_STOCK",
        entry_rule='[{"indicator":"RSI","operator":"LT","threshold":30,"lookback":14}]',
        exit_rule='[{"indicator":"RSI","operator":"GT","threshold":70,"lookback":14}]',
        stop_loss_rule='{"type":"PERCENT","value":5}', take_profit_rule='{"type":"PERCENT","value":10}',
        position_sizing_rule='{"method":"FIXED_PERCENT","value":0.1}',
    )
    return StrategyDraftApprovalService(session).approve(draft["draft_id"], actor="admin:7", reason="승인")


def _runtime_input(**overrides) -> dict:
    base = {
        "symbol": _TEST_SYMBOL, "exchange_code": _TEST_EXCHANGE,
        "start_date": date(2024, 1, 1), "end_date": date(2024, 4, 30),
        "initial_capital": Decimal("1000000"), "fee_ratio": Decimal("0.00015"),
        "sell_tax_ratio": Decimal("0.0018"), "slippage_ratio": Decimal("0"),
    }
    base.update(overrides)
    return base


def _run_backtest(session, strategy_definition_id: int) -> int:
    from stock_platform.ai.strategy_draft_approval.backtest_execution import (
        run_definition_backtest,
    )

    result = run_definition_backtest(
        session, strategy_definition_id, runtime_input=_runtime_input(), actor="STEP12_14_TEST:admin",
    )
    return result["backtest_run_id"]


def _seed_full_strategy(session) -> dict:
    """승인된 Strategy 1개 + Backtest/Quality Gate/Parameter Sensitivity/
    Monte Carlo/Walk-Forward Report를 전부 생성한다(Explainability가 참조할
    대상 전체)."""
    ids = session.info["result_ids"]
    _seed_prices(session, _TEST_SYMBOL, _triangle_wave(150, period=30), start=date(2024, 1, 1))

    req = _create_approved_request(session, result_id=ids[0])
    approval = _approve(session, req["strategy_request_id"])
    strategy_id = approval["strategy_definition_id"]

    backtest_run_id = _run_backtest(session, strategy_id)
    quality_gate = run_quality_gate(session, strategy_id, actor="STEP12_14_TEST:admin")
    sensitivity = run_parameter_sensitivity(
        session, strategy_id, parameter_names=["stop_loss_rule.value"], runtime_input=_runtime_input(),
        actor="STEP12_14_TEST:admin",
    )
    monte_carlo = run_monte_carlo_simulation(
        session, strategy_id, backtest_run_id=backtest_run_id, simulation_method="BOOTSTRAP_WITH_REPLACEMENT",
        actor="STEP12_14_TEST:admin", simulation_count=100,
    )
    walk_forward = run_walk_forward(
        session, strategy_id,
        start_date=date(2024, 1, 1), end_date=date(2024, 4, 30), train_days=45, test_days=45, scheme="ROLLING",
        symbol=_TEST_SYMBOL, exchange_code=_TEST_EXCHANGE, initial_capital=Decimal("1000000"),
        fee_ratio=Decimal("0.00015"), sell_tax_ratio=Decimal("0.0018"), slippage_ratio=Decimal("0"),
        actor="STEP12_14_TEST:admin",
    )

    # 순수 PK DESC 기준 "진짜 최신" Backtest Run(Walk-Forward Window 포함)
    # — 대표 Backtest 자동 선택이 이것을 골라선 안 됨을 확인하는 회귀
    # 테스트용으로 별도 저장한다.
    from sqlalchemy import select as sa_select

    from stock_platform.backtest.persistence_models import BacktestRunEntity

    absolute_latest_backtest_run_id = session.execute(
        sa_select(BacktestRunEntity.backtest_run_id)
        .where(BacktestRunEntity.strategy_definition_id == strategy_id)
        .order_by(BacktestRunEntity.backtest_run_id.desc())
        .limit(1)
    ).scalar_one()

    return {
        "strategy_id": strategy_id,
        "backtest_run_id": backtest_run_id,
        "quality_gate_report_id": quality_gate["quality_gate_report_id"],
        "parameter_sensitivity_report_id": sensitivity["parameter_sensitivity_report_id"],
        "monte_carlo_report_id": monte_carlo["monte_carlo_report_id"],
        "walk_forward_run_id": walk_forward["strategy_performance_run_id"],
        "walk_forward_last_window_backtest_run_id": int(absolute_latest_backtest_run_id),
    }


# ---------------------------------------------------------------------------
# A: Rule Explanation — 순수 함수 단위(Template 문구).
# ---------------------------------------------------------------------------


def test_rule_sentence_entry_rsi_lt() -> None:
    sentence = _rule_sentence({"indicator": "RSI", "operator": "LT", "threshold": 30, "lookback": 14}, action="매수")
    assert sentence == "RSI(14)가 30 미만일 때 매수 신호를 생성합니다."


def test_rule_sentence_entry_rsi_lte() -> None:
    sentence = _rule_sentence({"indicator": "RSI", "operator": "LTE", "threshold": 30, "lookback": 14}, action="매수")
    assert sentence == "RSI(14)가 30 이하일 때 매수 신호를 생성합니다."


def test_rule_sentence_exit_rsi_gt() -> None:
    sentence = _rule_sentence({"indicator": "RSI", "operator": "GT", "threshold": 70, "lookback": 14}, action="청산")
    assert sentence == "RSI(14)가 70 초과일 때 청산 신호를 생성합니다."


def test_rule_sentence_unsupported_operator_fail_closed() -> None:
    sentence = _rule_sentence({"indicator": "RSI", "operator": "UNKNOWN_OP", "threshold": 30, "lookback": 14}, action="매수")
    assert "지원하지 않아" in sentence
    assert "자동 설명을 생성할 수 없습니다" in sentence


# ---------------------------------------------------------------------------
# B: Completeness Score — 순수 함수 단위(정확한 경계값).
# ---------------------------------------------------------------------------


def test_completeness_score_all_available_is_100() -> None:
    outcomes = [
        _CategoryOutcome(name, "AVAILABLE", w, w) for name, w in BASE_EVIDENCE_WEIGHTS.items()
    ]
    result = _compute_completeness(outcomes)
    assert result["score"] == Decimal("100.00")
    assert result["status"] == "COMPLETE"


def test_completeness_score_none_available_is_0_insufficient() -> None:
    outcomes = [
        _CategoryOutcome(name, "NOT_AVAILABLE", w, Decimal("0")) for name, w in BASE_EVIDENCE_WEIGHTS.items()
    ]
    result = _compute_completeness(outcomes)
    assert result["score"] == Decimal("0.00")
    assert result["status"] == "INSUFFICIENT"


def test_completeness_score_not_requested_excluded_from_denominator() -> None:
    """Portfolio가 선택되지 않으면(NOT_REQUESTED) 분모에서 완전히 제외되어
    나머지 8개 필수 항목만으로 100%가 나와야 한다."""
    outcomes = [
        _CategoryOutcome(name, "AVAILABLE", w, w) for name, w in BASE_EVIDENCE_WEIGHTS.items()
    ]
    outcomes.append(_CategoryOutcome("portfolio", "NOT_REQUESTED", Decimal("0"), Decimal("0")))
    result = _compute_completeness(outcomes)
    assert result["score"] == Decimal("100.00")


def test_completeness_score_required_missing_counts_as_unmet_not_excluded() -> None:
    """Portfolio와 달리 8개 필수 항목은 없어도(NOT_AVAILABLE) 분모에서
    빠지지 않고 미충족으로 집계되어야 한다(분모 제외가 아니라 0점 기여)."""
    outcomes = [
        _CategoryOutcome(name, "AVAILABLE", w, w) for name, w in BASE_EVIDENCE_WEIGHTS.items()
    ]
    # Quality Gate(15)만 없음 -> 85/100 = 85.00(분모에서 빠졌다면 100/85*100=100이 될 것).
    outcomes = [o for o in outcomes if o.name != "quality_gate"]
    outcomes.append(_CategoryOutcome("quality_gate", "NOT_AVAILABLE", BASE_EVIDENCE_WEIGHTS["quality_gate"], Decimal("0")))
    result = _compute_completeness(outcomes)
    assert result["score"] == Decimal("85.00")
    assert result["status"] == "SUBSTANTIAL"


@pytest.mark.parametrize(
    ("score", "expected_status"),
    [
        (Decimal("90.00"), "COMPLETE"),
        (Decimal("89.99"), "SUBSTANTIAL"),
        (Decimal("70.00"), "SUBSTANTIAL"),
        (Decimal("69.99"), "PARTIAL"),
        (Decimal("40.00"), "PARTIAL"),
        (Decimal("39.99"), "INSUFFICIENT"),
        (Decimal("0.00"), "INSUFFICIENT"),
    ],
)
def test_completeness_status_boundaries(score, expected_status) -> None:
    from stock_platform.ai.strategy_draft_approval.explainability import _completeness_status

    assert _completeness_status(score) == expected_status


# ---------------------------------------------------------------------------
# C: Decision Checklist / Decision Summary — 순수 함수 단위.
# ---------------------------------------------------------------------------


def test_decision_checklist_quality_gate_fail_detected() -> None:
    checklist = _build_decision_checklist(
        quality_gate_payload={"status": "AVAILABLE", "rules": [{"rule_name": "X", "status": "FAIL"}]},
        sensitivity_payload={"status": "NOT_AVAILABLE"},
        monte_carlo_payload={"status": "NOT_AVAILABLE"},
        walk_forward_payload={"status": "NOT_AVAILABLE"},
        portfolio_payload={"status": "NOT_REQUESTED"},
        provenance_payload={"all_provenance_matches": True},
    )
    item = next(c for c in checklist if c["code"] == "QUALITY_GATE_FAIL_EXISTS")
    assert item["answer"] is True


def test_decision_checklist_answer_none_when_evidence_missing() -> None:
    checklist = _build_decision_checklist(
        quality_gate_payload={"status": "NOT_AVAILABLE"},
        sensitivity_payload={"status": "NOT_AVAILABLE"},
        monte_carlo_payload={"status": "NOT_AVAILABLE"},
        walk_forward_payload={"status": "NOT_AVAILABLE"},
        portfolio_payload={"status": "NOT_REQUESTED"},
        provenance_payload={"all_provenance_matches": True},
    )
    for code in (
        "QUALITY_GATE_FAIL_EXISTS", "SENSITIVITY_BASE_OUTSIDE_STABLE_RANGE",
        "MONTE_CARLO_RISK_OF_RUIN_HIGH", "WALK_FORWARD_OVERFITTING_HIGH",
        "PORTFOLIO_DUPLICATE_EXPOSURE_HIGH",
    ):
        item = next(c for c in checklist if c["code"] == code)
        assert item["answer"] is None


def test_decision_checklist_monte_carlo_risk_of_ruin_threshold_boundary() -> None:
    below = _build_decision_checklist(
        quality_gate_payload={"status": "NOT_AVAILABLE"}, sensitivity_payload={"status": "NOT_AVAILABLE"},
        monte_carlo_payload={"status": "AVAILABLE", "risk_of_ruin_percent": MONTE_CARLO_RISK_OF_RUIN_THRESHOLD_PERCENT},
        walk_forward_payload={"status": "NOT_AVAILABLE"}, portfolio_payload={"status": "NOT_REQUESTED"},
        provenance_payload={"all_provenance_matches": True},
    )
    above = _build_decision_checklist(
        quality_gate_payload={"status": "NOT_AVAILABLE"}, sensitivity_payload={"status": "NOT_AVAILABLE"},
        monte_carlo_payload={"status": "AVAILABLE", "risk_of_ruin_percent": MONTE_CARLO_RISK_OF_RUIN_THRESHOLD_PERCENT + Decimal("0.01")},
        walk_forward_payload={"status": "NOT_AVAILABLE"}, portfolio_payload={"status": "NOT_REQUESTED"},
        provenance_payload={"all_provenance_matches": True},
    )
    assert next(c for c in below if c["code"] == "MONTE_CARLO_RISK_OF_RUIN_HIGH")["answer"] is False
    assert next(c for c in above if c["code"] == "MONTE_CARLO_RISK_OF_RUIN_HIGH")["answer"] is True


def test_decision_summary_blocking_forces_human_review() -> None:
    outcomes = [_CategoryOutcome("quality_gate", "AVAILABLE", Decimal("15"), Decimal("15"), "BLOCKING", "QUALITY_GATE_REJECT")]
    summary = _build_decision_summary(outcomes, completeness_status="COMPLETE")
    assert summary["blocking_count"] == 1
    assert summary["human_review_required"] is True


def test_decision_summary_all_positive_and_complete_no_human_review() -> None:
    outcomes = [_CategoryOutcome("quality_gate", "AVAILABLE", Decimal("15"), Decimal("15"), "POSITIVE", "QUALITY_GATE_APPROVE")]
    summary = _build_decision_summary(outcomes, completeness_status="COMPLETE")
    assert summary["human_review_required"] is False
    assert summary["positive_count"] == 1


def test_decision_summary_warning_alone_forces_human_review() -> None:
    """§ STEP12-14 필수 인수 보완 5 — Blocking이 없어도 Warning만 있으면
    검토가 필요하다(이전에는 Blocking에만 반응해 놓쳤던 케이스)."""
    outcomes = [_CategoryOutcome("quality_gate", "AVAILABLE", Decimal("15"), Decimal("15"), "WARNING", "QUALITY_GATE_MANUAL_REVIEW")]
    summary = _build_decision_summary(outcomes, completeness_status="COMPLETE")
    assert summary["blocking_count"] == 0
    assert summary["human_review_required"] is True


def test_decision_summary_missing_alone_forces_human_review() -> None:
    outcomes = [_CategoryOutcome("monte_carlo", "NOT_AVAILABLE", Decimal("10"), Decimal("0"), "MISSING", "MONTE_CARLO_NOT_AVAILABLE")]
    summary = _build_decision_summary(outcomes, completeness_status="COMPLETE")
    assert summary["human_review_required"] is True


def test_decision_summary_incomplete_completeness_forces_human_review_even_if_all_positive() -> None:
    outcomes = [_CategoryOutcome("quality_gate", "AVAILABLE", Decimal("15"), Decimal("15"), "POSITIVE", "QUALITY_GATE_APPROVE")]
    summary = _build_decision_summary(outcomes, completeness_status="SUBSTANTIAL")
    assert summary["blocking_count"] == 0
    assert summary["warning_count"] == 0
    assert summary["missing_count"] == 0
    assert summary["human_review_required"] is True


# ---------------------------------------------------------------------------
# D: Provenance / Report Input Hash — 순수 함수 단위.
# ---------------------------------------------------------------------------


def _base_hash_kwargs() -> dict:
    return dict(
        strategy_definition_id=1, definition_version=1, executable_hash="h",
        backtest_run_id=10, walk_forward_run_id=20, quality_gate_report_id=30,
        parameter_sensitivity_report_id=40, monte_carlo_report_id=50,
        portfolio_validation_report_id=None, explanation_mode="RULE_BASED", explanation_language="ko",
    )


def test_report_input_hash_stable_for_identical_input() -> None:
    assert compute_report_input_hash(**_base_hash_kwargs()) == compute_report_input_hash(**_base_hash_kwargs())


@pytest.mark.parametrize(
    "changed_field",
    ["backtest_run_id", "walk_forward_run_id", "quality_gate_report_id", "parameter_sensitivity_report_id", "monte_carlo_report_id", "executable_hash"],
)
def test_report_input_hash_sensitive_to_each_selected_report(changed_field) -> None:
    base = compute_report_input_hash(**_base_hash_kwargs())
    changed_kwargs = _base_hash_kwargs()
    changed_kwargs[changed_field] = 999 if changed_field != "executable_hash" else "different-hash"
    changed = compute_report_input_hash(**changed_kwargs)
    assert base != changed


# ---------------------------------------------------------------------------
# E: 종단 간 실행(합성 데이터) — Source Selection/Evidence/Persistence/API/Audit.
# ---------------------------------------------------------------------------


def test_run_generate_explainability_explicit_ids_success(session) -> None:
    seed = _seed_full_strategy(session)
    result = run_generate_explainability(
        session, seed["strategy_id"], backtest_run_id=seed["backtest_run_id"],
        walk_forward_run_id=seed["walk_forward_run_id"], quality_gate_report_id=seed["quality_gate_report_id"],
        parameter_sensitivity_report_id=seed["parameter_sensitivity_report_id"],
        monte_carlo_report_id=seed["monte_carlo_report_id"], actor="STEP12_14_TEST:admin",
    )
    assert result["completeness_status"] in {"COMPLETE", "SUBSTANTIAL", "PARTIAL", "INSUFFICIENT"}
    assert result["backtest_evidence"]["status"] == "AVAILABLE"
    assert result["quality_gate_evidence"]["status"] == "AVAILABLE"
    assert result["sensitivity_evidence"]["status"] == "AVAILABLE"
    assert result["monte_carlo_evidence"]["status"] == "AVAILABLE"
    assert result["walk_forward_evidence"]["status"] == "AVAILABLE"
    assert result["portfolio_evidence"]["status"] == "NOT_REQUESTED"
    assert len(result["evidence_reference"]) > 0


def test_run_generate_explainability_use_latest_when_missing(session) -> None:
    """STEP12-14 필수 인수 보완 §1 반영 — Walk-Forward가 내부적으로 더 늦게
    (더 큰 PK로) 생성한 Window Backtest Run이 있어도, "대표 Backtest"
    자동 선택은 PRIMARY(사용자가 직접 실행한 것)인 seed의 메인 Backtest를
    정확히 가리켜야 한다(더 이상 "아무 유효한 Run"이 아니라 정확한 PK)."""
    seed = _seed_full_strategy(session)
    result = run_generate_explainability(
        session, seed["strategy_id"], use_latest_when_missing=True, actor="STEP12_14_TEST:admin",
    )
    assert result["backtest_run_id"] == seed["backtest_run_id"]
    assert result["backtest_run_id"] != seed["walk_forward_last_window_backtest_run_id"]
    assert result["quality_gate_report_id"] == seed["quality_gate_report_id"]
    assert result["monte_carlo_report_id"] == seed["monte_carlo_report_id"]
    assert result["parameter_sensitivity_report_id"] == seed["parameter_sensitivity_report_id"]


def test_run_generate_explainability_latest_selection_deterministic_repeated_calls(session) -> None:
    """§ STEP12-13 인수 조건 1 재확인 — 동일 상태에서 반복 호출해도 항상
    동일한 최신 Report가 선택되어야 한다(PK DESC 결정적 정렬)."""
    seed = _seed_full_strategy(session)
    r1 = run_generate_explainability(session, seed["strategy_id"], use_latest_when_missing=True, actor="STEP12_14_TEST:admin")
    r2 = run_generate_explainability(session, seed["strategy_id"], use_latest_when_missing=True, actor="STEP12_14_TEST:admin")
    assert r1["backtest_run_id"] == r2["backtest_run_id"]
    assert r1["quality_gate_report_id"] == r2["quality_gate_report_id"]
    assert r1["monte_carlo_report_id"] == r2["monte_carlo_report_id"]


def test_run_generate_explainability_use_latest_when_missing_false_leaves_not_available(session) -> None:
    seed = _seed_full_strategy(session)
    result = run_generate_explainability(
        session, seed["strategy_id"], use_latest_when_missing=False, actor="STEP12_14_TEST:admin",
    )
    assert result["backtest_evidence"]["status"] == "NOT_AVAILABLE"
    assert result["quality_gate_evidence"]["status"] == "NOT_AVAILABLE"


def test_run_generate_explainability_cross_strategy_report_blocked(session) -> None:
    seed_a = _seed_full_strategy(session)
    ids = session.info["result_ids"]
    if len(ids) < 2:
        pytest.skip("두 번째 candidate_result 행이 없어 Cross-Strategy 차단을 재현할 수 없음")
    req_b = _create_approved_request(session, result_id=ids[1])
    approval_b = _approve(session, req_b["strategy_request_id"])

    with pytest.raises(ExplainabilityError) as exc_info:
        run_generate_explainability(
            session, approval_b["strategy_definition_id"], backtest_run_id=seed_a["backtest_run_id"],
            actor="STEP12_14_TEST:admin",
        )
    assert exc_info.value.code == "OWNERSHIP_MISMATCH"


def test_run_generate_explainability_unsupported_mode_blocked(session) -> None:
    seed = _seed_full_strategy(session)
    with pytest.raises(ExplainabilityError) as exc_info:
        run_generate_explainability(
            session, seed["strategy_id"], explanation_mode="RULE_BASED_WITH_LLM_ASSIST", actor="STEP12_14_TEST:admin",
        )
    assert exc_info.value.code == "UNSUPPORTED_EXPLANATION_MODE"


def test_run_generate_explainability_unsupported_language_blocked(session) -> None:
    seed = _seed_full_strategy(session)
    with pytest.raises(ExplainabilityError) as exc_info:
        run_generate_explainability(
            session, seed["strategy_id"], explanation_language="en", actor="STEP12_14_TEST:admin",
        )
    assert exc_info.value.code == "UNSUPPORTED_LANGUAGE"


def test_run_generate_explainability_no_backtest_at_all_is_missing_not_pass(session) -> None:
    """검증 Report가 전혀 없어도 임의 PASS로 설명하지 않고 NOT_AVAILABLE +
    Missing Evidence로 명시해야 한다."""
    ids = session.info["result_ids"]
    _seed_prices(session, _TEST_SYMBOL, _triangle_wave(150, period=30), start=date(2024, 1, 1))
    req = _create_approved_request(session, result_id=ids[0])
    approval = _approve(session, req["strategy_request_id"])

    result = run_generate_explainability(
        session, approval["strategy_definition_id"], use_latest_when_missing=True, actor="STEP12_14_TEST:admin",
    )
    assert result["backtest_evidence"]["status"] == "NOT_AVAILABLE"
    missing_categories = {m["category"] for m in result["missing_evidence"]}
    assert "backtest" in missing_categories
    assert result["completeness_status"] == "INSUFFICIENT"


def test_run_generate_explainability_persists_and_immutable(session) -> None:
    seed = _seed_full_strategy(session)
    result = run_generate_explainability(
        session, seed["strategy_id"], backtest_run_id=seed["backtest_run_id"], actor="STEP12_14_TEST:admin",
    )
    fetched = get_explainability_report(session, result["explainability_report_id"])
    assert fetched["backtest_evidence"] == result["backtest_evidence"]
    assert fetched["report_input_hash"] == result["report_input_hash"]


def test_run_generate_explainability_immutable_after_source_backtest_reanalyzed(session) -> None:
    from stock_platform.performance.backtest_analytics import analyze_backtest_run

    seed = _seed_full_strategy(session)
    result = run_generate_explainability(
        session, seed["strategy_id"], backtest_run_id=seed["backtest_run_id"], actor="STEP12_14_TEST:admin",
    )
    before = get_explainability_report(session, result["explainability_report_id"])
    analyze_backtest_run(session, seed["backtest_run_id"])
    after = get_explainability_report(session, result["explainability_report_id"])
    assert after["backtest_evidence"] == before["backtest_evidence"]
    assert after["report_input_hash"] == before["report_input_hash"]


def test_run_generate_explainability_rerun_creates_new_report(session) -> None:
    seed = _seed_full_strategy(session)
    r1 = run_generate_explainability(session, seed["strategy_id"], backtest_run_id=seed["backtest_run_id"], actor="STEP12_14_TEST:admin")
    r2 = run_generate_explainability(session, seed["strategy_id"], backtest_run_id=seed["backtest_run_id"], actor="STEP12_14_TEST:admin")
    assert r1["explainability_report_id"] != r2["explainability_report_id"]


def test_run_generate_explainability_idempotency_replay(session) -> None:
    seed = _seed_full_strategy(session)
    r1 = run_generate_explainability(
        session, seed["strategy_id"], backtest_run_id=seed["backtest_run_id"], actor="STEP12_14_TEST:admin",
        idempotency_key="step12-14-idem-1",
    )
    r2 = run_generate_explainability(
        session, seed["strategy_id"], backtest_run_id=seed["backtest_run_id"], actor="STEP12_14_TEST:admin",
        idempotency_key="step12-14-idem-1",
    )
    assert r1["explainability_report_id"] == r2["explainability_report_id"]
    assert r2["idempotent_replay"] is True


def test_run_generate_explainability_idempotency_conflict(session) -> None:
    seed = _seed_full_strategy(session)
    run_generate_explainability(
        session, seed["strategy_id"], backtest_run_id=seed["backtest_run_id"], actor="STEP12_14_TEST:admin",
        idempotency_key="step12-14-conflict",
    )
    with pytest.raises(ExplainabilityError) as exc_info:
        run_generate_explainability(
            # Monte Carlo Report를 명시적으로 배제(use_latest_when_missing=False)해
            # 첫 호출과 다른 report_input_hash를 만든다 — 대표 Backtest
            # 자동 선택이 PRIMARY만 고르도록 고친 뒤로는 backtest_run_id를
            # 생략해도(§ STEP12-14 필수 인수 보완 1) 동일 Strategy에서 항상
            # 같은 값으로 resolve되어 더 이상 이 차이만으로는 해시가
            # 달라지지 않는다.
            session, seed["strategy_id"], backtest_run_id=seed["backtest_run_id"],
            monte_carlo_report_id=None, use_latest_when_missing=False, actor="STEP12_14_TEST:admin",
            idempotency_key="step12-14-conflict",
        )
    assert exc_info.value.code == "IDEMPOTENCY_CONFLICT"


def test_run_generate_explainability_with_portfolio_evidence(session) -> None:
    ids = session.info["result_ids"]
    if len(ids) < 2:
        pytest.skip("두 번째 candidate_result 행이 없어 Portfolio 조합을 재현할 수 없음")

    seed_a = _seed_full_strategy(session)
    _seed_prices(session, "STEP1214B", _triangle_wave(150, period=30), start=date(2024, 1, 1))
    req_b = _create_approved_request(session, result_id=ids[1])
    approval_b = _approve(session, req_b["strategy_request_id"])
    from stock_platform.ai.strategy_draft_approval.backtest_execution import run_definition_backtest

    run_b = run_definition_backtest(
        session, approval_b["strategy_definition_id"],
        runtime_input=_runtime_input(symbol="STEP1214B"), actor="STEP12_14_TEST:admin",
    )

    portfolio_result = run_portfolio_validation(
        session, strategy_definition_ids=[seed_a["strategy_id"], approval_b["strategy_definition_id"]],
        backtest_run_ids=[seed_a["backtest_run_id"], run_b["backtest_run_id"]],
        weighting_method="EQUAL_WEIGHT", strategy_weights=None, alignment_policy="INTERSECTION",
        minimum_overlap_days=60, initial_capital=Decimal("10000000"),
        correlation_threshold=Decimal("0.7"), concentration_threshold=Decimal("0.40"),
        actor="STEP12_14_TEST:admin",
    )

    result = run_generate_explainability(
        session, seed_a["strategy_id"], backtest_run_id=seed_a["backtest_run_id"],
        portfolio_validation_report_id=portfolio_result["portfolio_validation_report_id"],
        actor="STEP12_14_TEST:admin",
    )
    assert result["portfolio_evidence"]["status"] == "AVAILABLE"
    assert result["portfolio_evidence"]["portfolio_validation_report_id"] == portfolio_result["portfolio_validation_report_id"]


def test_run_generate_explainability_portfolio_not_including_strategy_blocked(session) -> None:
    ids = session.info["result_ids"]
    if len(ids) < 2:
        pytest.skip("두 번째 candidate_result 행이 없어 재현할 수 없음")

    seed_a = _seed_full_strategy(session)
    _seed_prices(session, "STEP1214C", _triangle_wave(150, period=30), start=date(2024, 1, 1))
    req_b = _create_approved_request(session, result_id=ids[1])
    approval_b = _approve(session, req_b["strategy_request_id"])
    from stock_platform.ai.strategy_draft_approval.backtest_execution import run_definition_backtest

    run_b = run_definition_backtest(
        session, approval_b["strategy_definition_id"],
        runtime_input=_runtime_input(symbol="STEP1214C"), actor="STEP12_14_TEST:admin",
    )
    portfolio_result = run_portfolio_validation(
        session, strategy_definition_ids=[seed_a["strategy_id"], approval_b["strategy_definition_id"]],
        backtest_run_ids=[seed_a["backtest_run_id"], run_b["backtest_run_id"]],
        weighting_method="EQUAL_WEIGHT", strategy_weights=None, alignment_policy="INTERSECTION",
        minimum_overlap_days=60, initial_capital=Decimal("10000000"),
        correlation_threshold=Decimal("0.7"), concentration_threshold=Decimal("0.40"),
        actor="STEP12_14_TEST:admin",
    )

    # 이 Portfolio Report에 포함되지 않은 제3의 Strategy로 조회 시도. dev
    # DB의 실제 candidate_result 행 수(2개)에 의존하지 않도록 STEP12-13과
    # 동일한 방식으로 합성 행을 추가한다(기존 운영 데이터는 건드리지 않음).
    third_result_id = _synthesize_candidate_result_id(session)
    req_c = _create_approved_request(session, result_id=third_result_id)
    approval_c = _approve(session, req_c["strategy_request_id"])

    with pytest.raises(ExplainabilityError) as exc_info:
        run_generate_explainability(
            session, approval_c["strategy_definition_id"],
            portfolio_validation_report_id=portfolio_result["portfolio_validation_report_id"],
            actor="STEP12_14_TEST:admin",
        )
    assert exc_info.value.code == "OWNERSHIP_MISMATCH"


# ---------------------------------------------------------------------------
# F: API / Audit.
# ---------------------------------------------------------------------------


def test_explainability_api_requires_admin() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/api/v1/admin/strategies/1/explainability", json={})
    assert resp.status_code == 401


def test_explainability_api_success_and_all_views(session) -> None:
    seed = _seed_full_strategy(session)
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        f"/api/v1/admin/strategies/{seed['strategy_id']}/explainability",
        json={"backtest_run_id": seed["backtest_run_id"], "quality_gate_report_id": seed["quality_gate_report_id"]},
        headers={"X-Admin-API-Key": admin_key},
    )
    assert resp.status_code == 201
    report_id = resp.json()["report_id"]

    for suffix in ("", "/summary", "/evidence", "/checklist", "/missing"):
        r = client.get(
            f"/api/v1/admin/strategies/{seed['strategy_id']}/explainability/{report_id}{suffix}",
            headers={"X-Admin-API-Key": admin_key},
        )
        assert r.status_code == 200


def test_explainability_api_cross_strategy_view_blocked(session) -> None:
    seed = _seed_full_strategy(session)
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        f"/api/v1/admin/strategies/{seed['strategy_id']}/explainability",
        json={"backtest_run_id": seed["backtest_run_id"]},
        headers={"X-Admin-API-Key": admin_key},
    )
    report_id = resp.json()["report_id"]

    other_strategy_id = seed["strategy_id"] + 999999
    r = client.get(
        f"/api/v1/admin/strategies/{other_strategy_id}/explainability/{report_id}",
        headers={"X-Admin-API-Key": admin_key},
    )
    assert r.status_code == 404


def test_explainability_api_not_found(session) -> None:
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get(
        "/api/v1/admin/strategies/1/explainability/999999999", headers={"X-Admin-API-Key": admin_key},
    )
    assert resp.status_code == 404


def test_explainability_audit_events(session) -> None:
    from sqlalchemy import select

    from stock_platform.operation.audit_models import AuditEvent

    seed = _seed_full_strategy(session)
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        f"/api/v1/admin/strategies/{seed['strategy_id']}/explainability",
        json={"backtest_run_id": seed["backtest_run_id"]},
        headers={"X-Admin-API-Key": admin_key},
    )
    report_id = resp.json()["report_id"]
    client.get(
        f"/api/v1/admin/strategies/{seed['strategy_id']}/explainability/{report_id}",
        headers={"X-Admin-API-Key": admin_key},
    )
    events = session.execute(
        select(AuditEvent.event_type)
        .where(AuditEvent.event_type.like("EXPLAINABILITY_%"))
        .order_by(AuditEvent.audit_event_id.desc())
        .limit(10)
    ).all()
    event_types = {e[0] for e in events}
    assert "EXPLAINABILITY_STARTED" in event_types
    assert "EXPLAINABILITY_COMPLETED" in event_types
    assert "EXPLAINABILITY_VIEWED" in event_types


# ---------------------------------------------------------------------------
# G: Regression — STEP12-13/12/11/10/9/8.
# ---------------------------------------------------------------------------


def test_step12_13_portfolio_validation_regression(session) -> None:
    ids = session.info["result_ids"]
    if len(ids) < 2:
        pytest.skip("두 번째 candidate_result 행이 없어 재현할 수 없음")
    seed_a = _seed_full_strategy(session)
    _seed_prices(session, "STEP1214REG", _triangle_wave(150, period=30), start=date(2024, 1, 1))
    req_b = _create_approved_request(session, result_id=ids[1])
    approval_b = _approve(session, req_b["strategy_request_id"])
    from stock_platform.ai.strategy_draft_approval.backtest_execution import run_definition_backtest

    run_b = run_definition_backtest(
        session, approval_b["strategy_definition_id"],
        runtime_input=_runtime_input(symbol="STEP1214REG"), actor="STEP12_14_TEST:admin",
    )
    result = run_portfolio_validation(
        session, strategy_definition_ids=[seed_a["strategy_id"], approval_b["strategy_definition_id"]],
        backtest_run_ids=[seed_a["backtest_run_id"], run_b["backtest_run_id"]],
        weighting_method="EQUAL_WEIGHT", strategy_weights=None, alignment_policy="INTERSECTION",
        minimum_overlap_days=60, initial_capital=Decimal("10000000"),
        correlation_threshold=Decimal("0.7"), concentration_threshold=Decimal("0.40"),
        actor="STEP12_14_TEST:admin",
    )
    assert result["validation_status"] in {"DIVERSIFIED", "ACCEPTABLE", "CONCENTRATED", "HIGHLY_CORRELATED", "HIGH_RISK", "INSUFFICIENT_DATA"}


def test_step12_10_quality_gate_regression(session) -> None:
    seed = _seed_full_strategy(session)
    result = run_quality_gate(session, seed["strategy_id"], actor="STEP12_14_TEST:admin")
    assert result["recommendation"] in {"APPROVE", "MANUAL_REVIEW", "REJECT"}


# ---------------------------------------------------------------------------
# H: STEP12-14 필수 인수 보완(STEP12-15 착수 전 확인·수정).
# ---------------------------------------------------------------------------


def test_representative_backtest_excludes_walk_forward_window_runs(session) -> None:
    """§1 — Walk-Forward가 내부적으로 만든 Window Backtest Run이 나중에
    생성돼도(PK가 더 큼) "대표 Backtest"로 선택되면 안 된다."""
    seed = _seed_full_strategy(session)
    latest_primary = get_latest_primary_backtest_run_id(session, seed["strategy_id"])
    assert latest_primary == seed["backtest_run_id"]
    # Walk-Forward Window Run이 실제로 더 나중(더 큰 PK)에 생성됐는지도 확인.
    assert latest_primary < seed["walk_forward_last_window_backtest_run_id"]


def test_representative_backtest_selection_is_deterministic_repeated_calls(session) -> None:
    seed = _seed_full_strategy(session)
    first = get_latest_primary_backtest_run_id(session, seed["strategy_id"])
    second = get_latest_primary_backtest_run_id(session, seed["strategy_id"])
    assert first == second == seed["backtest_run_id"]


def test_quality_gate_latest_backtest_excludes_walk_forward_window_runs(session) -> None:
    """§1 — Quality Gate도 동일 Helper를 재사용하므로 동일하게 보호된다."""
    from stock_platform.ai.strategy_draft_approval.quality_gate import _latest_backtest_run

    seed = _seed_full_strategy(session)
    run = _latest_backtest_run(session, seed["strategy_id"])
    assert int(run.backtest_run_id) == seed["backtest_run_id"]


def test_explainability_does_not_recompute_or_rewrite_performance_tables(session) -> None:
    """§2 — Explainability 생성 전후 backtest_run.parameters(Performance
    Analytics 포함)이 완전히 동일해야 한다(재계산·재저장 금지)."""
    from sqlalchemy import select as sa_select

    from stock_platform.backtest.persistence_models import BacktestRunEntity

    seed = _seed_full_strategy(session)
    before = session.execute(
        sa_select(BacktestRunEntity.parameters).where(
            BacktestRunEntity.backtest_run_id == seed["backtest_run_id"]
        )
    ).scalar_one()

    run_generate_explainability(
        session, seed["strategy_id"], backtest_run_id=seed["backtest_run_id"], actor="STEP12_14_TEST:admin",
    )

    session.expire_all()
    after = session.execute(
        sa_select(BacktestRunEntity.parameters).where(
            BacktestRunEntity.backtest_run_id == seed["backtest_run_id"]
        )
    ).scalar_one()
    assert after == before


def test_explainability_performance_evidence_not_available_when_never_computed(session) -> None:
    """§2 — analyze_backtest_run()이 한 번도 호출되지 않은 Backtest Run은
    Explainability가 이를 계산하지 않고 NOT_AVAILABLE로 처리해야 한다."""
    ids = session.info["result_ids"]
    _seed_prices(session, "STEP1214NOPERF", _triangle_wave(150, period=30), start=date(2024, 1, 1))
    req = _create_approved_request(session, result_id=ids[0])
    approval = _approve(session, req["strategy_request_id"])
    from stock_platform.ai.strategy_draft_approval.backtest_execution import run_definition_backtest

    run = run_definition_backtest(
        session, approval["strategy_definition_id"],
        runtime_input=_runtime_input(symbol="STEP1214NOPERF"), actor="STEP12_14_TEST:admin",
    )
    # analyze_backtest_run()을 의도적으로 호출하지 않는다(Performance
    # Analytics가 저장되지 않은 상태를 재현).
    result = run_generate_explainability(
        session, approval["strategy_definition_id"], backtest_run_id=run["backtest_run_id"],
        actor="STEP12_14_TEST:admin",
    )
    assert result["backtest_evidence"]["status"] == "AVAILABLE"  # Backtest 자체는 available
    assert result["backtest_evidence"]["performance_status"] == "NOT_AVAILABLE"
    assert "cagr" not in result["backtest_evidence"] or result["backtest_evidence"].get("cagr") is None
    missing_categories = {m["category"] for m in result["missing_evidence"]}
    assert "performance_analytics" in missing_categories


def test_explainability_backtest_evidence_performance_status_available_when_computed(session) -> None:
    seed = _seed_full_strategy(session)
    result = run_generate_explainability(
        session, seed["strategy_id"], backtest_run_id=seed["backtest_run_id"], actor="STEP12_14_TEST:admin",
    )
    assert result["backtest_evidence"]["performance_status"] == "AVAILABLE"
    assert "cagr" in result["backtest_evidence"]


def test_completeness_calculation_table(session) -> None:
    """§4 — Completeness 계산표를 명시적으로 고정한다: 필수 8개 모두
    충족(100) / Performance만 누락(85) / Provenance mismatch만 없음(95)."""
    all_available = [_CategoryOutcome(name, "AVAILABLE", w, w) for name, w in BASE_EVIDENCE_WEIGHTS.items()]
    assert _compute_completeness(all_available)["score"] == Decimal("100.00")

    performance_missing = [o for o in all_available if o.name != "performance_analytics"]
    performance_missing.append(
        _CategoryOutcome("performance_analytics", "NOT_AVAILABLE", BASE_EVIDENCE_WEIGHTS["performance_analytics"], Decimal("0"))
    )
    assert _compute_completeness(performance_missing)["score"] == Decimal("85.00")

    provenance_missing = [o for o in all_available if o.name != "provenance"]
    provenance_missing.append(
        _CategoryOutcome("provenance", "PROVENANCE_MISMATCH", BASE_EVIDENCE_WEIGHTS["provenance"], Decimal("0"))
    )
    assert _compute_completeness(provenance_missing)["score"] == Decimal("95.00")


def test_completeness_portfolio_requested_but_missing_included_in_denominator_as_unmet() -> None:
    """§4 — Portfolio를 요청했는데 못 찾으면(NOT_AVAILABLE) "선택 안 됨"과
    달리 분모(10)에 포함되고 미충족으로 집계돼야 한다."""
    from stock_platform.ai.strategy_draft_approval.explainability import PORTFOLIO_EVIDENCE_WEIGHT

    all_available = [_CategoryOutcome(name, "AVAILABLE", w, w) for name, w in BASE_EVIDENCE_WEIGHTS.items()]
    with_missing_portfolio = all_available + [
        _CategoryOutcome("portfolio", "NOT_AVAILABLE", PORTFOLIO_EVIDENCE_WEIGHT, Decimal("0"))
    ]
    result = _compute_completeness(with_missing_portfolio)
    # 100/(100+10) = 90.909... -> 90.91
    assert result["score"] == Decimal("90.91")
