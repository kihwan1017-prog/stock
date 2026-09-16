"""UPBIT EXIT risk fail-safe — ENTRY 제한이 risk-reducing SELL을 막지 않게.

fixture/mock only. 실 UPBIT/KIWOOM API · LIVE 주문 금지.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from stock_platform.order.live_safety_pipeline import LiveOrderSafetyPipeline
from stock_platform.order.outbox_dispatch_safety import (
    REASON_KILL_SWITCH_ACTIVE,
    OutboxDispatchSafetyError,
    assert_live_outbox_dispatch_safety,
)
from stock_platform.risk_engine.exit_risk import (
    REASON_INVALID_ORDER_QUANTITY,
    REASON_NO_POSITION_TO_SELL,
    REASON_SELL_QUANTITY,
    ExitClassification,
    classify_risk_reducing_exit,
)
from stock_platform.risk_engine.models import (
    RiskAccountState,
    RiskDecisionLevel,
    RiskOrderRequest,
    RiskOrderSide,
    RiskPolicy,
)
from stock_platform.risk_engine.order_guard import DatabaseBackedRiskOrderGuard
from stock_platform.risk_engine.resolved_policy import ResolvedRiskPolicy
from stock_platform.risk_engine.rules import (
    MaximumOrderAmountRule,
    SellQuantityRule,
)
from stock_platform.risk_engine.runtime import realtime_risk_engine


ZERO = Decimal("0")
UBA1380 = 1380


def _verified_exit(
    *,
    held: str = "100",
    pending: str = "0",
    qty: str = "10",
) -> ExitClassification:
    held_q = Decimal(held)
    pending_q = Decimal(pending)
    sellable = held_q - pending_q
    _ = qty
    return ExitClassification(
        is_risk_reducing_exit=True,
        reason_code=None,
        held_quantity=held_q,
        pending_sell_quantity=pending_q,
        sellable_quantity=sellable,
        side="SELL",
    )


def _policy(**overrides) -> ResolvedRiskPolicy:
    base = dict(
        max_order_amount=Decimal("50000"),
        daily_max_order_amount=Decimal("200000"),
        max_total_investment_amount=Decimal("1000000"),
        max_position_amount=Decimal("200000"),
        max_position_count=5,
        max_position_weight=Decimal("0.2"),
        max_investment_ratio=Decimal("0.70"),
        allow_duplicate_buy=True,
        daily_max_loss_amount=Decimal("30000"),
        daily_max_loss_rate=Decimal("0.05"),
        stop_loss_rate=Decimal("0.05"),
        take_profit_rate=Decimal("0.1"),
        trailing_stop_rate=Decimal("0.03"),
        auto_trading_enabled=True,
        buy_enabled=True,
        sell_enabled=True,
        sell_only=False,
        account_paused=False,
        max_order_quantity=Decimal("1000"),
        daily_order_limit=20,
        duplicate_order_window_seconds=5,
        max_open_orders=20,
        max_slippage_rate=Decimal("0.01"),
        anomaly_orders_per_minute=10,
        loop_detect_window_seconds=60,
        arm_ttl_seconds=300,
        source_layers=("system",),
    )
    base.update(overrides)
    return ResolvedRiskPolicy(**base)


def _uba(*, uba_id: int = UBA1380, broker: str = "UPBIT", live: bool = True):
    return SimpleNamespace(
        user_broker_account_id=uba_id,
        user_id=61,
        broker_code=broker,
        is_active=True,
        live_order_enabled=live,
        live_armed=True,
        arm_token_hash="x",
        arm_expires_at=None,
        live_approved_at=None,
        live_approved_by=None,
    )


def _pipeline_session(uba):
    session = MagicMock()
    session.get.return_value = uba
    # entity 조회는 None; 주문수는 테스트에서 _count_orders_today patch
    session.scalar = MagicMock(return_value=None)
    session.scalars.return_value = []
    return session


def _account(
    *,
    open_count: int = 5,
    held: str = "100",
    pending: str = "0",
) -> RiskAccountState:
    return RiskAccountState(
        cash_balance=Decimal("1000000"),
        total_asset_value=Decimal("2000000"),
        invested_amount=Decimal("500000"),
        daily_realized_profit_loss=ZERO,
        daily_unrealized_profit_loss=ZERO,
        open_position_count=open_count,
        symbol_position_quantity=Decimal(held),
        symbol_pending_sell_quantity=Decimal(pending),
    )


def _guard_ready(session, account: RiskAccountState, policy: ResolvedRiskPolicy):
    guard = DatabaseBackedRiskOrderGuard(session, broker_code="UPBIT")
    guard._account_state_service = MagicMock()
    guard._account_state_service.load_by_uba.return_value = account
    guard._account_state_service.load_by_paper_account.return_value = account
    guard._resolver = MagicMock()
    guard._resolver.resolve.return_value = SimpleNamespace(
        to_engine_policy=lambda: policy.to_engine_policy(),
        max_order_quantity=policy.max_order_quantity,
        max_position_amount=policy.max_position_amount,
        max_position_weight=policy.max_position_weight,
        max_total_investment_amount=policy.max_total_investment_amount,
    )
    guard._uba_symbol_invested_amount = MagicMock(return_value=ZERO)
    guard._paper_symbol_invested_amount = MagicMock(return_value=ZERO)
    guard._daily_ordered_amount = MagicMock(return_value=ZERO)
    guard._paper_open_position_count = MagicMock(
        return_value=account.open_position_count
    )
    guard._paper_symbol_qty = MagicMock(
        return_value=account.symbol_position_quantity
    )
    return guard


def _sell_order(*, qty: str = "10", price: str = "1000", reducing: bool = True):
    return RiskOrderRequest(
        exchange_code="UPBIT",
        symbol="KRW-XRP",
        side=RiskOrderSide.SELL,
        quantity=Decimal(qty),
        price=Decimal(price),
        requested_at=datetime.now(timezone.utc),
        user_broker_account_id=UBA1380,
        environment="LIVE",
        is_risk_reducing=reducing,
    )


def test_classify_buy_is_not_exit() -> None:
    clf = classify_risk_reducing_exit(
        MagicMock(),
        side="BUY",
        symbol="KRW-XRP",
        exchange_code="UPBIT",
        quantity=Decimal("1"),
        user_broker_account_id=UBA1380,
    )
    assert clf.is_risk_reducing_exit is False
    assert clf.reason_code is None


def test_classify_zero_qty_blocks() -> None:
    clf = classify_risk_reducing_exit(
        MagicMock(),
        side="SELL",
        symbol="KRW-XRP",
        exchange_code="UPBIT",
        quantity=ZERO,
        user_broker_account_id=UBA1380,
    )
    assert clf.reason_code == REASON_INVALID_ORDER_QUANTITY


def test_classify_negative_qty_blocks() -> None:
    clf = classify_risk_reducing_exit(
        MagicMock(),
        side="SELL",
        symbol="KRW-XRP",
        exchange_code="UPBIT",
        quantity=Decimal("-1"),
        user_broker_account_id=UBA1380,
    )
    assert clf.reason_code == REASON_INVALID_ORDER_QUANTITY


def test_classify_partial_exit_pass() -> None:
    pos = SimpleNamespace(
        symbol="KRW-XRP", exchange_code="UPBIT", quantity=Decimal("100")
    )
    session = MagicMock()
    session.scalars.return_value = []
    with patch(
        "stock_platform.broker.account_repository.BrokerAccountSnapshotRepository"
    ) as Repo:
        Repo.return_value.get_active_by_uba.return_value = (object(), [pos])
        clf = classify_risk_reducing_exit(
            session,
            side="SELL",
            symbol="KRW-XRP",
            exchange_code="UPBIT",
            quantity=Decimal("10"),
            user_broker_account_id=UBA1380,
        )
    assert clf.is_risk_reducing_exit is True
    assert clf.held_quantity == Decimal("100")


def test_classify_full_exit_pass() -> None:
    pos = SimpleNamespace(
        symbol="KRW-XRP", exchange_code="UPBIT", quantity=Decimal("100")
    )
    session = MagicMock()
    session.scalars.return_value = []
    with patch(
        "stock_platform.broker.account_repository.BrokerAccountSnapshotRepository"
    ) as Repo:
        Repo.return_value.get_active_by_uba.return_value = (object(), [pos])
        clf = classify_risk_reducing_exit(
            session,
            side="SELL",
            symbol="KRW-XRP",
            exchange_code="UPBIT",
            quantity=Decimal("100"),
            user_broker_account_id=UBA1380,
        )
    assert clf.is_risk_reducing_exit is True


def test_classify_no_position_blocks() -> None:
    session = MagicMock()
    session.scalars.return_value = []
    with patch(
        "stock_platform.broker.account_repository.BrokerAccountSnapshotRepository"
    ) as Repo:
        Repo.return_value.get_active_by_uba.return_value = (object(), [])
        clf = classify_risk_reducing_exit(
            session,
            side="SELL",
            symbol="KRW-XXX",
            exchange_code="UPBIT",
            quantity=Decimal("1"),
            user_broker_account_id=UBA1380,
        )
    assert clf.reason_code == REASON_NO_POSITION_TO_SELL


def test_classify_oversell_blocks() -> None:
    pos = SimpleNamespace(
        symbol="KRW-XRP", exchange_code="UPBIT", quantity=Decimal("100")
    )
    session = MagicMock()
    session.scalars.return_value = []
    with patch(
        "stock_platform.broker.account_repository.BrokerAccountSnapshotRepository"
    ) as Repo:
        Repo.return_value.get_active_by_uba.return_value = (object(), [pos])
        clf = classify_risk_reducing_exit(
            session,
            side="SELL",
            symbol="KRW-XRP",
            exchange_code="UPBIT",
            quantity=Decimal("101"),
            user_broker_account_id=UBA1380,
        )
    assert clf.reason_code == REASON_SELL_QUANTITY


def test_classify_pending_sell_oversell_70_pass_71_block() -> None:
    pos = SimpleNamespace(
        symbol="KRW-XRP", exchange_code="UPBIT", quantity=Decimal("100")
    )
    pending = [
        SimpleNamespace(
            remaining_quantity=Decimal("30"),
            order_quantity=Decimal("30"),
            filled_quantity=ZERO,
        )
    ]
    session = MagicMock()
    session.scalars.return_value = pending
    with patch(
        "stock_platform.broker.account_repository.BrokerAccountSnapshotRepository"
    ) as Repo:
        Repo.return_value.get_active_by_uba.return_value = (object(), [pos])
        ok = classify_risk_reducing_exit(
            session,
            side="SELL",
            symbol="KRW-XRP",
            exchange_code="UPBIT",
            quantity=Decimal("70"),
            user_broker_account_id=UBA1380,
        )
        bad = classify_risk_reducing_exit(
            session,
            side="SELL",
            symbol="KRW-XRP",
            exchange_code="UPBIT",
            quantity=Decimal("71"),
            user_broker_account_id=UBA1380,
        )
    assert ok.is_risk_reducing_exit is True
    assert ok.sellable_quantity == Decimal("70")
    assert bad.reason_code == REASON_SELL_QUANTITY


def test_classify_cross_uba_blocks_with_no_position() -> None:
    session = MagicMock()
    session.scalars.return_value = []
    with patch(
        "stock_platform.broker.account_repository.BrokerAccountSnapshotRepository"
    ) as Repo:
        Repo.return_value.get_active_by_uba.return_value = (object(), [])
        clf = classify_risk_reducing_exit(
            session,
            side="SELL",
            symbol="KRW-XRP",
            exchange_code="UPBIT",
            quantity=Decimal("10"),
            user_broker_account_id=UBA1380,
        )
        Repo.return_value.get_active_by_uba.assert_called_with(UBA1380)
    assert clf.reason_code == REASON_NO_POSITION_TO_SELL


def test_classify_paper_uses_paper_position_not_live_gates() -> None:
    session = MagicMock()
    paper_row = SimpleNamespace(
        symbol="KRW-XRP",
        exchange_code="UPBIT",
        quantity=Decimal("8"),
    )
    session.scalars.side_effect = [[paper_row], []]
    clf = classify_risk_reducing_exit(
        session,
        side="SELL",
        symbol="KRW-XRP",
        exchange_code="UPBIT",
        quantity=Decimal("3"),
        user_broker_account_id=None,
        paper_account_id=99,
        environment="PAPER",
    )
    assert clf.is_risk_reducing_exit is True
    assert clf.held_quantity == Decimal("8")


def test_sell_quantity_rule_subtracts_pending() -> None:
    rule = SellQuantityRule()
    account = _account(held="100", pending="30")
    ok = rule.evaluate(
        order=_sell_order(qty="70"),
        account=account,
        policy=RiskPolicy(),
    )
    bad = rule.evaluate(
        order=_sell_order(qty="71"),
        account=account,
        policy=RiskPolicy(),
    )
    assert ok.level == RiskDecisionLevel.PASS
    assert bad.level == RiskDecisionLevel.BLOCK


def test_max_order_amount_skipped_for_verified_exit() -> None:
    rule = MaximumOrderAmountRule()
    result = rule.evaluate(
        order=_sell_order(qty="100", price="10000", reducing=True),
        account=_account(),
        policy=RiskPolicy(max_order_amount=Decimal("1000")),
    )
    assert result.level == RiskDecisionLevel.PASS
    assert result.detail.get("exit_skip") is True


def test_max_order_amount_still_blocks_unverified_sell() -> None:
    rule = MaximumOrderAmountRule()
    result = rule.evaluate(
        order=_sell_order(qty="100", price="10000", reducing=False),
        account=_account(),
        policy=RiskPolicy(max_order_amount=Decimal("1000")),
    )
    assert result.level == RiskDecisionLevel.BLOCK


def test_engine_position_cap_allows_sell_blocks_new_buy() -> None:
    account = _account(open_count=5, held="0")
    policy = RiskPolicy(
        max_open_positions=5,
        max_order_amount=Decimal("100000000"),
        enforce_krx_market_hours=False,
    )
    buy = RiskOrderRequest(
        exchange_code="UPBIT",
        symbol="KRW-XXX",
        side=RiskOrderSide.BUY,
        quantity=Decimal("1"),
        price=Decimal("1000"),
        requested_at=datetime.now(timezone.utc),
        user_broker_account_id=UBA1380,
        environment="LIVE",
    )
    buy_result = realtime_risk_engine.evaluate(
        order=buy, account=account, policy=policy
    )
    sell_result = realtime_risk_engine.evaluate(
        order=_sell_order(qty="10"),
        account=_account(open_count=5, held="100"),
        policy=policy,
    )
    assert buy_result.allowed is False
    assert sell_result.allowed is True


def _eval_pipeline(session, **kwargs):
    defaults = dict(
        user_id=61,
        user_broker_account_id=UBA1380,
        broker_code="UPBIT",
        exchange_code="UPBIT",
        symbol="KRW-XRP",
        quantity=Decimal("10"),
        price=Decimal("1000"),
        emit_side_effects=False,
        require_arm=False,
        skip_market_hours=True,
    )
    defaults.update(kwargs)
    return LiveOrderSafetyPipeline(session).evaluate(**defaults)


def test_pipeline_position_cap_exit_sell_pass() -> None:
    session = _pipeline_session(_uba())
    with (
        patch(
            "stock_platform.order.live_safety_pipeline.ResolvedRiskPolicyResolver"
        ) as resolver,
        patch(
            "stock_platform.order.live_safety_pipeline.PersistentKillSwitchGuard"
        ) as ks,
        patch(
            "stock_platform.risk_engine.exit_risk.classify_risk_reducing_exit",
            return_value=_verified_exit(),
        ),
        patch(
            "stock_platform.operation.live_health_gate.assert_live_orders_allowed"
        ),
        patch(
            "stock_platform.broker.live_config_gate.evaluate_live_flag_consistency",
            return_value=SimpleNamespace(code="OK"),
        ),
    ):
        ks.return_value.require_order_allowed.return_value = None
        resolver.return_value.resolve.return_value = _policy(
            max_order_amount=Decimal("1"),
        )
        decision = _eval_pipeline(session, side="SELL")
    assert decision.allowed is True
    assert decision.reason_code == "LIVE_SAFETY_PASS"


def test_pipeline_daily_limit_blocks_buy_allows_exit() -> None:
    policy = _policy(daily_order_limit=20, max_order_amount=Decimal("50000"))
    session_buy = _pipeline_session(_uba())
    with (
        patch(
            "stock_platform.order.live_safety_pipeline.ResolvedRiskPolicyResolver"
        ) as resolver,
        patch(
            "stock_platform.order.live_safety_pipeline.PersistentKillSwitchGuard"
        ) as ks,
        patch(
            "stock_platform.operation.live_health_gate.assert_live_orders_allowed"
        ),
        patch(
            "stock_platform.broker.live_config_gate.evaluate_live_flag_consistency",
            return_value=SimpleNamespace(code="OK"),
        ),
        patch.object(
            LiveOrderSafetyPipeline,
            "_count_orders_today",
            return_value=20,
        ),
        patch.object(
            LiveOrderSafetyPipeline,
            "_is_duplicate",
            return_value=False,
        ),
    ):
        ks.return_value.require_order_allowed.return_value = None
        resolver.return_value.resolve.return_value = policy
        buy = _eval_pipeline(
            session_buy, side="BUY", symbol="KRW-XXX"
        )
    assert buy.reason_code == "DAILY_ORDER_LIMIT_EXCEEDED"

    session_sell = _pipeline_session(_uba())
    with (
        patch(
            "stock_platform.order.live_safety_pipeline.ResolvedRiskPolicyResolver"
        ) as resolver,
        patch(
            "stock_platform.order.live_safety_pipeline.PersistentKillSwitchGuard"
        ) as ks,
        patch(
            "stock_platform.risk_engine.exit_risk.classify_risk_reducing_exit",
            return_value=_verified_exit(),
        ),
        patch(
            "stock_platform.operation.live_health_gate.assert_live_orders_allowed"
        ),
        patch(
            "stock_platform.broker.live_config_gate.evaluate_live_flag_consistency",
            return_value=SimpleNamespace(code="OK"),
        ),
        patch.object(
            LiveOrderSafetyPipeline,
            "_count_orders_today",
            return_value=20,
        ),
        patch.object(
            LiveOrderSafetyPipeline,
            "_is_duplicate",
            return_value=False,
        ),
    ):
        ks.return_value.require_order_allowed.return_value = None
        resolver.return_value.resolve.return_value = policy
        sell = _eval_pipeline(session_sell, side="SELL")
    assert sell.allowed is True


def test_pipeline_open_order_limit_blocks_buy_allows_exit() -> None:
    session = MagicMock()
    session.get.return_value = _uba()

    def _scalar(*_a, **_k):
        return 0

    session.scalar = MagicMock(side_effect=_scalar)
    session.scalars.return_value = []
    policy = _policy(max_open_orders=20, daily_order_limit=100)
    remote_block = SimpleNamespace(
        canonical_count=20,
        auto_open_count=20,
        manual_open_count=0,
        unknown_open_count=0,
        total_open_count=20,
        local_open_count=20,
        remote_open_count=0,
        remote_unmapped_count=0,
        mapped_remote_count=0,
        remote_state="FRESH",
        remote_state_ok=True,
        source="TEST",
        reason_code=None,
        as_detail=lambda: {
            "open_order_count": 20,
            "auto_open_orders": 20,
            "manual_open_orders": 0,
            "unknown_open_orders": 0,
            "local_open_order_count": 20,
            "remote_open_order_count": 0,
            "remote_unmapped_open_order_count": 0,
        },
    )
    with (
        patch(
            "stock_platform.order.live_safety_pipeline.ResolvedRiskPolicyResolver"
        ) as resolver,
        patch(
            "stock_platform.order.live_safety_pipeline.PersistentKillSwitchGuard"
        ) as ks,
        patch(
            "stock_platform.operation.live_health_gate.assert_live_orders_allowed"
        ),
        patch(
            "stock_platform.broker.live_config_gate.evaluate_live_flag_consistency",
            return_value=SimpleNamespace(code="OK"),
        ),
        patch(
            "stock_platform.order.live_safety_pipeline.evaluate_live_open_order_exposure",
            return_value=remote_block,
        ),
        patch.object(
            LiveOrderSafetyPipeline,
            "_count_orders_today",
            return_value=0,
        ),
        patch.object(
            LiveOrderSafetyPipeline,
            "_is_duplicate",
            return_value=False,
        ),
    ):
        ks.return_value.require_order_allowed.return_value = None
        resolver.return_value.resolve.return_value = policy
        buy = _eval_pipeline(session, side="BUY", symbol="KRW-XXX")
    assert buy.reason_code == "OPEN_ORDER_LIMIT_EXCEEDED"

    session2 = _pipeline_session(_uba())
    with (
        patch(
            "stock_platform.order.live_safety_pipeline.ResolvedRiskPolicyResolver"
        ) as resolver,
        patch(
            "stock_platform.order.live_safety_pipeline.PersistentKillSwitchGuard"
        ) as ks,
        patch(
            "stock_platform.risk_engine.exit_risk.classify_risk_reducing_exit",
            return_value=_verified_exit(),
        ),
        patch(
            "stock_platform.operation.live_health_gate.assert_live_orders_allowed"
        ),
        patch(
            "stock_platform.broker.live_config_gate.evaluate_live_flag_consistency",
            return_value=SimpleNamespace(code="OK"),
        ),
    ):
        ks.return_value.require_order_allowed.return_value = None
        resolver.return_value.resolve.return_value = policy
        sell = _eval_pipeline(session2, side="SELL")
    assert sell.allowed is True


def test_pipeline_no_position_sell_blocks() -> None:
    session = _pipeline_session(_uba())
    blocked = ExitClassification(
        is_risk_reducing_exit=False,
        reason_code=REASON_NO_POSITION_TO_SELL,
        held_quantity=ZERO,
        pending_sell_quantity=ZERO,
        sellable_quantity=ZERO,
        side="SELL",
    )
    with (
        patch(
            "stock_platform.order.live_safety_pipeline.ResolvedRiskPolicyResolver"
        ) as resolver,
        patch(
            "stock_platform.order.live_safety_pipeline.PersistentKillSwitchGuard"
        ) as ks,
        patch(
            "stock_platform.risk_engine.exit_risk.classify_risk_reducing_exit",
            return_value=blocked,
        ),
    ):
        ks.return_value.require_order_allowed.return_value = None
        resolver.return_value.resolve.return_value = _policy()
        decision = _eval_pipeline(session, side="SELL", symbol="KRW-XXX")
    assert decision.reason_code == REASON_NO_POSITION_TO_SELL


def test_pipeline_kill_still_blocks_exit() -> None:
    session = _pipeline_session(_uba())
    with (
        patch(
            "stock_platform.order.live_safety_pipeline.ResolvedRiskPolicyResolver"
        ) as resolver,
        patch(
            "stock_platform.order.live_safety_pipeline.PersistentKillSwitchGuard"
        ) as ks,
    ):
        ks.return_value.require_order_allowed.side_effect = PermissionError(
            "kill"
        )
        resolver.return_value.resolve.return_value = _policy()
        decision = _eval_pipeline(session, side="SELL")
    assert decision.reason_code == "KILL_SWITCH_ACTIVE"


def test_pipeline_account_paused_blocks_exit() -> None:
    session = _pipeline_session(_uba())
    with patch(
        "stock_platform.order.live_safety_pipeline.ResolvedRiskPolicyResolver"
    ) as resolver:
        resolver.return_value.resolve.return_value = _policy(account_paused=True)
        decision = _eval_pipeline(session, side="SELL")
    assert decision.reason_code == "ACCOUNT_PAUSED"


def test_pipeline_duplicate_window_still_blocks_exit() -> None:
    session = MagicMock()
    session.get.return_value = _uba()
    session.scalar.side_effect = [0, None, object(), 0, 0]
    with (
        patch(
            "stock_platform.order.live_safety_pipeline.ResolvedRiskPolicyResolver"
        ) as resolver,
        patch(
            "stock_platform.order.live_safety_pipeline.PersistentKillSwitchGuard"
        ) as ks,
        patch(
            "stock_platform.risk_engine.exit_risk.classify_risk_reducing_exit",
            return_value=_verified_exit(),
        ),
    ):
        ks.return_value.require_order_allowed.return_value = None
        resolver.return_value.resolve.return_value = _policy()
        decision = _eval_pipeline(session, side="SELL")
    assert decision.reason_code == "DUPLICATE_ORDER"


def test_guard_exit_pass_at_position_cap() -> None:
    session = MagicMock()
    policy = _policy(max_position_count=5, max_order_amount=Decimal("1"))
    guard = _guard_ready(session, _account(open_count=5, held="100"), policy)
    with (
        patch(
            "stock_platform.risk_engine.exit_risk.classify_risk_reducing_exit",
            return_value=_verified_exit(held="100", qty="10"),
        ),
        patch(
            "stock_platform.risk_engine.order_guard.DatabasePositionLimitRule"
        ) as pos_rule,
    ):
        pos_rule.return_value.evaluate.return_value = SimpleNamespace(
            level=RiskDecisionLevel.PASS,
            rule_code="POSITION_LIMIT",
            message="ok",
            detail={},
        )
        result = guard.check(
            account_number="UBA:1380",
            account_id=None,
            exchange_code="UPBIT",
            symbol="KRW-XRP",
            side="SELL",
            quantity=Decimal("10"),
            price=Decimal("1000"),
            user_id=61,
            user_broker_account_id=UBA1380,
            environment="LIVE",
            is_risk_reducing=False,
        )
    assert result.allowed is True


def test_guard_entry_buy_blocked_at_position_cap() -> None:
    session = MagicMock()
    policy = _policy(max_position_count=5)
    guard = _guard_ready(session, _account(open_count=5, held="0"), policy)
    with patch(
        "stock_platform.risk_engine.order_guard.DatabasePositionLimitRule"
    ) as pos_rule:
        pos_rule.return_value.evaluate.return_value = SimpleNamespace(
            level=RiskDecisionLevel.PASS,
            rule_code="POSITION_LIMIT",
            message="ok",
            detail={},
        )
        result = guard.check(
            account_number="UBA:1380",
            account_id=None,
            exchange_code="UPBIT",
            symbol="KRW-XXX",
            side="BUY",
            quantity=Decimal("1"),
            price=Decimal("1000"),
            user_id=61,
            user_broker_account_id=UBA1380,
            environment="LIVE",
            is_risk_reducing=True,
        )
    assert result.allowed is False


def test_guard_ignores_client_risk_reducing_without_holding() -> None:
    session = MagicMock()
    guard = _guard_ready(session, _account(held="0"), _policy())
    with patch(
        "stock_platform.risk_engine.exit_risk.classify_risk_reducing_exit",
        return_value=ExitClassification(
            is_risk_reducing_exit=False,
            reason_code=REASON_NO_POSITION_TO_SELL,
            held_quantity=ZERO,
            pending_sell_quantity=ZERO,
            sellable_quantity=ZERO,
            side="SELL",
        ),
    ):
        result = guard.check(
            account_number="UBA:1380",
            account_id=None,
            exchange_code="UPBIT",
            symbol="KRW-XXX",
            side="SELL",
            quantity=Decimal("1"),
            price=Decimal("1000"),
            user_id=61,
            user_broker_account_id=UBA1380,
            environment="LIVE",
            is_risk_reducing=True,
        )
    assert result.allowed is False
    assert result.blocked_reason == REASON_NO_POSITION_TO_SELL


def test_guard_paper_sell_does_not_require_live_arm() -> None:
    session = MagicMock()
    guard = _guard_ready(session, _account(open_count=1, held="8"), _policy())
    with (
        patch(
            "stock_platform.risk_engine.exit_risk.classify_risk_reducing_exit",
            return_value=_verified_exit(held="8", qty="3"),
        ),
        patch(
            "stock_platform.risk_engine.order_guard.DatabasePositionLimitRule"
        ) as pos_rule,
        patch(
            "stock_platform.risk_engine.account_ownership.validate_account_ownership",
            return_value=(99, None),
        ),
    ):
        pos_rule.return_value.evaluate.return_value = SimpleNamespace(
            level=RiskDecisionLevel.PASS,
            rule_code="POSITION_LIMIT",
            message="ok",
            detail={},
        )
        result = guard.check(
            account_number="PAPER-99",
            account_id=99,
            exchange_code="UPBIT",
            symbol="KRW-XRP",
            side="SELL",
            quantity=Decimal("3"),
            price=Decimal("1000"),
            user_id=61,
            user_broker_account_id=None,
            environment="PAPER",
        )
    assert result.allowed is True


def test_kiwoom_pipeline_exit_pass_entry_amount_block() -> None:
    uba = _uba(uba_id=10, broker="KIWOOM")
    session = _pipeline_session(uba)
    with (
        patch(
            "stock_platform.order.live_safety_pipeline.ResolvedRiskPolicyResolver"
        ) as resolver,
        patch(
            "stock_platform.order.live_safety_pipeline.PersistentKillSwitchGuard"
        ) as ks,
        patch(
            "stock_platform.risk_engine.exit_risk.classify_risk_reducing_exit",
            return_value=_verified_exit(held="100", qty="10"),
        ),
        patch(
            "stock_platform.operation.live_health_gate.assert_live_orders_allowed"
        ),
        patch(
            "stock_platform.broker.live_config_gate.evaluate_live_flag_consistency",
            return_value=SimpleNamespace(code="OK"),
        ),
    ):
        ks.return_value.require_order_allowed.return_value = None
        resolver.return_value.resolve.return_value = _policy(
            max_order_amount=Decimal("1"), daily_order_limit=1
        )
        sell = LiveOrderSafetyPipeline(session).evaluate(
            user_id=61,
            user_broker_account_id=10,
            broker_code="KIWOOM",
            exchange_code="KRX",
            symbol="005930",
            side="SELL",
            quantity=Decimal("10"),
            price=Decimal("70000"),
            emit_side_effects=False,
            require_arm=False,
            skip_market_hours=True,
        )
    assert sell.allowed is True

    session_buy = MagicMock()
    session_buy.get.return_value = uba
    session_buy.scalar.side_effect = [0, None, None, 0, 0]
    with (
        patch(
            "stock_platform.order.live_safety_pipeline.ResolvedRiskPolicyResolver"
        ) as resolver,
        patch(
            "stock_platform.order.live_safety_pipeline.PersistentKillSwitchGuard"
        ) as ks,
    ):
        ks.return_value.require_order_allowed.return_value = None
        resolver.return_value.resolve.return_value = _policy(
            max_order_amount=Decimal("1")
        )
        buy = LiveOrderSafetyPipeline(session_buy).evaluate(
            user_id=61,
            user_broker_account_id=10,
            broker_code="KIWOOM",
            exchange_code="KRX",
            symbol="005930",
            side="BUY",
            quantity=Decimal("10"),
            price=Decimal("70000"),
            emit_side_effects=False,
            require_arm=False,
            skip_market_hours=True,
        )
    assert buy.reason_code == "ORDER_AMOUNT_EXCEEDED"


def test_paper_pipeline_skips_live_exit_gates() -> None:
    session = MagicMock()
    decision = LiveOrderSafetyPipeline(session).evaluate(
        user_id=1,
        user_broker_account_id=99,
        broker_code="PAPER",
        exchange_code="UPBIT",
        symbol="KRW-XRP",
        side="SELL",
        quantity=Decimal("1"),
        price=Decimal("1000"),
        environment="PAPER",
        emit_side_effects=False,
    )
    assert decision.allowed is True
    assert decision.reason_code == "NOT_LIVE"
    session.get.assert_not_called()


def test_outbox_fail_closed_kill_blocks_exit_payload() -> None:
    from tests.test_outbox_dispatch_fail_closed import (
        _enter_live_pass,
        _exit_patches,
        _payload,
        _uba as outbox_uba,
    )

    session = MagicMock()
    uba = outbox_uba()
    patches, _mocks = _enter_live_pass(session, uba, kill_on=True)
    try:
        payload = _payload()
        payload["side"] = "SELL"
        try:
            assert_live_outbox_dispatch_safety(
                session, payload, outbox_id=99
            )
            raised = False
        except OutboxDispatchSafetyError as exc:
            raised = True
            assert exc.reason_code == REASON_KILL_SWITCH_ACTIVE
        assert raised is True
    finally:
        _exit_patches(patches)


def test_preflight_exit_skips_entry_caps_aligns_with_guard() -> None:
    """PREFLIGHT_EXIT_RISK_GUARD_ALIGNED — OPEN/DAILY/AMOUNT skip on EXIT."""

    from stock_platform.risk_engine.kill_switch_models import (
        KillSwitchState,
        KillSwitchStatus,
    )
    from stock_platform.trading.upbit_live_preflight_service import (
        UpbitLivePreflightService,
    )

    session = MagicMock()
    uba = SimpleNamespace(
        user_broker_account_id=UBA1380,
        user_id=61,
        broker_code="UPBIT",
        is_active=True,
        live_order_enabled=True,
        live_armed=True,
        arm_token_hash="x",
        arm_expires_at=datetime.now(timezone.utc),
        arm_armed_by="admin",
        arm_armed_at=datetime.now(timezone.utc),
    )
    session.get.return_value = uba
    policy = _policy(
        daily_order_limit=1,
        max_open_orders=1,
        max_order_amount=Decimal("1"),
        max_order_quantity=Decimal("1000000"),
        max_slippage_rate=Decimal("0.5"),
    )
    with (
        patch(
            "stock_platform.trading.upbit_live_preflight_service.KillSwitchService"
        ) as ks,
        patch(
            "stock_platform.trading.upbit_live_preflight_service.LiveArmService"
        ) as arm,
        patch(
            "stock_platform.trading.upbit_live_preflight_service.ResolvedRiskPolicyResolver"
        ) as resolver,
        patch(
            "stock_platform.trading.upbit_live_preflight_service.emit_live_safety_audit"
        ),
        patch.object(
            UpbitLivePreflightService,
            "_check_credential",
            return_value=(True, "ok"),
        ),
        patch.object(
            UpbitLivePreflightService,
            "_check_broker_health",
            return_value=(True, "ok"),
        ),
        patch.object(
            UpbitLivePreflightService, "_open_order_count", return_value=5
        ),
        patch.object(
            UpbitLivePreflightService, "_daily_order_count", return_value=20
        ),
        patch(
            "stock_platform.risk_engine.exit_risk.classify_risk_reducing_exit",
            return_value=_verified_exit(held="100", qty="10"),
        ),
    ):
        ks.return_value.get_state.return_value = KillSwitchState(
            status=KillSwitchStatus.INACTIVE,
            reason=None,
            activated_by=None,
            activated_at=None,
            deactivated_by=None,
            deactivated_at=None,
        )
        arm.return_value.expire_if_needed.return_value = False
        arm.return_value.get_arm_status.return_value = {
            "live_armed": True,
            "arm_expires_at": uba.arm_expires_at.isoformat(),
        }
        arm.return_value.validate_arm_authorization.return_value = (
            True,
            "ARM_OK",
        )
        resolver.return_value.resolve.return_value = policy
        result = UpbitLivePreflightService(session).run(
            user_broker_account_id=UBA1380,
            market="KRW-XRP",
            side="SELL",
            amount=Decimal("5000"),
            limit_price=Decimal("500"),
            skip_live_network=True,
        )
    codes = {c["code"]: c["status"] for c in result.checks}
    assert codes.get("POSITION_EXIT") == "PASS"
    assert codes.get("OPEN_ORDERS") == "PASS"
    assert codes.get("DAILY_ORDERS") == "PASS"
    assert codes.get("AMOUNT_LIMIT") == "PASS"

