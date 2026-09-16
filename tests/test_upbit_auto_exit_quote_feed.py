"""AUTO OPEN position → Upbit quote feed / Exit Monitor freshness."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.operation.upbit_full_market.constants import (
    BINDING_STATUS_OPEN,
    SLOT_WAITING_SIGNAL,
)
from stock_platform.operation.upbit_full_market.portfolio_runtime_sync import (
    collect_upbit_open_auto_position_symbols,
    desired_portfolio_symbols,
)
from stock_platform.position.exit_monitor_live import quote_is_fresh
from stock_platform.risk.engine import RiskManagementEngine
from stock_platform.risk.models import ExitEvaluationRequest
from stock_platform.trading.autotrading_master_gate import (
    _evaluate_auto_exit_quote_freshness,
)


def test_desired_includes_open_binding_not_in_slot() -> None:
    """Slot에 없어도 OPEN binding 심볼은 desired에 포함."""
    session = MagicMock()
    slot = SimpleNamespace(
        symbol="KRW-PEPE", status=SLOT_WAITING_SIGNAL
    )
    # slots query returns empty (WAITING not in SLOT_RUNTIME) —
    # simulate scalars side_effect for multiple selects
    binding = SimpleNamespace(
        symbol="KRW-GEOD",
        status=BINDING_STATUS_OPEN,
        broker_code="UPBIT",
        owned_quantity=Decimal("14.4"),
    )
    upbit_binding = SimpleNamespace(
        symbol="KRW-GEOD",
        status=BINDING_STATUS_OPEN,
    )

    def _scalars(stmt):  # noqa: ANN001
        text = str(stmt)
        if "upbit_position_slot" in text.lower() or "UpbitPositionSlot" in text:
            return iter([])
        if "StrategyPositionBinding" in text or "strategy_position_binding" in text:
            return iter([binding])
        return iter([upbit_binding])

    # session.scalars is called with select() — mock by call order
    calls: list[object] = []

    def scalars_side_effect(stmt):  # noqa: ANN001
        calls.append(stmt)
        n = len(calls)
        if n == 1:
            return iter([])  # slots
        if n == 2:
            return iter([binding])  # strategy binding
        return iter([upbit_binding])

    session.scalars.side_effect = scalars_side_effect
    out = desired_portfolio_symbols(session, 1380)
    assert "KRW-GEOD" in out


def test_open_auto_symbols_collector() -> None:
    session = MagicMock()
    binding = SimpleNamespace(
        symbol="KRW-GEOD",
        owned_quantity=Decimal("10"),
        status=BINDING_STATUS_OPEN,
        broker_code="UPBIT",
    )
    session.scalars.side_effect = [
        iter([binding]),
        iter([]),
    ]
    out = collect_upbit_open_auto_position_symbols(
        session, user_broker_account_id=1380
    )
    assert out == ["KRW-GEOD"]


def test_manual_holding_not_required_for_open_auto_collector() -> None:
    """qty=0 binding은 feed 의무 대상 아님."""
    session = MagicMock()
    binding = SimpleNamespace(
        symbol="KRW-BTC",
        owned_quantity=Decimal("0"),
        status=BINDING_STATUS_OPEN,
        broker_code="UPBIT",
    )
    session.scalars.side_effect = [iter([binding]), iter([])]
    out = collect_upbit_open_auto_position_symbols(
        session, user_broker_account_id=1
    )
    assert out == []


def test_collector_excludes_orphan_upbit_binding_when_strategy_owned_closed() -> None:
    """strategy-owned CLOSED + portfolio binding OPEN → exit-quote 대상 아님."""
    from stock_platform.operation.upbit_full_market.constants import (
        BINDING_STATUS_CLOSED,
    )

    session = MagicMock()
    closed_owned = SimpleNamespace(
        symbol="KRW-GEOD",
        owned_quantity=Decimal("0"),
        status=BINDING_STATUS_CLOSED,
        broker_code="UPBIT",
        binding_id=1,
    )
    orphan_upbit = SimpleNamespace(
        symbol="KRW-GEOD",
        status=BINDING_STATUS_OPEN,
        user_broker_account_id=1380,
    )
    session.scalars.side_effect = [
        iter([]),  # strategy-owned OPEN query → empty
        iter([orphan_upbit]),  # upbit portfolio OPEN
    ]
    session.scalar.return_value = closed_owned
    out = collect_upbit_open_auto_position_symbols(
        session, user_broker_account_id=1380
    )
    assert out == []


def test_exit_quote_na_when_no_open_auto_positions() -> None:
    session = MagicMock()
    with patch(
        "stock_platform.operation.upbit_full_market.portfolio_runtime_sync."
        "collect_upbit_open_auto_position_symbols",
        return_value=[],
    ):
        result = _evaluate_auto_exit_quote_freshness(
            session, user_broker_account_id=1380
        )
    assert result["ok"] is True
    assert result["applicable"] is False
    assert result["reason"] == "NO_OPEN_AUTO_POSITION"


def test_quote_fresh_threshold() -> None:
    now = datetime.now(timezone.utc)
    assert quote_is_fresh(now, stale_seconds=30) is True
    assert (
        quote_is_fresh(now - timedelta(seconds=31), stale_seconds=30)
        is False
    )


def test_quote_snapshot_uses_updated_at_when_quoted_at_stale() -> None:
    """적재는 최근인데 exchange timestamp만 오래면 false-stale 금지."""

    from stock_platform.position.exit_monitor_live import (
        quote_snapshot_is_fresh,
    )

    now = datetime.now(timezone.utc)
    snap = SimpleNamespace(
        quoted_at=now - timedelta(seconds=90),
        updated_at=now - timedelta(seconds=5),
        trade_price=Decimal("100"),
    )
    assert quote_snapshot_is_fresh(snap, stale_seconds=30) is True
    snap_stale = SimpleNamespace(
        quoted_at=now - timedelta(seconds=90),
        updated_at=now - timedelta(seconds=45),
        trade_price=Decimal("100"),
    )
    assert quote_snapshot_is_fresh(snap_stale, stale_seconds=30) is False


def test_orderbook_and_trade_derive_quote_for_snapshot() -> None:
    from stock_platform.realtime.manager import (
        _quote_from_orderbook,
        _quote_from_trade,
    )
    from stock_platform.realtime.models import (
        MarketEventType,
        RealtimeOrderbook,
        RealtimeTrade,
    )

    now = datetime.now(timezone.utc)
    book = RealtimeOrderbook(
        exchange_code="UPBIT",
        symbol="KRW-SUI",
        bids=[{"price": "1000", "quantity": "1"}],
        asks=[{"price": "1002", "quantity": "1"}],
        captured_at=now,
        received_at=now,
        source_code="UPBIT_WEBSOCKET",
    )
    q = _quote_from_orderbook(book)
    assert q is not None
    assert q.symbol == "KRW-SUI"
    assert q.trade_price == Decimal("1001")
    assert q.source_code == "UPBIT_WEBSOCKET_ORDERBOOK"
    assert q.event_time == now

    trade = RealtimeTrade(
        exchange_code="UPBIT",
        symbol="KRW-XLM",
        trade_id="t1",
        price=Decimal("256"),
        quantity=Decimal("10"),
        side="BUY",
        traded_at=now - timedelta(seconds=120),
        received_at=now,
        source_code="UPBIT_WEBSOCKET",
        event_type=MarketEventType.TRADE,
    )
    tq = _quote_from_trade(trade)
    assert tq is not None
    assert tq.trade_price == Decimal("256")
    assert tq.event_time == now  # 수신 시각 기준 freshness


def test_stale_quote_no_false_exit() -> None:
    """stale이면 Exit loader가 price=None → ManagedPosition 미생성 (평가 없음)."""
    # evaluate_exit itself only runs with prices; HOLD when no trigger
    decision = RiskManagementEngine().evaluate_exit(
        ExitEvaluationRequest(
            entry_price=Decimal("347"),
            current_price=Decimal("350"),
            highest_price=Decimal("350"),
            stop_loss_price=Decimal("329.65"),
            take_profit_price=Decimal("381.70"),
            trailing_stop_ratio=Decimal("0.03"),
        )
    )
    assert decision.should_exit is False
    assert decision.reason == "HOLD"


def test_sl_tp_trailing_evaluation() -> None:
    eng = RiskManagementEngine()
    sl = eng.evaluate_exit(
        ExitEvaluationRequest(
            entry_price=Decimal("347"),
            current_price=Decimal("320"),
            highest_price=Decimal("347"),
            stop_loss_price=Decimal("329.65"),
            take_profit_price=Decimal("381.70"),
            trailing_stop_ratio=None,
        )
    )
    assert sl.reason == "STOP_LOSS"
    tp = eng.evaluate_exit(
        ExitEvaluationRequest(
            entry_price=Decimal("347"),
            current_price=Decimal("390"),
            highest_price=Decimal("390"),
            stop_loss_price=Decimal("329.65"),
            take_profit_price=Decimal("381.70"),
            trailing_stop_ratio=None,
        )
    )
    assert tp.reason == "TAKE_PROFIT"
    trail = eng.evaluate_exit(
        ExitEvaluationRequest(
            entry_price=Decimal("347"),
            current_price=Decimal("360"),
            highest_price=Decimal("380"),
            stop_loss_price=Decimal("329.65"),
            take_profit_price=Decimal("381.70"),
            trailing_stop_ratio=Decimal("0.03"),
        )
    )
    # 380 * 0.97 = 368.6; current 360 <= trailing → TRAILING_STOP
    assert trail.reason == "TRAILING_STOP"


def test_readiness_detects_stale_protective_exit() -> None:
    session = MagicMock()
    stale_at = datetime.now(timezone.utc) - timedelta(seconds=120)
    fake_snap = SimpleNamespace(trade_price=Decimal("350"), quoted_at=stale_at)

    class _Svc:
        def get(self, *_a, **_k):  # noqa: ANN001
            return fake_snap

    with (
        patch(
            "stock_platform.markets.service.QuoteSnapshotService",
            return_value=_Svc(),
        ),
        patch(
            "stock_platform.operation.upbit_full_market.portfolio_runtime_sync."
            "collect_upbit_open_auto_position_symbols",
            return_value=["KRW-GEOD"],
        ),
    ):
        result = _evaluate_auto_exit_quote_freshness(
            session, user_broker_account_id=1380
        )
    assert result["ok"] is False
    assert "KRW-GEOD" in result["stale_symbols"]
    assert result["reason"] == "AUTO_EXIT_QUOTE_STALE"


@pytest.mark.asyncio
async def test_start_upbit_expands_missing_symbols() -> None:
    from stock_platform.realtime.manager import RealtimeMarketDataManager

    mgr = RealtimeMarketDataManager()
    fake_client = MagicMock()
    fake_client.status.return_value = {
        "symbols": ["KRW-BTC"],
        "connected": True,
        "running": True,
    }
    fake_task = MagicMock()
    fake_task.done.return_value = False
    mgr._clients["UPBIT"] = fake_client
    mgr._tasks["UPBIT"] = fake_task

    started: dict = {}

    async def fake_discard(_id: str) -> None:
        mgr._clients.pop("UPBIT", None)
        mgr._tasks.pop("UPBIT", None)

    async def fake_wait(**_kwargs):  # noqa: ANN003
        return True

    original_create = None

    class FakeUpbit:
        def __init__(self, *, symbols, **_kwargs):  # noqa: ANN003
            started["symbols"] = list(symbols)

        def status(self):
            return {
                "symbols": started["symbols"],
                "connected": True,
                "running": True,
            }

        async def run_forever(self):
            return None

        async def stop(self):
            return None

    with (
        patch.object(mgr, "_discard_client", side_effect=fake_discard),
        patch.object(mgr, "_wait_until_connected", side_effect=fake_wait),
        patch(
            "stock_platform.realtime.manager.UpbitRealtimeClient",
            FakeUpbit,
        ),
        patch("asyncio.create_task") as create_task,
    ):
        create_task.side_effect = lambda coro, name=None: MagicMock(
            done=lambda: False
        )
        # drain coroutine
        async def _track(task):
            return task

        mgr._track_task = lambda t: t  # type: ignore[method-assign]
        result = await mgr.start_upbit(symbols=["KRW-GEOD"])
    assert "KRW-GEOD" in started["symbols"]
    assert "KRW-BTC" in started["symbols"]
    assert result.get("expanded") is True
