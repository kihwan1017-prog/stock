"""Paper validation acceptance policy — unit tests. DB persist 없음."""

from __future__ import annotations

from decimal import Decimal

from stock_platform.ai.strategy_draft_approval.quality_gate import (
    QualityGateThresholds,
    evaluate_rules,
)
from stock_platform.trading.paper_validation_policy import (
    PAPER_VALIDATION_POLICY_VERSION,
    PaperValidationPolicy,
    REASON_DUPLICATE_ORDER_IDS,
    REASON_FEE_TAX_RECONCILIATION_FAILED,
    REASON_INSUFFICIENT_CLOSED_TRADES,
    REASON_INSUFFICIENT_EVIDENCE,
    REASON_MDD_ABOVE_THRESHOLD,
    REASON_MISSING_METRIC,
    REASON_NEGATIVE_CASH,
    REASON_ORDER_FILL_MISMATCH,
    REASON_OVERSELL_DETECTED,
    REASON_PROFIT_FACTOR_BELOW_THRESHOLD,
    REASON_REAL_BROKER_INVOCATION_DETECTED,
    REASON_RUN_NOT_COMPLETED,
    REASON_SHARPE_BELOW_THRESHOLD,
    REASON_SOURCE_EVIDENCE_NOT_INHERITED,
    RESULT_FAIL,
    RESULT_INSUFFICIENT,
    RESULT_PASS,
    evaluate_paper_snapshot,
)


def _snapshot_1525() -> dict:
    return {
        "run_id": 1525,
        "strategy_id": 17486,
        "run_type": "PAPER",
        "status_code": "COMPLETED",
        "symbol": "034310",
        "period_start": "2025-06-25",
        "period_end": "2026-08-19",
        "result_payload": {
            "bars": 282,
            "signals": {"BUY": 7, "SELL": 0, "STOP_LOSS": 3, "TAKE_PROFIT": 4},
            "buy_orders": 7,
            "sell_orders": 7,
            "fills": 14,
            "order_ids": list(range(1705, 1719)),
            "closed_trades": [{}] * 7,
            "open_position": {"quantity": "0", "average_entry_price": "0"},
            "final_cash": "10005073.23",
            "realized_pnl": "5700.60",
            "fee_total": "88.88",
            "tax_total": "538.49",
            "integrity_ok": True,
            "blocked": [],
            "kiwoom_adapter_calls": 0,
            "upbit_adapter_calls": 0,
        },
        "metric": {
            "total_trade_count": 7,
            "winning_trade_count": 4,
            "losing_trade_count": 3,
            "sharpe_ratio": Decimal("0.93492522"),
            "maximum_drawdown_rate": Decimal("0.02109324"),
            "profit_factor": Decimal("2.21283454"),
            "win_rate": Decimal("57.14285714"),
            "total_return_rate": Decimal("0.05073230"),
            "net_profit_amount": Decimal("5073.23"),
        },
    }


def test_a_sufficient_evidence_pass() -> None:
    result = evaluate_paper_snapshot(snapshot=_snapshot_1525())
    assert result.result == RESULT_PASS
    assert result.reason_codes == []
    assert result.layers["evidence_sufficiency"] == "PASS"
    assert result.layers["execution_integrity"] == "PASS"
    assert result.layers["performance_quality"] == "PASS"


def test_b_insufficient_trades() -> None:
    snap = _snapshot_1525()
    snap["metric"]["total_trade_count"] = 4
    snap["metric"]["winning_trade_count"] = 2
    snap["metric"]["losing_trade_count"] = 2
    snap["result_payload"]["closed_trades"] = [{}] * 4
    result = evaluate_paper_snapshot(snapshot=snap)
    assert result.result == RESULT_FAIL
    assert REASON_INSUFFICIENT_CLOSED_TRADES in result.reason_codes


def test_c_incomplete_run() -> None:
    snap = _snapshot_1525()
    snap["status_code"] = "RUNNING"
    result = evaluate_paper_snapshot(snapshot=snap)
    assert result.result == RESULT_INSUFFICIENT
    assert REASON_RUN_NOT_COMPLETED in result.reason_codes


