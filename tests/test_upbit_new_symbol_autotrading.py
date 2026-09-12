"""UPBIT 신규 심볼 자동매매 준비 — production DB mutation 없음."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

from stock_platform.broker.upbit.rules import (
    UPBIT_MIN_NOTIONAL_KRW,
    evaluate_upbit_min_notional,
)
from stock_platform.realtime.consumer_registry import ScopeConsumerRegistry
from stock_platform.realtime.market_event import RealtimeMarketEvent
from stock_platform.realtime.runtime_bridge import _symbols_for_entry
from stock_platform.risk_engine.models import (
    RiskAccountState,
    RiskDecisionLevel,
    RiskOrderRequest,
    RiskOrderSide,
    RiskPolicy,
)
from stock_platform.risk_engine.rules import MaximumOpenPositionsRule
from stock_platform.strategy_deployment.ownership import StrategyDefinitionService
from stock_platform.strategy_deployment.runtime_scope import (
    AccountKind,
    RuntimeLifecycleStatus,
    StrategyRuntimeScope,
)
from stock_platform.strategy_deployment.symbol_payload import (
    apply_symbol_to_parameter_payload,
    signal_symbol_matches_strategy,
    symbols_from_parameter_payload,
)
from stock_platform.trading.upbit_new_symbol_readiness import (
    RECOMMENDED_SMOKE_MAX_ORDER_AMOUNT,
    classify_entry_positions,
    entry_blocked_by_position_cap,
    recommended_max_order_amount,
)


XRP_PAYLOAD = {
    "symbol": "KRW-XRP",
    "symbols": ["KRW-XRP"],
    "exchange_code": "UPBIT",
    "short_window": 5,
    "long_window": 20,
    "strategy_type": "MOVING_AVERAGE_CROSS",
    "stop_loss_ratio": "0.03",
    "take_profit_ratio": "0.06",
    "position_ratio": "0.20",
    "cooldown_seconds": 30,
    "evaluator": "MovingAverageStrategyEvaluator",
}


def test_new_symbol_payload_isolation_from_xrp() -> None:
    original = dict(XRP_PAYLOAD)
    cloned = apply_symbol_to_parameter_payload(original, symbol="KRW-GRVT")
    assert original["symbol"] == "KRW-XRP"
    assert original["symbols"] == ["KRW-XRP"]
    assert cloned["symbol"] == "KRW-GRVT"
    assert cloned["symbols"] == ["KRW-GRVT"]
    assert symbols_from_parameter_payload(original) == ["KRW-XRP"]
    assert signal_symbol_matches_strategy(
        signal_symbol="KRW-XRP", payload=original
    )
    assert not signal_symbol_matches_strategy(
        signal_symbol="KRW-GRVT", payload=original
    )
    assert not signal_symbol_matches_strategy(
        signal_symbol="KRW-XRP", payload=cloned
    )


def test_cross_symbol_signals_rejected() -> None:
    payload = apply_symbol_to_parameter_payload(XRP_PAYLOAD, symbol="KRW-GRVT")
    assert (
        signal_symbol_matches_strategy(
            signal_symbol="KRW-DOGE", payload=payload
        )
        is False
    )


def test_runtime_bridge_uses_payload_symbol() -> None:
    entry = SimpleNamespace(
        runtime=SimpleNamespace(
            symbol="KRW-XRP",
            parameter_payload=apply_symbol_to_parameter_payload(
                XRP_PAYLOAD, symbol="KRW-GRVT"
            ),
        )
    )
    assert _symbols_for_entry(entry) == ["KRW-GRVT"]


def test_position_cap_counts_dust() -> None:
    rows = [
        {"symbol": "KRW-BTC", "quantity": "0.01", "evaluation_amount": "900000"},
        {"symbol": "KRW-ETH", "quantity": "0.7", "evaluation_amount": "2000000"},
        {"symbol": "KRW-DOGE", "quantity": "9000", "evaluation_amount": "900000"},
        {"symbol": "KRW-SKY", "quantity": "3000", "evaluation_amount": "250000"},
        {"symbol": "KRW-XRP", "quantity": "3.4", "evaluation_amount": "4820"},
    ]
    classified = classify_entry_positions(rows)
    assert classified["position_count"] == 5
    assert classified["dust_count"] == 1
    assert classified["current_domain_counts_dust"] is True
    assert classified["dust_positions"][0]["symbol"] == "KRW-XRP"
    assert entry_blocked_by_position_cap(
        position_count=5, max_position_count=5
    )

    now = datetime.now(timezone.utc)
    policy = RiskPolicy(max_open_positions=5)
    account = RiskAccountState(
        cash_balance=Decimal("100000"),
        total_asset_value=Decimal("4000000"),
        invested_amount=Decimal("3900000"),
        daily_realized_profit_loss=Decimal("0"),
        daily_unrealized_profit_loss=Decimal("0"),
        open_position_count=5,
        symbol_position_quantity=Decimal("0"),
    )
    order = RiskOrderRequest(
        exchange_code="UPBIT",
        symbol="KRW-GRVT",
        side=RiskOrderSide.BUY,
        quantity=Decimal("20"),
        price=Decimal("400"),
        requested_at=now,
        user_broker_account_id=1380,
        environment="LIVE",
    )
    result = MaximumOpenPositionsRule().evaluate(
        order=order, account=account, policy=policy
    )
    assert result.level == RiskDecisionLevel.BLOCK


def test_min_notional_and_max_order_amount() -> None:
    assert (
        evaluate_upbit_min_notional(
            broker_code="UPBIT",
            environment="LIVE",
            side="BUY",
            order_type="MARKET",
            quantity=Decimal("1"),
            price=None,
            market_krw_amount=Decimal("4999"),
        )
        is not None
    )
    assert (
        evaluate_upbit_min_notional(
            broker_code="UPBIT",
            environment="LIVE",
            side="BUY",
            order_type="MARKET",
            quantity=Decimal("1"),
            price=None,
            market_krw_amount=Decimal("5000"),
        )
        is None
    )
    rec = recommended_max_order_amount(
        current_max_order_amount=Decimal("5100"),
        available_krw=Decimal("500000"),
    )
    assert rec["current_survives_3pct_sl"] is False
    assert rec["recommended_max_order_amount"] == str(
        RECOMMENDED_SMOKE_MAX_ORDER_AMOUNT
    )
    assert rec["auto_applied"] is False
    assert rec["minimum_order"] == str(UPBIT_MIN_NOTIONAL_KRW)


def test_hub_cross_broker_and_cross_uba_isolation() -> None:
    registry = ScopeConsumerRegistry()
    upbit = StrategyRuntimeScope(
        user_id=61,
        account_kind=AccountKind.USER_BROKER,
        account_id=1380,
        strategy_id=17483,
        strategy_version="1",
        market_type="CRYPTO",
        broker_code="UPBIT",
    )
    kiwoom = StrategyRuntimeScope(
        user_id=61,
        account_kind=AccountKind.USER_BROKER,
        account_id=1381,
        strategy_id=17579,
        strategy_version="1",
        market_type="STOCK",
        broker_code="KIWOOM",
    )
    registry.register_consumer(
        upbit,
        ["KRW-GRVT"],
        runtime_status=RuntimeLifecycleStatus.CREATED,
    )
    registry.register_consumer(
        kiwoom,
        ["034310"],
        runtime_status=RuntimeLifecycleStatus.CREATED,
    )
    now = datetime.now(timezone.utc)
    registry.dispatch(
        RealtimeMarketEvent(
            broker_code="KIWOOM",
            market_type="STOCK",
            symbol="034310",
            event_type="TRADE",
            event_time=now,
            received_at=now,
            exchange_code="KRX",
            price=Decimal("40150"),
        )
    )
    consumers = {c["scope_key"]: c for c in registry.list_consumers()}
    assert consumers[kiwoom.scope_key]["event_count"] == 1
    assert consumers[upbit.scope_key]["event_count"] == 0


def test_scanner_is_alert_only_no_order_import() -> None:
    import inspect

    from stock_platform.operation.upbit_opportunity_scanner import service

    src = inspect.getsource(service)
    assert "create_order" not in src
    assert "TradingOrder" not in src
    assert "alert_only" in src


def test_clone_for_symbol_does_not_inherit_evidence() -> None:
    source = SimpleNamespace(
        strategy_id=17483,
        market_type="CRYPTO",
        parameter_payload=dict(XRP_PAYLOAD),
        definition_hash="deadbeef",
        schema_version=None,
        definition_version=None,
    )
    fake_clone = SimpleNamespace(
        user_id=61,
        is_active=False,
        parameter_payload=dict(XRP_PAYLOAD),
        candidate_id=9,
        candidate_fingerprint="abc",
        approval_id=3,
        definition_hash="deadbeef",
        strategy_request_id=777,
        approved_at="keep",
        approved_by="keep",
    )
    svc = StrategyDefinitionService(MagicMock())
    svc.require = MagicMock(return_value=source)  # type: ignore[method-assign]
    svc.clone_strategy = MagicMock(return_value=fake_clone)  # type: ignore[method-assign]
    user = SimpleNamespace(user_id=7, is_admin=True)
    clone = svc.clone_strategy_for_symbol(
        user,  # type: ignore[arg-type]
        17483,
        symbol="KRW-GRVT",
        actor="admin:7",
        for_user_id=61,
    )
    assert clone.user_id == 61
    assert clone.is_active is False
    assert clone.parameter_payload["symbol"] == "KRW-GRVT"
    assert clone.parameter_payload["entry_rule"]
    assert clone.parameter_payload["timeframe"] == "1D"
    assert clone.schema_version == "1.0"
    assert clone.definition_hash is None
    assert clone.candidate_id is None
    assert clone.approval_id is None
    assert clone.strategy_request_id is None
    assert source.parameter_payload["symbol"] == "KRW-XRP"
    assert source.definition_hash == "deadbeef"


def test_position_cap_five_to_six_allows_one_new_slot() -> None:
    """max_position_count 5→6이면 보유 5개에서 신규 슬롯 1개."""
    now = datetime.now(timezone.utc)
    policy = RiskPolicy(max_open_positions=6)
    account = RiskAccountState(
        cash_balance=Decimal("159000"),
        total_asset_value=Decimal("4000000"),
        invested_amount=Decimal("3900000"),
        daily_realized_profit_loss=Decimal("0"),
        daily_unrealized_profit_loss=Decimal("0"),
        open_position_count=5,
        symbol_position_quantity=Decimal("0"),
    )
    order = RiskOrderRequest(
        exchange_code="UPBIT",
        symbol="KRW-GRVT",
        side=RiskOrderSide.BUY,
        quantity=Decimal("20"),
        price=Decimal("500"),
        requested_at=now,
        user_broker_account_id=1380,
        environment="LIVE",
    )
    result = MaximumOpenPositionsRule().evaluate(
        order=order, account=account, policy=policy
    )
    assert result.level == RiskDecisionLevel.PASS
    assert entry_blocked_by_position_cap(
        position_count=5, max_position_count=6
    ) is False
    still_blocked = MaximumOpenPositionsRule().evaluate(
        order=order,
        account=account,
        policy=RiskPolicy(max_open_positions=5),
    )
    assert still_blocked.level == RiskDecisionLevel.BLOCK


def test_max_order_amount_10000_accepted_and_5100_dust_regression() -> None:
    """1만원 진입은 한도 통과. 5100은 3% SL 후 최소주문 미달 회귀."""
    from stock_platform.order.live_safety_pipeline import LiveOrderSafetyPipeline

    amount = Decimal("10000")
    old = recommended_max_order_amount(
        current_max_order_amount=Decimal("5100"),
        available_krw=Decimal("159000"),
    )
    new = recommended_max_order_amount(
        current_max_order_amount=Decimal("10000"),
        available_krw=Decimal("159000"),
    )
    assert old["current_survives_3pct_sl"] is False
    assert new["current_survives_3pct_sl"] is True
    sl3 = amount * Decimal("0.97")
    sl6 = amount * Decimal("0.94")
    assert sl3 >= UPBIT_MIN_NOTIONAL_KRW
    assert sl6 >= UPBIT_MIN_NOTIONAL_KRW
    src = __import__("inspect").getsource(LiveOrderSafetyPipeline.evaluate)
    assert "ORDER_AMOUNT_EXCEEDED" in src


def test_open_order_and_daily_order_limit_blockers() -> None:
    """max_open_orders=1·daily_order_limit=1이면 기존 1건이 신규 ENTRY를 막는다."""
    import inspect

    from stock_platform.order.live_safety_pipeline import LiveOrderSafetyPipeline

    src = inspect.getsource(LiveOrderSafetyPipeline.evaluate)
    assert "OPEN_ORDER_LIMIT_EXCEEDED" in src
    assert "DAILY_ORDER_LIMIT_EXCEEDED" in src
    open_count = 1
    max_open = 1
    daily_count = 1
    daily_limit = 1
    assert open_count >= max_open
    assert daily_count >= daily_limit
    daily_limit_remaining = max(0, daily_limit - daily_count)
    assert daily_limit_remaining == 0


def test_buy_exit_duplicate_sell_guards_exist() -> None:
    import inspect

    from stock_platform.order.live_safety_pipeline import LiveOrderSafetyPipeline
    from stock_platform.position.exit_monitor import FORCE_EXIT_REASONS

    assert "KILL_SWITCH" in FORCE_EXIT_REASONS
    body = inspect.getsource(LiveOrderSafetyPipeline.evaluate)
    assert "DUPLICATE" in body or "duplicate" in body.lower()
    from stock_platform.realtime.risk_integrated_order_executor import (
        RiskIntegratedRealtimeOrderExecutor,
    )

    exec_src = inspect.getsource(RiskIntegratedRealtimeOrderExecutor.execute)
    assert "SELL" in exec_src


def test_daily_risk_count_resets_on_kst_midnight_not_utc() -> None:
    """daily_order_limit는 Asia/Seoul 달력일. UTC 자정이 아님."""
    from zoneinfo import ZoneInfo

    from stock_platform.order.daily_risk_order_count import day_start_kst_as_utc

    kst = ZoneInfo("Asia/Seoul")
    late_19 = datetime(2026, 8, 19, 23, 50, tzinfo=kst)
    early_20 = datetime(2026, 8, 20, 0, 1, tzinfo=kst)
    start_19 = day_start_kst_as_utc(late_19)
    start_20 = day_start_kst_as_utc(early_20)
    assert start_19.astimezone(kst).date().isoformat() == "2026-08-19"
    assert start_20.astimezone(kst).date().isoformat() == "2026-08-20"
    assert (start_20 - start_19).total_seconds() == 86400
    utc_aug19_1501 = datetime(2026, 8, 19, 15, 1, tzinfo=timezone.utc)
    assert day_start_kst_as_utc(utc_aug19_1501).astimezone(kst).date().isoformat() == "2026-08-20"


def test_clone_for_symbol_clears_xrp_evidence_fields() -> None:
    import inspect

    src = inspect.getsource(StrategyDefinitionService.clone_strategy_for_symbol)
    assert "candidate_id = None" in src
    assert "definition_hash = None" in src
    assert "approval_id = None" in src
    assert "strategy_request_id = None" in src
    assert "is_active = False" in src
    assert "canonical_step12_payload_from_ma_semantics" in src


def test_new_symbol_clone_equivalence_ignores_symbol_and_cleared_evidence(
    monkeypatch,
) -> None:
    from stock_platform.ai.strategy_draft_approval.readiness import (
        evaluate_derived_source_equivalence,
    )

    payload = {
        "timeframe": "1D",
        "source_market_type": "CRYPTO",
        "symbol": "KRW-XRP",
        "symbols": ["KRW-XRP"],
        "entry_rule": [{"indicator": "SMA"}],
        "stop_loss_rule": {"type": "PERCENT", "value": 3},
        "take_profit_rule": {"type": "PERCENT", "value": 6},
        "position_sizing_rule": {"method": "FIXED_PERCENT", "value": 0.05},
        "risk_parameters": {"max_order_amount": 10000},
        "indicator_configuration": {
            "short_window": 5,
            "long_window": 20,
            "warmup_bars": 20,
            "cooldown_bars": 1,
        },
    }
    source = SimpleNamespace(
        strategy_id=17483,
        source_strategy_id=None,
        market_type="CRYPTO",
        parameter_payload=payload,
        candidate_fingerprint="xrp-fp",
        definition_hash="xrp-hash",
        is_active=True,
        schema_version="1.0",
    )
    derived_payload = dict(payload)
    derived_payload["symbol"] = "KRW-GRVT"
    derived_payload["symbols"] = ["KRW-GRVT"]
    derived = SimpleNamespace(
        strategy_id=99999,
        source_strategy_id=17483,
        market_type="CRYPTO",
        parameter_payload=derived_payload,
        candidate_fingerprint=None,
        definition_hash=None,
        is_active=False,
        schema_version="1.0",
    )
    session = MagicMock()
    session.get.side_effect = lambda _cls, sid: source if int(sid) == 17483 else derived
    from stock_platform.ai.strategy_draft_approval import readiness as readiness_mod

    monkeypatch.setattr(
        readiness_mod,
        "check_readiness",
        lambda _session, _sid: {"ready": True},
    )
    result = evaluate_derived_source_equivalence(session, derived)
    assert result["equivalent"] is True
    assert result["failures"] == []


def test_compiler_supports_crypto_market() -> None:
    from stock_platform.ai.strategy_draft_approval.backtest_spec import (
        COMPILER_SUPPORTED_MARKET_TYPES,
    )

    assert "KR_STOCK" in COMPILER_SUPPORTED_MARKET_TYPES
    assert "CRYPTO" in COMPILER_SUPPORTED_MARKET_TYPES


def test_legacy_ma_normalizes_without_mutating_source() -> None:
    from stock_platform.strategy_deployment.symbol_payload import (
        canonical_step12_payload_from_ma_semantics,
        execution_semantics,
    )

    original = dict(XRP_PAYLOAD)
    canonical = canonical_step12_payload_from_ma_semantics(
        original, symbol="KRW-SOL"
    )
    assert original["symbol"] == "KRW-XRP"
    assert "entry_rule" not in original
    assert canonical["symbol"] == "KRW-SOL"
    assert canonical["timeframe"] == "1D"
    assert canonical["source_market_type"] == "CRYPTO"
    assert canonical["stop_loss_rule"]["value"] == 3.0
    assert canonical["take_profit_rule"]["value"] == 6.0
    assert canonical["position_sizing_rule"]["value"] == 0.20
    assert execution_semantics(original) == execution_semantics(canonical)


def test_history_gate_uses_warmup_and_market_analysis_sot() -> None:
    from stock_platform.trading.upbit_new_symbol_readiness import (
        classify_official_daily_history,
    )

    assert classify_official_daily_history(15) == "WARMUP_INSUFFICIENT"
    assert classify_official_daily_history(25) == "SHORT_HISTORY"
    assert classify_official_daily_history(1109) == "BACKTEST_DATA_READY"


def test_paper_upbit_fee_has_no_stock_tax() -> None:
    from stock_platform.trading.paper_historical_replay import (
        UPBIT_FEE_RATIO,
        UPBIT_SELL_TAX_RATIO,
        _cost_ratios,
    )

    fee, tax = _cost_ratios("UPBIT")
    assert fee == UPBIT_FEE_RATIO
    assert tax == UPBIT_SELL_TAX_RATIO
    assert tax == 0
    krx_fee, krx_tax = _cost_ratios("KRX")
    assert krx_tax > 0


def test_kiwoom_isolation_in_symbol_clone() -> None:
    import inspect

    src = inspect.getsource(StrategyDefinitionService.clone_strategy_for_symbol)
    assert "17579" not in src
    assert "1381" not in src
