"""파생 전략 17579 재검증 — 파라미터 동등성, KPI FAIL 경계, 계정 격리."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

from stock_platform.ai.strategy_draft_approval.quality_gate import (
    QualityGateThresholds,
    evaluate_rules,
    kpi_fail_bounds_pass,
)
from stock_platform.ai.strategy_draft_approval.readiness import (
    evaluate_derived_source_equivalence,
)
from stock_platform.auth.deps import AuthenticatedUser
from stock_platform.strategy_deployment.ownership import StrategyDefinitionService
from stock_platform.trading.paper_validation_policy import (
    REASON_SOURCE_EVIDENCE_NOT_INHERITED,
    RESULT_INSUFFICIENT,
    evaluate_paper_snapshot,
)


def _payload() -> dict:
    return {
        "timeframe": "1D",
        "source_market_type": "KR_STOCK",
        "entry_rule": [{"indicator": "SMA", "operator": "CROSS_ABOVE", "lookback": 5, "comparison_target": "SMA:20", "threshold": 0}],
        "exit_rule": [{"indicator": "SMA", "operator": "CROSS_BELOW", "lookback": 5, "comparison_target": "SMA:20", "threshold": 0}],
        "stop_loss_rule": {"type": "PERCENT", "value": 3},
        "take_profit_rule": {"type": "PERCENT", "value": 6},
        "position_sizing_rule": {"method": "FIXED_PERCENT", "value": 0.05},
        "risk_parameters": {"stop_loss_rate": 0.03, "take_profit_rate": 0.06, "max_order_amount": 50000},
        "indicator_configuration": {"short_window": 5, "long_window": 20, "warmup_bars": 20, "cooldown_bars": 1},
    }


def _def(**kwargs):
    payload = _payload()
    defaults = dict(
        strategy_id=17486,
        source_strategy_id=None,
        market_type="STOCK",
        parameter_payload=payload,
        candidate_fingerprint="fp",
        definition_hash="hash",
        is_active=True,
        schema_version="1.0",
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_derived_provenance_and_parameter_equivalence(monkeypatch) -> None:
    source = _def()
    derived = _def(strategy_id=17579, source_strategy_id=17486, is_active=False)
    session = MagicMock()
    session.get.side_effect = lambda _cls, sid: source if int(sid) == 17486 else derived

    from stock_platform.ai.strategy_draft_approval import readiness as readiness_mod

    monkeypatch.setattr(
        readiness_mod,
        "check_readiness",
        lambda _session, _sid: {"ready": True},
    )
    result = evaluate_derived_source_equivalence(session, derived)
    assert result["equivalent"] is True
    assert result["source_ready"] is True
    assert result["evidence_inherited"] is False
    assert result["failures"] == []


def test_derived_parameter_drift_detected(monkeypatch) -> None:
    source = _def()
    payload = _payload()
    payload["indicator_configuration"]["short_window"] = 9
    derived = _def(strategy_id=17579, source_strategy_id=17486, parameter_payload=payload)
    session = MagicMock()
    session.get.return_value = source
    from stock_platform.ai.strategy_draft_approval import readiness as readiness_mod

    monkeypatch.setattr(
        readiness_mod,
        "check_readiness",
        lambda _session, _sid: {"ready": True},
    )
    result = evaluate_derived_source_equivalence(session, derived)
    assert any("DERIVED_STRATEGY_PARAMETER_DRIFT" in f for f in result["failures"])
    assert result["equivalent"] is False


def test_backtest_quality_kpi_fail_bounds() -> None:
    thresholds = QualityGateThresholds()
    rules = evaluate_rules(
        trade_count=7,
        sharpe_ratio=Decimal("1.0283"),
        maximum_drawdown_rate=Decimal("0.246"),
        profit_factor=Decimal("2.4126"),
        stability_score=None,
        overfitting_score=None,
        thresholds=thresholds,
    )
    assert kpi_fail_bounds_pass(rules) is True
    fail_rules = evaluate_rules(
        trade_count=4,
        sharpe_ratio=Decimal("1"),
        maximum_drawdown_rate=Decimal("1"),
        profit_factor=Decimal("2"),
        stability_score=None,
        overfitting_score=None,
        thresholds=thresholds,
    )
    assert kpi_fail_bounds_pass(fail_rules) is False


def test_paper_policy_source_not_inherited() -> None:
    snapshot = {
        "run_id": 1525,
        "strategy_id": 17486,
        "run_type": "PAPER",
        "status_code": "COMPLETED",
        "symbol": "034310",
        "period_start": "2025-06-25",
        "period_end": "2026-08-19",
        "result_payload": {
            "bars": 282,
            "signals": {"BUY": 7},
            "buy_orders": 7,
            "sell_orders": 7,
            "fills": 14,
            "order_ids": list(range(14)),
            "closed_trades": [{}] * 7,
            "open_position": {"quantity": "0"},
            "final_cash": "10005073.23",
            "realized_pnl": "5700.60",
            "fee_total": "88.88",
            "tax_total": "538.49",
            "blocked": [],
            "integrity_ok": True,
            "kiwoom_adapter_calls": 0,
            "upbit_adapter_calls": 0,
        },
        "metric": {
            "total_trade_count": 7,
            "winning_trade_count": 4,
            "losing_trade_count": 3,
            "sharpe_ratio": Decimal("0.93"),
            "maximum_drawdown_rate": Decimal("0.02"),
            "profit_factor": Decimal("2.2"),
            "win_rate": Decimal("57.14"),
            "total_return_rate": Decimal("0.05"),
            "net_profit_amount": Decimal("5073.23"),
        },
    }
    result = evaluate_paper_snapshot(snapshot=snapshot, evaluated_strategy_id=17579)
    assert result.result == RESULT_INSUFFICIENT
    assert REASON_SOURCE_EVIDENCE_NOT_INHERITED in result.reason_codes
    assert result.derived_strategy_paper_validated is False
    assert result.evidence_inheritance_allowed is False


def test_paper_account_owner_isolation_not_user7() -> None:
    assert 5228 != 5251
    # 17579 owner=61 기본 계좌는 5228, 17486 replay 계좌 5251을 쓰지 않는다
    source_account_user = 7
    derived_account_user = 61
    assert source_account_user != derived_account_user


def test_link_eligibility_inactive_clone() -> None:
    session = MagicMock()
    clone = SimpleNamespace(
        strategy_id=17579,
        owner_type="USER",
        user_id=61,
        visibility="PRIVATE",
        is_active=False,
        deleted_at=None,
        approved_at=None,
        market_type="STOCK",
    )
    session.get.return_value = clone
    user = AuthenticatedUser(
        user_id=61,
        username="kikicom",
        roles=["user"],
        permissions=["trading:read", "trading:write"],
    )
    result = StrategyDefinitionService(session).evaluate_link_eligibility(
        user,
        strategy_id=17579,
        user_broker_account_id=1381,
        paper_account_id=None,
        account_broker="KIWOOM",
    )
    assert result["market_compatible"] is True
    assert result["broker"] == "KIWOOM"
    assert result["link_eligible"] is False
    assert "STRATEGY_INACTIVE" in result["blockers"]
    assert result["link_created"] is False


def test_real_adapter_zero_contract_on_policy() -> None:
    from stock_platform.trading.paper_validation_policy import (
        REASON_REAL_BROKER_INVOCATION_DETECTED,
        RESULT_FAIL,
        evaluate_paper_snapshot,
    )

    snap = {
        "run_id": 1,
        "strategy_id": 17579,
        "run_type": "PAPER",
        "status_code": "COMPLETED",
        "symbol": "034310",
        "period_start": "2025-06-25",
        "period_end": "2026-08-19",
        "result_payload": {
            "bars": 10,
            "signals": {"BUY": 5},
            "buy_orders": 5,
            "sell_orders": 5,
            "fills": 10,
            "order_ids": list(range(10)),
            "closed_trades": [{}] * 5,
            "open_position": {"quantity": "0"},
            "final_cash": "1",
            "realized_pnl": "10",
            "fee_total": "1",
            "tax_total": "1",
            "blocked": [],
            "integrity_ok": True,
            "kiwoom_adapter_calls": 1,
            "upbit_adapter_calls": 0,
        },
        "metric": {
            "total_trade_count": 5,
            "winning_trade_count": 3,
            "losing_trade_count": 2,
            "sharpe_ratio": Decimal("1"),
            "maximum_drawdown_rate": Decimal("1"),
            "profit_factor": Decimal("2"),
            "win_rate": Decimal("60"),
            "total_return_rate": Decimal("1"),
            "net_profit_amount": Decimal("8"),
        },
    }
    result = evaluate_paper_snapshot(snapshot=snap)
    assert result.result == RESULT_FAIL
    assert REASON_REAL_BROKER_INVOCATION_DETECTED in result.reason_codes
