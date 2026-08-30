"""EXIT SELL qty invariant — synthetic/fake broker (no REAL orders).

TEST A–J coverage for ORDER_QTY_EXCEEDED / multi-binding / ownership / retry.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.operation.upbit_exit_intent.constants import (
    STATUS_BLOCKED,
    STATUS_CONFIRMED,
)
from stock_platform.operation.upbit_exit_intent.service import (
    UpbitExitIntentService,
)
from stock_platform.order.live_safety_pipeline import LiveOrderSafetyPipeline
from stock_platform.risk_engine.exit_sell_quantity import (
    ExitSellQuantityPlan,
    resolve_exit_sell_quantity,
)


ZERO = Decimal("0")


def _plan(**kwargs) -> ExitSellQuantityPlan:
    base = dict(
        sell_quantity=ZERO,
        requested_quantity=ZERO,
        broker_held=ZERO,
        pending_sell=ZERO,
        broker_sellable=ZERO,
        strategy_owned=ZERO,
        max_order_quantity=Decimal("100"),
        capped_by=(),
        detail={},
    )
    base.update(kwargs)
    return ExitSellQuantityPlan(**base)


def test_a_local_remaining_gt_broker_free_blocks_oversell() -> None:
    """TEST A: local 181 / broker free 100 → sell <= 100."""

    session = MagicMock()
    with (
        patch(
            "stock_platform.risk_engine.exit_sell_quantity.acquire_exit_sell_scope_lock"
        ),
        patch(
            "stock_platform.risk_engine.exit_sell_quantity.load_held_quantity",
            return_value=Decimal("100"),
        ),
        patch(
            "stock_platform.risk_engine.exit_sell_quantity.load_pending_sell_quantity",
            return_value=ZERO,
        ),
        patch(
            "stock_platform.risk_engine.exit_sell_quantity.load_strategy_owned_open_quantity",
            return_value=Decimal("181"),
        ),
    ):
        plan = resolve_exit_sell_quantity(
            session,
            user_broker_account_id=1380,
            symbol="KRW-ENA",
            exchange_code="UPBIT",
            environment="LIVE",
            broker_code="UPBIT",
            requested_quantity=Decimal("181"),
            max_order_quantity=Decimal("100"),
        )
    assert plan.sell_quantity == Decimal("100")
    assert plan.sell_quantity <= plan.broker_sellable
    assert "BROKER_SELLABLE" in plan.capped_by or "MAX_ORDER_QUANTITY" in plan.capped_by
    # 181 제출 금지
    assert plan.sell_quantity < Decimal("181")


def test_b_multi_binding_total_sell_bounded_by_broker_free() -> None:
    """TEST B: A=100 B=100 / free=150 → total submit cap <=150 (and max_qty)."""

    session = MagicMock()
    with (
        patch(
            "stock_platform.risk_engine.exit_sell_quantity.acquire_exit_sell_scope_lock"
        ),
        patch(
            "stock_platform.risk_engine.exit_sell_quantity.load_held_quantity",
            return_value=Decimal("150"),
        ),
        patch(
            "stock_platform.risk_engine.exit_sell_quantity.load_pending_sell_quantity",
            return_value=ZERO,
        ),
        patch(
            "stock_platform.risk_engine.exit_sell_quantity.load_strategy_owned_open_quantity",
            return_value=Decimal("200"),
        ),
    ):
        plan = resolve_exit_sell_quantity(
            session,
            user_broker_account_id=1380,
            symbol="KRW-ENA",
            exchange_code="UPBIT",
            environment="LIVE",
            broker_code="UPBIT",
            requested_quantity=Decimal("200"),
            max_order_quantity=Decimal("100"),
        )
    # 1회 submit은 max_order + sellable 교집합
    assert plan.sell_quantity == Decimal("100")
    assert plan.sell_quantity <= Decimal("150")


def test_c_locked_qty_subtracted() -> None:
    """TEST C: total=200 free=100 locked/pending=100 → 신규 200 금지."""

    session = MagicMock()
    with (
        patch(
            "stock_platform.risk_engine.exit_sell_quantity.acquire_exit_sell_scope_lock"
        ),
        patch(
            "stock_platform.risk_engine.exit_sell_quantity.load_held_quantity",
            return_value=Decimal("200"),
        ),
        patch(
            "stock_platform.risk_engine.exit_sell_quantity.load_pending_sell_quantity",
            return_value=Decimal("100"),
        ),
        patch(
            "stock_platform.risk_engine.exit_sell_quantity.load_strategy_owned_open_quantity",
            return_value=Decimal("200"),
        ),
    ):
        plan = resolve_exit_sell_quantity(
            session,
            user_broker_account_id=1380,
            symbol="KRW-ENA",
            exchange_code="UPBIT",
            environment="LIVE",
            broker_code="UPBIT",
            requested_quantity=Decimal("200"),
            max_order_quantity=Decimal("1000"),
        )
    assert plan.broker_sellable == Decimal("100")
    assert plan.sell_quantity == Decimal("100")
    assert plan.sell_quantity < Decimal("200")


def test_d_partial_remaining_uses_sellable() -> None:
    """TEST D: partial 후 remaining/local vs free → sellable 정확."""

    session = MagicMock()
    with (
        patch(
            "stock_platform.risk_engine.exit_sell_quantity.acquire_exit_sell_scope_lock"
        ),
        patch(
            "stock_platform.risk_engine.exit_sell_quantity.load_held_quantity",
            return_value=Decimal("81.81818180"),
        ),
        patch(
            "stock_platform.risk_engine.exit_sell_quantity.load_pending_sell_quantity",
            return_value=ZERO,
        ),
        patch(
            "stock_platform.risk_engine.exit_sell_quantity.load_strategy_owned_open_quantity",
            return_value=Decimal("81.81818180"),
        ),
    ):
        plan = resolve_exit_sell_quantity(
            session,
            user_broker_account_id=1380,
            symbol="KRW-ENA",
            exchange_code="UPBIT",
            environment="LIVE",
            broker_code="UPBIT",
            requested_quantity=Decimal("181.81818180"),
            max_order_quantity=Decimal("100"),
        )
    assert plan.sell_quantity == Decimal("81.81818180")


def test_e_concurrent_exit_uses_advisory_lock_path() -> None:
    """TEST E: resolve 시 UBA+symbol lock 호출 — double reservation 방지 경로."""

    session = MagicMock()
    lock = MagicMock()
    with (
        patch(
            "stock_platform.risk_engine.exit_sell_quantity.acquire_exit_sell_scope_lock",
            lock,
        ),
        patch(
            "stock_platform.risk_engine.exit_sell_quantity.load_held_quantity",
            return_value=Decimal("150"),
        ),
        patch(
            "stock_platform.risk_engine.exit_sell_quantity.load_pending_sell_quantity",
            return_value=ZERO,
        ),
        patch(
            "stock_platform.risk_engine.exit_sell_quantity.load_strategy_owned_open_quantity",
            return_value=Decimal("150"),
        ),
    ):
        p1 = resolve_exit_sell_quantity(
            session,
            user_broker_account_id=1380,
            symbol="KRW-ENA",
            exchange_code="UPBIT",
            environment="LIVE",
            broker_code="UPBIT",
            requested_quantity=Decimal("100"),
            max_order_quantity=Decimal("100"),
        )
        # 두 번째 intent가 pending을 보면 sellable 감소
        with patch(
            "stock_platform.risk_engine.exit_sell_quantity.load_pending_sell_quantity",
            return_value=Decimal("100"),
        ):
            p2 = resolve_exit_sell_quantity(
                session,
                user_broker_account_id=1380,
                symbol="KRW-ENA",
                exchange_code="UPBIT",
                environment="LIVE",
                broker_code="UPBIT",
                requested_quantity=Decimal("100"),
                max_order_quantity=Decimal("100"),
            )
    assert lock.call_count >= 2
    assert p1.sell_quantity + p2.sell_quantity <= Decimal("150")


def test_f_auto_does_not_invade_manual() -> None:
    """TEST F: broker 200 / AUTO owned 100 → AUTO exit <=100."""

    session = MagicMock()
    with (
        patch(
            "stock_platform.risk_engine.exit_sell_quantity.acquire_exit_sell_scope_lock"
        ),
        patch(
            "stock_platform.risk_engine.exit_sell_quantity.load_held_quantity",
            return_value=Decimal("200"),
        ),
        patch(
            "stock_platform.risk_engine.exit_sell_quantity.load_pending_sell_quantity",
            return_value=ZERO,
        ),
        patch(
            "stock_platform.risk_engine.exit_sell_quantity.load_strategy_owned_open_quantity",
            return_value=Decimal("100"),
        ),
    ):
        plan = resolve_exit_sell_quantity(
            session,
            user_broker_account_id=1380,
            symbol="KRW-ENA",
            exchange_code="UPBIT",
            environment="LIVE",
            broker_code="UPBIT",
            requested_quantity=Decimal("200"),
            max_order_quantity=Decimal("1000"),
            require_strategy_owned=True,
        )
    assert plan.sell_quantity == Decimal("100")
    assert "STRATEGY_OWNED" in plan.capped_by


def test_g_deterministic_reject_suppresses_retry() -> None:
    """TEST G: 상태 변화 없이 ORDER_QTY_EXCEEDED → suppress."""

    row = SimpleNamespace(
        status=STATUS_BLOCKED,
        last_block_reason="ORDER_QTY_EXCEEDED",
        next_retry_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        detail_json={"deterministic_reject_fp": "qty=181|limit=100|sellable=181|held=181|pending=0"},
        event_log_json=[],
        updated_at=None,
    )
    session = MagicMock()
    svc = UpbitExitIntentService(session)
    with patch.object(svc, "get_active", return_value=row):
        suppress, reason = svc.should_suppress_sell_emit(
            user_broker_account_id=1380,
            symbol="KRW-ENA",
            current_fingerprint="qty=181|limit=100|sellable=181|held=181|pending=0",
        )
    assert suppress is True
    assert reason == "DETERMINISTIC_QTY_REJECT_COOLDOWN"


def test_h_state_change_allows_reevaluation() -> None:
    """TEST H: broker qty 변화(지문 변경) → suppress 해제."""

    row = SimpleNamespace(
        status=STATUS_BLOCKED,
        last_block_reason="ORDER_QTY_EXCEEDED",
        next_retry_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        detail_json={"deterministic_reject_fp": "qty=181|limit=100|sellable=181|held=181|pending=0"},
        event_log_json=[],
    )
    session = MagicMock()
    svc = UpbitExitIntentService(session)
    with patch.object(svc, "get_active", return_value=row):
        suppress, _ = svc.should_suppress_sell_emit(
            user_broker_account_id=1380,
            symbol="KRW-ENA",
            current_fingerprint="qty=81|limit=100|sellable=81|held=81|pending=0",
        )
    assert suppress is False


def test_i_normal_single_binding_sell_unchanged() -> None:
    """TEST I: single binding 45.45 / max 100 → 전량 허용."""

    session = MagicMock()
    with (
        patch(
            "stock_platform.risk_engine.exit_sell_quantity.acquire_exit_sell_scope_lock"
        ),
        patch(
            "stock_platform.risk_engine.exit_sell_quantity.load_held_quantity",
            return_value=Decimal("45.45454545"),
        ),
        patch(
            "stock_platform.risk_engine.exit_sell_quantity.load_pending_sell_quantity",
            return_value=ZERO,
        ),
        patch(
            "stock_platform.risk_engine.exit_sell_quantity.load_strategy_owned_open_quantity",
            return_value=Decimal("45.45454545"),
        ),
    ):
        plan = resolve_exit_sell_quantity(
            session,
            user_broker_account_id=1380,
            symbol="KRW-ENA",
            exchange_code="UPBIT",
            environment="LIVE",
            broker_code="UPBIT",
            requested_quantity=Decimal("45.45454545"),
            max_order_quantity=Decimal("100"),
        )
    assert plan.sell_quantity == Decimal("45.45454545")
    assert plan.capped_by == ()


def test_j_exit_pipeline_clamps_instead_of_qty_reject() -> None:
    """TEST J: verified EXIT + qty>max → clamp (ORDER_QTY_EXCEEDED 아님)."""

    from stock_platform.risk_engine.exit_risk import ExitClassification
    from stock_platform.risk_engine.resolved_policy import ResolvedRiskPolicy

    uba = SimpleNamespace(
        user_id=1,
        is_active=True,
        live_order_enabled=True,
        broker_code="UPBIT",
    )
    session = MagicMock()
    session.get.return_value = uba
    # pipeline이 소비하는 scalar 여유분
    session.scalar.side_effect = [0, None, None, 0, 0, 0, 0, 0, None] * 3
    clf = ExitClassification(
        is_risk_reducing_exit=True,
        reason_code=None,
        held_quantity=Decimal("181.81818180"),
        pending_sell_quantity=ZERO,
        sellable_quantity=Decimal("181.81818180"),
        side="SELL",
    )
    policy = ResolvedRiskPolicy(
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
        max_order_quantity=Decimal("100"),
        daily_order_limit=100,
        duplicate_order_window_seconds=0,
        max_open_orders=20,
        max_slippage_rate=Decimal("0.01"),
        anomaly_orders_per_minute=10,
        loop_detect_window_seconds=60,
        arm_ttl_seconds=300,
        source_layers=("system",),
    )
    with (
        patch(
            "stock_platform.order.live_safety_pipeline.ResolvedRiskPolicyResolver"
        ) as resolver_cls,
        patch(
            "stock_platform.order.live_safety_pipeline.PersistentKillSwitchGuard"
        ) as ks,
        patch(
            "stock_platform.risk_engine.exit_risk.classify_risk_reducing_exit",
            return_value=clf,
        ),
        patch(
            "stock_platform.broker.upbit.rules.evaluate_upbit_min_notional",
            return_value=None,
        ),
        patch(
            "stock_platform.order.live_open_order_exposure.evaluate_live_open_order_exposure",
            return_value=SimpleNamespace(
                allowed=True,
                reason_code=None,
                detail={},
            ),
        ),
        patch(
            "stock_platform.order.live_safety_pipeline.emit_live_safety_audit"
        ),
        patch(
            "stock_platform.order.live_safety_pipeline.emit_live_order_telegram"
        ),
    ):
        ks.return_value.require_order_allowed.return_value = None
        resolver_cls.return_value.resolve.return_value = policy
        decision = LiveOrderSafetyPipeline(session).evaluate(
            user_id=1,
            user_broker_account_id=10,
            broker_code="UPBIT",
            exchange_code="UPBIT",
            symbol="KRW-ENA",
            side="SELL",
            quantity=Decimal("181.81818180"),
            price=Decimal("220"),
            emit_side_effects=False,
            require_arm=False,
            skip_market_hours=True,
            order_type="LIMIT",
            order_source="AUTO",
            is_risk_reducing=True,
        )
    assert decision.reason_code != "ORDER_QTY_EXCEEDED"
    assert decision.detail.get("quantity_clamped_to_max_order") is True
    assert decision.detail.get("effective_quantity") == "100"


def test_entry_still_hard_rejects_qty_exceeded() -> None:
    """ENTRY는 기존처럼 ORDER_QTY_EXCEEDED hard reject (regression)."""

    from stock_platform.risk_engine.resolved_policy import ResolvedRiskPolicy

    uba = SimpleNamespace(
        user_id=1,
        is_active=True,
        live_order_enabled=True,
        broker_code="KIWOOM",
    )
    session = MagicMock()
    session.get.return_value = uba
    policy = ResolvedRiskPolicy(
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
        max_order_quantity=Decimal("10"),
        daily_order_limit=100,
        duplicate_order_window_seconds=5,
        max_open_orders=20,
        max_slippage_rate=Decimal("0.01"),
        anomaly_orders_per_minute=10,
        loop_detect_window_seconds=60,
        arm_ttl_seconds=300,
        source_layers=("system",),
    )
    with (
        patch(
            "stock_platform.order.live_safety_pipeline.ResolvedRiskPolicyResolver"
        ) as resolver_cls,
        patch(
            "stock_platform.order.live_safety_pipeline.PersistentKillSwitchGuard"
        ) as ks,
        patch(
            "stock_platform.broker.upbit.rules.evaluate_upbit_min_notional",
            return_value=None,
        ),
    ):
        ks.return_value.require_order_allowed.return_value = None
        resolver_cls.return_value.resolve.return_value = policy
        decision = LiveOrderSafetyPipeline(session).evaluate(
            user_id=1,
            user_broker_account_id=10,
            broker_code="KIWOOM",
            exchange_code="KRX",
            symbol="005930",
            side="BUY",
            quantity=Decimal("11"),
            price=Decimal("1000"),
            emit_side_effects=False,
            require_arm=False,
            skip_market_hours=True,
        )
    assert decision.allowed is False
    assert decision.reason_code == "ORDER_QTY_EXCEEDED"
