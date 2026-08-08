"""daily_order_limit — 미전송 retire 주문 제외 정책 테스트."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from stock_platform.order.daily_risk_order_count import (
    RETIRED_UNSUBMITTED_REASON,
    count_daily_risk_orders,
    day_start_kst_as_utc,
    is_retired_unsubmitted_for_daily_risk,
    summarize_daily_risk_orders,
)
from stock_platform.order.live_safety_pipeline import LiveOrderSafetyPipeline
from stock_platform.order.models import OrderStatus
from stock_platform.risk_engine.resolved_policy import ResolvedRiskPolicy


KST = ZoneInfo("Asia/Seoul")


def _policy(**overrides) -> ResolvedRiskPolicy:
    base = dict(
        max_order_amount=Decimal("5000"),
        daily_max_order_amount=Decimal("1000000"),
        max_total_investment_amount=Decimal("10000000"),
        max_position_amount=Decimal("10000000"),
        max_position_count=5,
        max_position_weight=Decimal("1"),
        max_investment_ratio=Decimal("1"),
        allow_duplicate_buy=True,
        daily_max_loss_amount=Decimal("10000000"),
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
        daily_order_limit=1,
        duplicate_order_window_seconds=5,
        max_open_orders=1,
        max_slippage_rate=Decimal("0.01"),
        anomaly_orders_per_minute=10,
        loop_detect_window_seconds=60,
        arm_ttl_seconds=300,
        source_layers=("account",),
    )
    base.update(overrides)
    return ResolvedRiskPolicy(**base)


def _uba():
    return SimpleNamespace(
        user_broker_account_id=1380,
        user_id=61,
        broker_code="UPBIT",
        is_active=True,
        live_order_enabled=True,
        live_armed=True,
        arm_token_hash="x",
        arm_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )


# ----- A–F: 분류 정책 -----


def test_a_retired_unsubmitted_excluded() -> None:
    """CANCELLED + null broker + attempts0 + retire history → 제외."""

    assert (
        is_retired_unsubmitted_for_daily_risk(
            status_code=OrderStatus.CANCELLED.value,
            broker_order_id=None,
            submission_attempt_count=0,
            has_unsubmitted_retire_history=True,
        )
        is True
    )


def test_b_submitted_then_cancelled_included() -> None:
    """제출 후 CANCELLED — broker_order_id 있으면 포함(제외 아님)."""

    assert (
        is_retired_unsubmitted_for_daily_risk(
            status_code=OrderStatus.CANCELLED.value,
            broker_order_id="upbit-uuid-1",
            submission_attempt_count=0,
            has_unsubmitted_retire_history=False,
        )
        is False
    )
    assert (
        is_retired_unsubmitted_for_daily_risk(
            status_code=OrderStatus.CANCELLED.value,
            broker_order_id=None,
            submission_attempt_count=1,
            has_unsubmitted_retire_history=False,
        )
        is False
    )


def test_c_pending_not_excluded() -> None:
    assert (
        is_retired_unsubmitted_for_daily_risk(
            status_code=OrderStatus.PENDING.value,
            broker_order_id=None,
            submission_attempt_count=0,
            has_unsubmitted_retire_history=False,
        )
        is False
    )


def test_d_cancelled_without_retire_provenance_not_excluded() -> None:
    """단순 CANCELLED만으로는 제외하지 않음."""

    assert (
        is_retired_unsubmitted_for_daily_risk(
            status_code=OrderStatus.CANCELLED.value,
            broker_order_id=None,
            submission_attempt_count=0,
            has_unsubmitted_retire_history=False,
        )
        is False
    )


def test_reason_constant_matches_retire_service() -> None:
    assert RETIRED_UNSUBMITTED_REASON == "UNSUBMITTED_LIVE_RETIRED"


def test_day_start_kst_boundary() -> None:
    # 2026-08-08 01:00 KST → day start 2026-08-07 15:00 UTC
    now = datetime(2026, 8, 8, 1, 0, tzinfo=KST)
    start = day_start_kst_as_utc(now)
    assert start == datetime(2026, 8, 7, 15, 0, tzinfo=timezone.utc)


# ----- count helper + pipeline evaluate G/H -----


def test_count_daily_risk_orders_delegates_to_session_scalar() -> None:
    session = MagicMock()
    session.scalar.return_value = 0
    assert count_daily_risk_orders(session, 1380) == 0
    assert session.scalar.called


def test_g_retired_fixture_allows_new_order_when_limit_1() -> None:
    """1680과 동일: retire만 있으면 daily_count=0 → limit=1 통과."""

    uba = _uba()
    session = MagicMock()
    session.get.return_value = uba
    # count=0, loss=None, dup=None, open=0, per_min=0
    session.scalar.side_effect = [0, None, None, 0, 0]
    session.scalars.return_value = []

    with (
        patch(
            "stock_platform.order.live_safety_pipeline.ResolvedRiskPolicyResolver"
        ) as resolver_cls,
        patch(
            "stock_platform.order.live_safety_pipeline.PersistentKillSwitchGuard"
        ) as ks,
        patch(
            "stock_platform.order.daily_risk_order_count.count_daily_risk_orders",
            return_value=0,
        ) as cnt,
        patch(
            "stock_platform.operation.live_health_gate.assert_live_orders_allowed",
            return_value=None,
        ),
        patch(
            "stock_platform.broker.live_config_gate.evaluate_live_flag_consistency",
            return_value=SimpleNamespace(code="OK", detail={}),
        ),
    ):
        ks.return_value.require_order_allowed.return_value = None
        resolver_cls.return_value.resolve.return_value = _policy(
            daily_order_limit=1
        )
        decision = LiveOrderSafetyPipeline(session).evaluate(
            user_id=61,
            user_broker_account_id=1380,
            broker_code="UPBIT",
            exchange_code="UPBIT",
            symbol="KRW-XRP",
            side="BUY",
            quantity=Decimal("3.48"),
            price=Decimal("1435"),
            emit_side_effects=False,
            require_arm=False,
            skip_market_hours=True,
        )
    assert cnt.called
    assert decision.allowed is True
    assert decision.reason_code != "DAILY_ORDER_LIMIT_EXCEEDED"


def test_h_real_submitted_today_blocks_when_limit_1() -> None:
    """오늘 실제 제출 1건 + limit=1 → 신규 차단."""

    uba = _uba()
    session = MagicMock()
    session.get.return_value = uba
    session.scalar.side_effect = [1, None, None, 0, 0]
    session.scalars.return_value = []

    with (
        patch(
            "stock_platform.order.live_safety_pipeline.ResolvedRiskPolicyResolver"
        ) as resolver_cls,
        patch(
            "stock_platform.order.live_safety_pipeline.PersistentKillSwitchGuard"
        ) as ks,
        patch(
            "stock_platform.order.daily_risk_order_count.count_daily_risk_orders",
            return_value=1,
        ),
    ):
        ks.return_value.require_order_allowed.return_value = None
        resolver_cls.return_value.resolve.return_value = _policy(
            daily_order_limit=1
        )
        decision = LiveOrderSafetyPipeline(session).evaluate(
            user_id=61,
            user_broker_account_id=1380,
            broker_code="UPBIT",
            exchange_code="UPBIT",
            symbol="KRW-XRP",
            side="BUY",
            quantity=Decimal("3.48"),
            price=Decimal("1435"),
            emit_side_effects=False,
            require_arm=False,
            skip_market_hours=True,
        )
    assert decision.allowed is False
    assert decision.reason_code == "DAILY_ORDER_LIMIT_EXCEEDED"


def test_pipeline_count_orders_today_uses_helper() -> None:
    session = MagicMock()
    with patch(
        "stock_platform.order.daily_risk_order_count.count_daily_risk_orders",
        return_value=7,
    ) as cnt:
        n = LiveOrderSafetyPipeline(session)._count_orders_today(1380)
    assert n == 7
    cnt.assert_called_once_with(session, 1380)


def test_summarize_shape() -> None:
    session = MagicMock()
    session.scalar.side_effect = [1, 1, 0]
    out = summarize_daily_risk_orders(session, 1380)
    assert out["total_created_today"] == 1
    assert out["retired_unsubmitted"] == 1
    assert out["risk_counted_orders"] == 0
