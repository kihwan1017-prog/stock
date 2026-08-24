"""price_daily exchange mapping — KIWOOM scope must seed from KRX instruments."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from stock_platform.realtime.daily_bar_seed import (
    price_daily_exchange_code,
    required_completed_bars,
    seed_registered_consumer,
)
from stock_platform.realtime.hub_constants import ConsumerWarmupStatus
from stock_platform.realtime.ma_evaluator import MovingAverageStrategyEvaluator
from stock_platform.realtime.strategy_models import RealtimeStrategyConfig
from stock_platform.strategy_deployment.runtime_scope import (
    AccountKind,
    StrategyRuntimeScope,
)


def test_price_daily_exchange_code_maps_kiwoom_stock_to_krx() -> None:
    assert (
        price_daily_exchange_code(broker_code="KIWOOM", market_type="STOCK")
        == "KRX"
    )
    assert (
        price_daily_exchange_code(broker_code="KIWOOM", market_type="KRX")
        == "KRX"
    )
    assert (
        price_daily_exchange_code(broker_code="UPBIT", market_type="CRYPTO")
        == "UPBIT"
    )
    assert price_daily_exchange_code(broker_code="PAPER") == "UPBIT"


def test_seed_registered_consumer_uses_krx_for_kiwoom_scope() -> None:
    scope = StrategyRuntimeScope(
        user_id=1,
        account_kind=AccountKind.USER_BROKER,
        account_id=99,
        strategy_id=1,
        strategy_version="t",
        market_type="STOCK",
        broker_code="KIWOOM",
    )
    evaluator = MovingAverageStrategyEvaluator(
        scope,
        RealtimeStrategyConfig(
            short_window=2, long_window=3, timeframe="1D", cooldown_seconds=0
        ),
    )
    consumer = SimpleNamespace(
        evaluator=evaluator, symbols={"005930"}, scope=scope
    )
    required = required_completed_bars(3)
    closes = [
        (date(2026, 8, 1 + i), Decimal(str(100 + i))) for i in range(required)
    ]

    def _fake_load(session, *, exchange_code, symbol, required, today=None):
        assert exchange_code == "KRX"
        assert symbol == "005930"
        return closes[-required:]

    with patch(
        "stock_platform.realtime.daily_bar_seed.load_completed_daily_closes",
        side_effect=_fake_load,
    ):
        result = seed_registered_consumer(
            consumer,
            force=True,
            bootstrap_current_day=False,
            session=SimpleNamespace(),
        )

    assert result.get("seeded") is True
    assert evaluator.warmup_status("005930") == ConsumerWarmupStatus.READY
    assert len(evaluator.get_state("005930").prices) == required