def test_d_fill_mismatch() -> None:
    snap = _snapshot_1525()
    snap["result_payload"]["fills"] = 13
    result = evaluate_paper_snapshot(snapshot=snap)
    assert result.result == RESULT_FAIL
    assert REASON_ORDER_FILL_MISMATCH in result.reason_codes


def test_e_oversell() -> None:
    snap = _snapshot_1525()
    snap["result_payload"]["open_position"]["quantity"] = "-1"
    result = evaluate_paper_snapshot(snapshot=snap)
    assert result.result == RESULT_FAIL
    assert REASON_OVERSELL_DETECTED in result.reason_codes


def test_f_negative_cash() -> None:
    snap = _snapshot_1525()
    snap["result_payload"]["final_cash"] = "-1"
    result = evaluate_paper_snapshot(snapshot=snap)
    assert result.result == RESULT_FAIL
    assert REASON_NEGATIVE_CASH in result.reason_codes


def test_g_real_broker_invocation() -> None:
    snap = _snapshot_1525()
    snap["result_payload"]["kiwoom_adapter_calls"] = 1
    result = evaluate_paper_snapshot(snapshot=snap)
    assert result.result == RESULT_FAIL
    assert REASON_REAL_BROKER_INVOCATION_DETECTED in result.reason_codes


def test_h_sharpe_threshold() -> None:
    snap = _snapshot_1525()
    snap["metric"]["sharpe_ratio"] = Decimal("-0.01")
    result = evaluate_paper_snapshot(snapshot=snap)
    assert result.result == RESULT_FAIL
    assert REASON_SHARPE_BELOW_THRESHOLD in result.reason_codes


def test_i_mdd_threshold() -> None:
    snap = _snapshot_1525()
    snap["metric"]["maximum_drawdown_rate"] = Decimal("41")
    result = evaluate_paper_snapshot(snapshot=snap)
    assert result.result == RESULT_FAIL
    assert REASON_MDD_ABOVE_THRESHOLD in result.reason_codes


def test_j_pf_threshold() -> None:
    snap = _snapshot_1525()
    snap["metric"]["profit_factor"] = Decimal("0.99")
    result = evaluate_paper_snapshot(snapshot=snap)
    assert result.result == RESULT_FAIL
    assert REASON_PROFIT_FACTOR_BELOW_THRESHOLD in result.reason_codes


def test_k_missing_metric() -> None:
    snap = _snapshot_1525()
    snap["metric"]["sharpe_ratio"] = None
    result = evaluate_paper_snapshot(snapshot=snap)
    assert result.result == RESULT_INSUFFICIENT
    assert REASON_MISSING_METRIC in result.reason_codes


def test_l_deterministic_reason_codes() -> None:
    a = evaluate_paper_snapshot(snapshot=_snapshot_1525())
    b = evaluate_paper_snapshot(snapshot=_snapshot_1525())
    assert a.result == b.result
    assert a.reason_codes == b.reason_codes
    assert a.policy_version == PAPER_VALIDATION_POLICY_VERSION


def test_m_source_vs_derived_isolation() -> None:
    result = evaluate_paper_snapshot(
        snapshot=_snapshot_1525(),
        evaluated_strategy_id=17579,
    )
    assert result.result == RESULT_INSUFFICIENT
    assert REASON_SOURCE_EVIDENCE_NOT_INHERITED in result.reason_codes
    assert result.derived_strategy_paper_validated is False
    assert result.evidence_inheritance_allowed is False


def test_n_1525_fixture_evaluation() -> None:
    result = evaluate_paper_snapshot(snapshot=_snapshot_1525())
    assert result.source_strategy_paper_validated is True
    policy = PaperValidationPolicy()
    assert policy.min_closed_trades == 5
    assert policy.win_rate_rule == "REPORT_ONLY"
    assert policy.return_rule == "REPORT_ONLY"


