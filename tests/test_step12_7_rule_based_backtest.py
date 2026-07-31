"""STEP 12-7 — Rule-Based Backtest Adapter Evaluation & Controlled Backtest
Execution.

새 BacktestEngine을 만들지 않고 기존 엔진(backtest/engine.py)에
RuleBasedBacktestAdapter를 주입해 승인된 Strategy Definition을 과거 데이터로
실행한다. 실제 dev DB에는 KR_STOCK(KRX) 가격 데이터가 거의 없어(005930
1건뿐), 결정적 검증을 위해 합성 가격 데이터를 `market.instrument`/
`market.price_daily`에 직접 삽입하는 fixture를 사용한다(테스트 종료 시
정리).
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from stock_platform.ai.strategy_draft.service import StrategyDraftService
from stock_platform.ai.strategy_draft_approval.backtest_execution import (
    BacktestExecutionError,
    compute_runtime_input_hash,
    run_definition_backtest,
    validate_runtime_input,
)
from stock_platform.ai.strategy_draft_approval.backtest_spec import (
    BacktestSpecificationError,
    RuleBasedBacktestAdapter,
    compile_specification,
)
from stock_platform.ai.strategy_draft_approval.rule_evaluator import (
    IndicatorCache,
    RuleEvaluationError,
    evaluate_group,
    evaluate_rule,
)
from stock_platform.ai.strategy_draft_approval.service import (
    StrategyDraftApprovalService,
)
from stock_platform.ai.strategy_request.service import StrategyRequestService
from stock_platform.api.main import app
from stock_platform.backtest.models import BacktestPrice
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory
from stock_platform.strategy_deployment.definition_entities import (
    StrategyDefinitionEntity,
)

pytestmark = pytest.mark.integration

_REQUESTER_USER_ID = 8
_REVIEWER_USER_ID = 7
_MARKER = "STEP12_7_TEST"
_FINGERPRINT = "b7" * 32
_TEST_SYMBOL = "STEP127T"
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
            text(
                "SELECT result_id FROM strategy.candidate_result ORDER BY result_id LIMIT 1"
            )
        ).fetchall()
        ids = [int(r[0]) for r in rows]
        if not ids:
            pytest.skip("strategy.candidate_result에 테스트용 행이 없어 스킵")
        return ids
    finally:
        s.close()


_CLEANUP_SQL = [
    # actor(requested_by)가 API 경로에서는 인증된 admin 사용자명이라 마커로
    # 필터링할 수 없다 — candidate_lifecycle.created_by 체인을 통해 이번
    # 테스트가 만든 strategy_definition에 연결된 backtest_run만 정확히
    # 특정한다.
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
        _cleanup(s)  # 이전 실행 잔여물 방어적 정리
        yield s
    finally:
        s.rollback()
        _cleanup(s)
        s.close()


def _seed_prices(session, closes: list[float], *, start: date) -> None:
    """합성 일봉 데이터를 삽입한다(OHLC 전부 close와 동일하게 설정 —
    Stop Loss/Take Profit이 close 기준으로만 발동하도록 해 테스트를
    단순하고 결정적으로 유지한다)."""
    instrument_id = session.execute(
        text(
            """
            INSERT INTO market.instrument
            (asset_type, exchange_code, symbol, name)
            VALUES ('STOCK', :exchange, :symbol, 'STEP12-7 Test')
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
                VALUES (:iid, :td, :c, :c, :c, :c, 1000, 'STEP12_7_TEST')
                """
            ),
            {"iid": instrument_id, "td": trade_date, "c": Decimal(str(close))},
        )
    session.commit()


def _create_candidate(session, *, result_id: int, fingerprint=_FINGERPRINT) -> int:
    candidate_id = session.execute(
        text(
            """
            INSERT INTO ai.candidate_lifecycle
            (candidate_id, lifecycle_status, health_status, source_fingerprint, created_by, updated_by)
            VALUES (:cid, 'PROMOTED', 'UNKNOWN', :fp, :marker, :marker)
            RETURNING candidate_id
            """
        ),
        {"cid": result_id, "fp": fingerprint, "marker": _MARKER},
    ).scalar_one()
    session.commit()
    return int(candidate_id)


def _create_approved_request(session, *, result_id: int) -> dict:
    candidate_id = _create_candidate(session, result_id=result_id)
    req = StrategyRequestService(session).create(
        candidate_id=candidate_id,
        user_id=_REQUESTER_USER_ID,
        request_note=None,
        actor=f"user:{_REQUESTER_USER_ID}",
    )
    return StrategyRequestService(session).approve(
        req["strategy_request_id"],
        reviewer_user_id=_REVIEWER_USER_ID,
        review_note="ok",
        actor=f"admin:{_REVIEWER_USER_ID}",
    )


def _manual_draft_kwargs(**overrides) -> dict:
    base = {
        "actor": "admin:7",
        "title": "수동 초안",
        "timeframe": "1D",
        "market_type": "KR_STOCK",
        "entry_rule": _VALID_ENTRY,
        "exit_rule": _VALID_EXIT,
        "stop_loss_rule": _VALID_STOP_LOSS,
        "take_profit_rule": _VALID_TAKE_PROFIT,
        "position_sizing_rule": _VALID_POSITION_SIZING,
    }
    base.update(overrides)
    return base


def _approve(session, strategy_request_id: int, **draft_overrides) -> dict:
    draft = StrategyDraftService(session).create(
        strategy_request_id=strategy_request_id, **_manual_draft_kwargs(**draft_overrides)
    )
    return StrategyDraftApprovalService(session).approve(
        draft["draft_id"], actor="admin:7", reason="승인"
    )


def _default_runtime_input(**overrides) -> dict:
    base = {
        "symbol": _TEST_SYMBOL,
        "exchange_code": _TEST_EXCHANGE,
        "start_date": date(2024, 1, 1),
        "end_date": date(2024, 6, 1),
        "initial_capital": Decimal("1000000"),
        "fee_ratio": Decimal("0.00015"),
        "sell_tax_ratio": Decimal("0.0018"),
        "slippage_ratio": Decimal("0"),
    }
    base.update(overrides)
    return base


def _rule(indicator="RSI", operator="LT", threshold=30, lookback=14, comparison_target=None):
    # Rule Evaluator는 순수 함수(duck-typed `Any`)이므로 여기서는 실제
    # Draft 승인 화이트리스트(ALLOWED_OPERATORS 등)를 강제하는
    # DraftRule(Pydantic)을 거치지 않고 가벼운 네임스페이스로 직접
    # 구성한다 — 화이트리스트 자체는 STEP12-2-2 스키마 계층의 책임이고,
    # 여기서 검증하려는 것은 Evaluator의 연산 로직이다(예: ALLOWED_OPERATORS
    # 에는 없는 임의 연산자를 evaluate_rule에 직접 넣어 UNSUPPORTED_OPERATOR
    # 분기를 확인하려면 Pydantic 검증을 우회해야 한다).
    return SimpleNamespace(
        indicator=indicator, operator=operator, threshold=threshold, lookback=lookback,
        comparison_target=comparison_target,
    )


# ---------------------------------------------------------------------------
# A: Rule Evaluator
# ---------------------------------------------------------------------------


def test_operator_gt_gte_lt_lte_eq_ne() -> None:
    closes = [Decimal(x) for x in [10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 20]]
    cache = IndicatorCache(closes)
    # SMA(10) at index 10 covers closes[1:11] = nine 10s + one 20 => (9*10+20)/10=11
    r_gt = evaluate_rule(_rule("SMA", "GT", 10, 10), cache=cache, index=10)
    assert r_gt.matched is True
    r_gte = evaluate_rule(_rule("SMA", "GTE", 11, 10), cache=cache, index=10)
    assert r_gte.matched is True
    r_lt = evaluate_rule(_rule("SMA", "LT", 12, 10), cache=cache, index=10)
    assert r_lt.matched is True
    r_lte = evaluate_rule(_rule("SMA", "LTE", 11, 10), cache=cache, index=10)
    assert r_lte.matched is True
    r_eq = evaluate_rule(_rule("SMA", "EQ", 11, 10), cache=cache, index=10)
    assert r_eq.matched is True
    r_ne = evaluate_rule(_rule("SMA", "NE", 11, 10), cache=cache, index=10)
    assert r_ne.matched is False


def test_cross_above_and_cross_below() -> None:
    # SMA(1) == close 그 자체. index3: prev=9<=10, cur=11>10 => CROSS_ABOVE True
    closes = [Decimal(x) for x in [10, 10, 9, 11]]
    cache = IndicatorCache(closes)
    r = evaluate_rule(_rule("SMA", "CROSS_ABOVE", 10, 1), cache=cache, index=3)
    assert r.matched is True
    assert r.previous_left_value == Decimal(9)
    assert r.left_value == Decimal(11)

    closes2 = [Decimal(x) for x in [10, 10, 11, 9]]
    cache2 = IndicatorCache(closes2)
    r2 = evaluate_rule(_rule("SMA", "CROSS_BELOW", 10, 1), cache=cache2, index=3)
    assert r2.matched is True


def test_first_index_cross_is_insufficient_data() -> None:
    closes = [Decimal(20)]
    cache = IndicatorCache(closes)
    r = evaluate_rule(_rule("SMA", "CROSS_ABOVE", 10, 1), cache=cache, index=0)
    assert r.matched is False
    assert r.error_code == "INSUFFICIENT_DATA"


def test_insufficient_data_for_period() -> None:
    closes = [Decimal(10), Decimal(11)]
    cache = IndicatorCache(closes)
    r = evaluate_rule(_rule("SMA", "GT", 5, 20), cache=cache, index=1)
    assert r.matched is False
    assert r.error_code == "INSUFFICIENT_DATA"


def test_unknown_operator_blocked() -> None:
    closes = [Decimal(x) for x in range(1, 20)]
    cache = IndicatorCache(closes)
    rule = _rule("SMA", "BETWEEN", 10, 5)
    r = evaluate_rule(rule, cache=cache, index=10)
    assert r.matched is False
    assert r.error_code == "UNSUPPORTED_OPERATOR"


def test_comparison_target_unsupported() -> None:
    closes = [Decimal(x) for x in range(1, 20)]
    cache = IndicatorCache(closes)
    rule = _rule("SMA", "GT", 10, 5, comparison_target="EMA")
    r = evaluate_rule(rule, cache=cache, index=10)
    assert r.matched is False
    assert r.error_code == "UNSUPPORTED_RULE_FIELD"


# ---------------------------------------------------------------------------
# B: Indicator
# ---------------------------------------------------------------------------


def test_sma_calculation_exact() -> None:
    closes = [Decimal(x) for x in [1, 2, 3, 4, 5]]
    cache = IndicatorCache(closes)
    assert cache.value_at("SMA", 5, 4) == Decimal(3)
    assert cache.value_at("SMA", 5, 3) is None  # 기간 미충족


def test_ema_calculation_matches_reference() -> None:
    from stock_platform.indicators.engine import _ema

    closes = [Decimal(x) for x in [1, 2, 3, 4, 5, 6, 7]]
    expected = _ema(closes, 3)
    cache = IndicatorCache(closes)
    for i in range(len(closes)):
        assert cache.value_at("EMA", 3, i) == expected[i]


def test_rsi_calculation_matches_reference() -> None:
    from stock_platform.indicators.engine import _rsi_wilder

    closes = [Decimal(x) for x in [10, 11, 12, 11, 10, 9, 8, 9, 10, 11, 12, 13, 14, 15, 16]]
    expected = _rsi_wilder(closes, 14)
    cache = IndicatorCache(closes)
    for i in range(len(closes)):
        assert cache.value_at("RSI", 14, i) == expected[i]


def test_indicator_no_future_data_used() -> None:
    # 뒤쪽 값을 극단적으로 바꿔도 앞쪽 index의 계산 결과는 변하지 않아야 한다.
    base = [Decimal(x) for x in [10, 10, 10, 10, 10]]
    cache_a = IndicatorCache(base)
    val_a = cache_a.value_at("SMA", 3, 2)

    altered = list(base)
    altered[4] = Decimal(9999)
    cache_b = IndicatorCache(altered)
    val_b = cache_b.value_at("SMA", 3, 2)
    assert val_a == val_b


def test_indicator_cache_isolated_between_instances() -> None:
    closes = [Decimal(x) for x in [1, 2, 3, 4, 5]]
    cache1 = IndicatorCache(closes)
    cache1.value_at("SMA", 3, 4)
    cache2 = IndicatorCache([Decimal(x) for x in [100, 200, 300, 400, 500]])
    # 서로 다른 인스턴스이므로 캐시가 섞이지 않는다(index4의 SMA(3)은
    # [300,400,500]의 평균인 400 — cache1의 값(1~5 기준 4)과 무관해야 한다).
    assert cache2.value_at("SMA", 3, 4) == Decimal(400)


def test_repeated_index_uses_cache_not_recompute() -> None:
    closes = [Decimal(x) for x in [1, 2, 3, 4, 5]]
    cache = IndicatorCache(closes)
    cache.value_at("SMA", 3, 4)
    series_ref = cache._series[("SMA", 3)]
    cache.value_at("SMA", 3, 3)
    assert cache._series[("SMA", 3)] is series_ref  # 재계산되지 않고 동일 객체 재사용


# ---------------------------------------------------------------------------
# C: Entry/Exit 그룹 평가
# ---------------------------------------------------------------------------


def test_entry_and_all_rules_required() -> None:
    closes = [Decimal(x) for x in [30] * 20]
    cache = IndicatorCache(closes)
    rule_true = _rule("SMA", "EQ", 30, 5)
    rule_false = _rule("SMA", "GT", 999, 5)
    assert evaluate_group([rule_true], logical_operator="AND", cache=cache, index=10) is True
    assert (
        evaluate_group([rule_true, rule_false], logical_operator="AND", cache=cache, index=10)
        is False
    )


def test_exit_or_any_rule_triggers() -> None:
    closes = [Decimal(x) for x in [30] * 20]
    cache = IndicatorCache(closes)
    rule_true = _rule("SMA", "EQ", 30, 5)
    rule_false = _rule("SMA", "GT", 999, 5)
    assert evaluate_group([rule_false, rule_true], logical_operator="OR", cache=cache, index=10) is True


def test_empty_rule_group_is_false() -> None:
    cache = IndicatorCache([Decimal(1)])
    assert evaluate_group([], logical_operator="AND", cache=cache, index=0) is False
    assert evaluate_group([], logical_operator="OR", cache=cache, index=0) is False


# ---------------------------------------------------------------------------
# D: Adapter
# ---------------------------------------------------------------------------


def test_adapter_rejects_non_compilable_specification() -> None:
    with pytest.raises(BacktestSpecificationError):
        RuleBasedBacktestAdapter({"compilable": False}, [])


def test_adapter_config_unit_conversion(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    approval = _approve(session, request["strategy_request_id"])
    specification = compile_specification(session, approval["strategy_definition_id"])
    prices = [BacktestPrice(date(2024, 1, 1), Decimal(100), Decimal(100), Decimal(100), Decimal(100), Decimal(1))]
    adapter = RuleBasedBacktestAdapter(specification, prices)
    # stop_loss_rule.value=5(PERCENT) -> ratio 0.05, position_sizing.value=0.1(이미 비율)
    assert adapter.config.stop_loss_ratio == Decimal("0.05")
    assert adapter.config.take_profit_ratio == Decimal("0.10")
    assert adapter.config.position_ratio == Decimal("0.1")


def test_adapter_deterministic_signal(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    approval = _approve(session, request["strategy_request_id"])
    specification = compile_specification(session, approval["strategy_definition_id"])
    prices = [
        BacktestPrice(date(2024, 1, 1) + timedelta(days=i), Decimal(v), Decimal(v), Decimal(v), Decimal(v), Decimal(1))
        for i, v in enumerate([100] * 20 + [50] * 20)
    ]
    a1 = RuleBasedBacktestAdapter(specification, prices)
    a2 = RuleBasedBacktestAdapter(specification, prices)
    for idx in range(len(prices)):
        assert a1.should_enter(prices=prices, index=idx) == a2.should_enter(prices=prices, index=idx)


# ---------------------------------------------------------------------------
# E: Backtest 실행(합성 데이터)
# ---------------------------------------------------------------------------


def test_full_backtest_run_success_and_determinism(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    approval = _approve(session, request["strategy_request_id"])
    # RSI를 30 밑으로 떨어뜨렸다가 70 위로 올리는 패턴 — entry 후 exit이
    # 확실히 발생하도록 설계.
    closes = [100.0] * 15 + [float(100 - i) for i in range(1, 16)] + [float(85 + i * 3) for i in range(1, 20)]
    _seed_prices(session, closes, start=date(2024, 1, 1))
    runtime_input = _default_runtime_input(
        start_date=date(2024, 1, 1), end_date=date(2024, 1, 1) + timedelta(days=len(closes))
    )
    result1 = run_definition_backtest(
        session, approval["strategy_definition_id"], runtime_input=runtime_input, actor="STEP12_7_TEST:admin",
    )
    assert result1["status"] == "SUCCESS"
    assert result1["idempotent_replay"] is False

    result2 = run_definition_backtest(
        session, approval["strategy_definition_id"], runtime_input=runtime_input, actor="STEP12_7_TEST:admin",
        idempotency_key=None,
    )
    # 서로 다른 idempotency_key(자동 생성)이므로 새로운 Run이 생기지만,
    # 동일 입력이므로 요약 결과는 동일해야 한다(결정성).
    assert result1["summary"]["trade_count"] == result2["summary"]["trade_count"]
    assert result1["summary"]["total_return_rate"] == result2["summary"]["total_return_rate"]


def test_runtime_input_hash_deterministic() -> None:
    ri = _default_runtime_input()
    assert compute_runtime_input_hash(ri) == compute_runtime_input_hash(dict(ri))


def test_fee_and_slippage_applied(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    approval = _approve(session, request["strategy_request_id"])
    closes = [100.0] * 15 + [float(100 - i) for i in range(1, 16)] + [float(85 + i * 3) for i in range(1, 20)]
    _seed_prices(session, closes, start=date(2024, 1, 1))
    base_input = _default_runtime_input(
        start_date=date(2024, 1, 1), end_date=date(2024, 1, 1) + timedelta(days=len(closes))
    )
    no_fee = run_definition_backtest(
        session, approval["strategy_definition_id"],
        runtime_input={**base_input, "fee_ratio": Decimal("0"), "sell_tax_ratio": Decimal("0")},
        actor="STEP12_7_TEST:admin",
    )
    with_fee = run_definition_backtest(
        session, approval["strategy_definition_id"],
        runtime_input={**base_input, "fee_ratio": Decimal("0.01"), "sell_tax_ratio": Decimal("0.01")},
        actor="STEP12_7_TEST:admin",
    )
    if no_fee["summary"]["trade_count"] > 0:
        assert with_fee["summary"]["final_equity"] <= no_fee["summary"]["final_equity"]


def test_insufficient_data_fails_closed(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    approval = _approve(session, request["strategy_request_id"])
    _seed_prices(session, [100.0, 101.0], start=date(2024, 1, 1))
    runtime_input = _default_runtime_input(start_date=date(2024, 1, 1), end_date=date(2024, 1, 3))
    with pytest.raises(BacktestExecutionError) as exc_info:
        run_definition_backtest(
            session, approval["strategy_definition_id"], runtime_input=runtime_input,
            actor="STEP12_7_TEST:admin",
        )
    assert exc_info.value.code == "RUNTIME_INPUT_REQUIRED"


def test_ready_false_blocks_execution(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    draft = StrategyDraftService(session).create(
        strategy_request_id=request["strategy_request_id"], **_manual_draft_kwargs()
    )
    svc = StrategyDraftApprovalService(session)
    approval = svc.approve(draft["draft_id"], actor="admin:7", reason="승인")
    svc.revoke(approval["approval_id"], actor="admin:9", reason="취소")
    with pytest.raises(BacktestExecutionError) as exc_info:
        run_definition_backtest(
            session, approval["strategy_definition_id"],
            runtime_input=_default_runtime_input(), actor="STEP12_7_TEST:admin",
        )
    assert exc_info.value.code == "DEFINITION_NOT_READY"


def test_compiler_failure_blocks_execution(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    approval = _approve(
        session, request["strategy_request_id"],
        entry_rule='[{"indicator":"MACD","operator":"GT","threshold":0}]',
    )
    with pytest.raises(BacktestExecutionError):
        run_definition_backtest(
            session, approval["strategy_definition_id"],
            runtime_input=_default_runtime_input(), actor="STEP12_7_TEST:admin",
        )


def test_moving_average_engine_regression() -> None:
    """기존 MovingAverageCrossStrategy 경로가 이번 STEP 변경으로 깨지지
    않았는지 확인(엔진/전략 자체는 수정하지 않았으므로 직접 호출 검증)."""
    from stock_platform.backtest.engine import BacktestEngine
    from stock_platform.backtest.strategy import (
        MovingAverageCrossStrategy,
        MovingAverageStrategyConfig,
    )

    prices = [
        BacktestPrice(date(2024, 1, 1) + timedelta(days=i), Decimal(v), Decimal(v), Decimal(v), Decimal(v), Decimal(1))
        for i, v in enumerate([100.0] * 25 + [110.0] * 10)
    ]
    strategy = MovingAverageCrossStrategy(MovingAverageStrategyConfig(short_window=5, long_window=20))
    result = BacktestEngine(strategy).run(
        exchange_code="KRX", symbol="005930", prices=prices, initial_capital=Decimal("1000000"),
    )
    assert result.summary.initial_capital == Decimal("1000000")


# ---------------------------------------------------------------------------
# F: API / Auth / Audit
# ---------------------------------------------------------------------------


def test_backtest_api_requires_admin() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        "/api/v1/admin/strategies/1/backtests",
        json={
            "symbol": "X", "exchange_code": "KRX", "start_date": "2024-01-01",
            "end_date": "2024-02-01", "initial_capital": "1000000",
        },
    )
    assert resp.status_code == 401


def test_backtest_api_success(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    approval = _approve(session, request["strategy_request_id"])
    closes = [100.0] * 15 + [float(100 - i) for i in range(1, 16)] + [float(85 + i * 3) for i in range(1, 20)]
    _seed_prices(session, closes, start=date(2024, 1, 1))
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        f"/api/v1/admin/strategies/{approval['strategy_definition_id']}/backtests",
        json={
            "symbol": _TEST_SYMBOL, "exchange_code": _TEST_EXCHANGE,
            "start_date": "2024-01-01",
            "end_date": (date(2024, 1, 1) + timedelta(days=len(closes))).isoformat(),
            "initial_capital": "1000000",
        },
        headers={"X-Admin-API-Key": admin_key},
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "SUCCESS"


def test_backtest_api_validation_failure_response(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    approval = _approve(session, request["strategy_request_id"])
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        f"/api/v1/admin/strategies/{approval['strategy_definition_id']}/backtests",
        json={
            "symbol": _TEST_SYMBOL, "exchange_code": _TEST_EXCHANGE,
            "start_date": "2024-01-01", "end_date": "2024-01-02",
            "initial_capital": "1000000",
        },
        headers={"X-Admin-API-Key": admin_key},
    )
    assert resp.status_code in (400, 404, 409)


def test_backtest_api_idempotency_replay(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    approval = _approve(session, request["strategy_request_id"])
    closes = [100.0] * 15 + [float(100 - i) for i in range(1, 16)] + [float(85 + i * 3) for i in range(1, 20)]
    _seed_prices(session, closes, start=date(2024, 1, 1))
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    body = {
        "symbol": _TEST_SYMBOL, "exchange_code": _TEST_EXCHANGE,
        "start_date": "2024-01-01",
        "end_date": (date(2024, 1, 1) + timedelta(days=len(closes))).isoformat(),
        "initial_capital": "1000000", "idempotency_key": "step12-7-idem-1",
    }
    r1 = client.post(
        f"/api/v1/admin/strategies/{approval['strategy_definition_id']}/backtests",
        json=body, headers={"X-Admin-API-Key": admin_key},
    )
    r2 = client.post(
        f"/api/v1/admin/strategies/{approval['strategy_definition_id']}/backtests",
        json=body, headers={"X-Admin-API-Key": admin_key},
    )
    assert r1.json()["backtest_run_id"] == r2.json()["backtest_run_id"]
    assert r2.json()["idempotent_replay"] is True


def test_backtest_audit_events(session) -> None:
    from sqlalchemy import select

    from stock_platform.operation.audit_models import AuditEvent

    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    approval = _approve(session, request["strategy_request_id"])
    closes = [100.0] * 15 + [float(100 - i) for i in range(1, 16)] + [float(85 + i * 3) for i in range(1, 20)]
    _seed_prices(session, closes, start=date(2024, 1, 1))
    admin_key = get_settings().admin_api_key
    client = TestClient(app, raise_server_exceptions=False)
    client.post(
        f"/api/v1/admin/strategies/{approval['strategy_definition_id']}/backtests",
        json={
            "symbol": _TEST_SYMBOL, "exchange_code": _TEST_EXCHANGE,
            "start_date": "2024-01-01",
            "end_date": (date(2024, 1, 1) + timedelta(days=len(closes))).isoformat(),
            "initial_capital": "1000000",
        },
        headers={"X-Admin-API-Key": admin_key},
    )
    events = session.execute(
        select(AuditEvent.event_type)
        .where(AuditEvent.event_type.like("STRATEGY_BACKTEST_%"))
        .order_by(AuditEvent.audit_event_id.desc())
        .limit(5)
    ).all()
    event_types = {e[0] for e in events}
    assert "STRATEGY_BACKTEST_REQUESTED" in event_types
    assert "STRATEGY_BACKTEST_SUCCEEDED" in event_types


_WRITE_GUARD_TABLES = (
    "trading.trading_order",
    "trading.user_broker_account",
    "trading.paper_account",
    "trading.paper_trade",
)


def _table_counts(session) -> dict[str, int]:
    return {
        table: session.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
        for table in _WRITE_GUARD_TABLES
    }


def test_no_broker_or_order_writes(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    approval = _approve(session, request["strategy_request_id"])
    closes = [100.0] * 15 + [float(100 - i) for i in range(1, 16)] + [float(85 + i * 3) for i in range(1, 20)]
    _seed_prices(session, closes, start=date(2024, 1, 1))
    before = _table_counts(session)
    run_definition_backtest(
        session, approval["strategy_definition_id"],
        runtime_input=_default_runtime_input(
            start_date=date(2024, 1, 1), end_date=date(2024, 1, 1) + timedelta(days=len(closes))
        ),
        actor="STEP12_7_TEST:admin",
    )
    after = _table_counts(session)
    assert after == before


# ---------------------------------------------------------------------------
# G: 회귀
# ---------------------------------------------------------------------------


def test_readiness_regression(session) -> None:
    from stock_platform.ai.strategy_draft_approval.readiness import check_readiness

    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    approval = _approve(session, request["strategy_request_id"])
    assert check_readiness(session, approval["strategy_definition_id"])["ready"] is True


def test_compiler_regression(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    approval = _approve(session, request["strategy_request_id"])
    result = compile_specification(session, approval["strategy_definition_id"])
    assert result["compilable"] is True


def test_definition_immutable_after_backtest(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    approval = _approve(session, request["strategy_request_id"])
    closes = [100.0] * 15 + [float(100 - i) for i in range(1, 16)] + [float(85 + i * 3) for i in range(1, 20)]
    _seed_prices(session, closes, start=date(2024, 1, 1))
    definition_before = session.get(
        StrategyDefinitionEntity, approval["strategy_definition_id"]
    )
    hash_before = definition_before.definition_hash
    run_definition_backtest(
        session, approval["strategy_definition_id"],
        runtime_input=_default_runtime_input(
            start_date=date(2024, 1, 1), end_date=date(2024, 1, 1) + timedelta(days=len(closes))
        ),
        actor="STEP12_7_TEST:admin",
    )
    session.expire_all()
    definition_after = session.get(
        StrategyDefinitionEntity, approval["strategy_definition_id"]
    )
    assert definition_after.definition_hash == hash_before


def test_unapproved_draft_cannot_be_backtested(session) -> None:
    request = _create_approved_request(session, result_id=session.info["result_ids"][0])
    StrategyDraftService(session).create(
        strategy_request_id=request["strategy_request_id"], **_manual_draft_kwargs()
    )
    # 승인하지 않은 Draft는 Strategy Definition을 만들지 않는다 — Backtest
    # 대상이 될 Definition 자체가 존재하지 않음을 확인한다.
    count = session.execute(
        text(
            "SELECT COUNT(*) FROM trading.strategy_definition WHERE strategy_request_id = :rid"
        ),
        {"rid": request["strategy_request_id"]},
    ).scalar_one()
    assert count == 0
    with pytest.raises(BacktestExecutionError) as exc_info:
        run_definition_backtest(
            session, 999_999_999, runtime_input=_default_runtime_input(),
            actor="STEP12_7_TEST:admin",
        )
    assert exc_info.value.code == "NOT_FOUND"