def test_o_existing_backtest_quality_fail_thresholds() -> None:
    thresholds = QualityGateThresholds()
    assert thresholds.min_trade_count_fail == 5
    assert thresholds.min_sharpe_ratio_fail == Decimal("0")
    assert thresholds.max_drawdown_rate_fail == Decimal("40")
    assert thresholds.min_profit_factor_fail == Decimal("1.0")
    fail_trade = [
        r
        for r in evaluate_rules(
            trade_count=4,
            sharpe_ratio=Decimal("1"),
            maximum_drawdown_rate=Decimal("1"),
            profit_factor=Decimal("2"),
            stability_score=Decimal("1"),
            overfitting_score=Decimal("0"),
            thresholds=thresholds,
        )
        if r.rule_name == "MINIMUM_TRADE_COUNT"
    ][0]
    assert fail_trade.status == "FAIL"
    fail_sharpe = [
        r
        for r in evaluate_rules(
            trade_count=10,
            sharpe_ratio=Decimal("-0.01"),
            maximum_drawdown_rate=Decimal("1"),
            profit_factor=Decimal("2"),
            stability_score=Decimal("1"),
            overfitting_score=Decimal("0"),
            thresholds=thresholds,
        )
        if r.rule_name == "MINIMUM_SHARPE_RATIO"
    ][0]
    assert fail_sharpe.status == "FAIL"
    fail_mdd = [
        r
        for r in evaluate_rules(
            trade_count=10,
            sharpe_ratio=Decimal("1"),
            maximum_drawdown_rate=Decimal("41"),
            profit_factor=Decimal("2"),
            stability_score=Decimal("1"),
            overfitting_score=Decimal("0"),
            thresholds=thresholds,
        )
        if r.rule_name == "MAXIMUM_DRAWDOWN"
    ][0]
    assert fail_mdd.status == "FAIL"
    fail_pf = [
        r
        for r in evaluate_rules(
            trade_count=10,
            sharpe_ratio=Decimal("1"),
            maximum_drawdown_rate=Decimal("1"),
            profit_factor=Decimal("0.99"),
            stability_score=Decimal("1"),
            overfitting_score=Decimal("0"),
            thresholds=thresholds,
        )
        if r.rule_name == "MINIMUM_PROFIT_FACTOR"
    ][0]
    assert fail_pf.status == "FAIL"
    boundary = evaluate_rules(
        trade_count=5,
        sharpe_ratio=Decimal("0"),
        maximum_drawdown_rate=Decimal("40"),
        profit_factor=Decimal("1.0"),
        stability_score=Decimal("1"),
        overfitting_score=Decimal("0"),
        thresholds=thresholds,
    )
    kpi = {
        r.rule_name: r.status
        for r in boundary
        if r.rule_name
        in {
            "MINIMUM_TRADE_COUNT",
            "MINIMUM_SHARPE_RATIO",
            "MAXIMUM_DRAWDOWN",
            "MINIMUM_PROFIT_FACTOR",
        }
    }
    assert kpi["MINIMUM_TRADE_COUNT"] != "FAIL"
    assert kpi["MINIMUM_SHARPE_RATIO"] != "FAIL"
    assert kpi["MAXIMUM_DRAWDOWN"] != "FAIL"
    assert kpi["MINIMUM_PROFIT_FACTOR"] != "FAIL"


def test_duplicate_orders_and_fee_tax() -> None:
    snap = _snapshot_1525()
    snap["result_payload"]["order_ids"] = [1, 1] + list(range(1707, 1719))
    result = evaluate_paper_snapshot(snapshot=snap)
    assert REASON_DUPLICATE_ORDER_IDS in result.reason_codes
    snap2 = _snapshot_1525()
    snap2["result_payload"]["fee_total"] = "0"
    result2 = evaluate_paper_snapshot(snapshot=snap2)
    assert result2.result == RESULT_FAIL
    assert REASON_FEE_TAX_RECONCILIATION_FAILED in result2.reason_codes
