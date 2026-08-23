"""Portfolio slot ↔ AUTO order lifecycle sync (no broker calls)."""

from __future__ import annotations

import itertools
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.operation.upbit_full_market.constants import (
    SLOT_COOLDOWN,
    SLOT_ENTRY_PENDING,
    SLOT_EXIT_PENDING,
    SLOT_OPEN,
)
from stock_platform.operation.upbit_full_market.portfolio_lifecycle_sync import (
    link_entry_order_to_pending_slot,
    reconcile_portfolio_slot_lifecycle,
)
from stock_platform.operation.upbit_full_market.portfolio_service import (
    UpbitPortfolioService,
)


def _slot(
    *,
    status: str = SLOT_ENTRY_PENDING,
    symbol: str = "KRW-ETC",
    entry_order_id: int | None = None,
    binding_id: int | None = None,
) -> SimpleNamespace:
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        slot_id=7,
        slot_no=4,
        user_broker_account_id=1380,
        status=status,
        symbol=symbol,
        candidate_selection_id=99,
        entry_order_id=entry_order_id,
        position_binding_id=binding_id,
        reserved_amount_krw=10000.0,
        allocated_amount_krw=10000.0,
        opened_at=None,
        closed_at=None,
        version=10,
        created_at=now - timedelta(minutes=30),
        updated_at=now - timedelta(minutes=30),
    )


def _order(
    order_id: int,
    *,
    side: str,
    status: str,
    signal_reason: str,
    minutes_ago: float = 20,
) -> SimpleNamespace:
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        order_id=order_id,
        side_code=side,
        status_code=status,
        order_source="AUTO",
        broker_code="UPBIT",
        symbol="KRW-ETC",
        created_at=now - timedelta(minutes=minutes_ago),
        metadata_payload={"signal_reason": signal_reason, "order_source": "AUTO"},
    )


def _portfolio_assignment() -> SimpleNamespace:
    return SimpleNamespace(mode="FULL_MARKET_PORTFOLIO", strategy_id=17483)


def _scalars_cycle(session: MagicMock, slot: SimpleNamespace, orders: list) -> None:
    session.scalars = MagicMock(side_effect=itertools.cycle([[slot], orders]))


@pytest.fixture
def session() -> MagicMock:
    return MagicMock()


def test_link_entry_order_to_pending_slot(session: MagicMock) -> None:
    slot = _slot()
    session.scalar = MagicMock(return_value=slot)
    with patch(
        "stock_platform.operation.upbit_full_market.portfolio_lifecycle_sync.UpbitFullMarketAssignmentService"
    ) as fm_cls:
        fm_cls.return_value.get_or_create.return_value = _portfolio_assignment()
        out = link_entry_order_to_pending_slot(
            session,
            user_broker_account_id=1380,
            order_id=1806,
            symbol="KRW-ETC",
        )
    assert out["linked"] is True
    assert slot.entry_order_id == 1806


def test_buy_filled_transitions_entry_pending_to_open(session: MagicMock) -> None:
    slot = _slot()
    orders = [
        _order(1806, side="BUY", status="FILLED", signal_reason="PORTFOLIO_BULLISH_STATE_ENTRY"),
    ]
    _scalars_cycle(session, slot, orders)
    session.scalar = MagicMock(return_value=None)
    fm = MagicMock()
    fm.get_or_create.return_value = _portfolio_assignment()
    fm.mark_position_open.return_value = {
        "ok": True,
        "binding_id": 55,
        "slot_id": 7,
    }
    binding = SimpleNamespace(
        binding_id=55,
        status="OPEN",
        slot_id=7,
        entry_order_id=1806,
        meta_json={},
    )
    session.get = MagicMock(return_value=binding)
    with patch(
        "stock_platform.operation.upbit_full_market.portfolio_lifecycle_sync.UpbitFullMarketAssignmentService",
        return_value=fm,
    ):
        out = reconcile_portfolio_slot_lifecycle(
            session, user_broker_account_id=1380, symbol="KRW-ETC"
        )
    assert out["changed"] is True
    fm.mark_position_open.assert_called_once()


def test_buy_filled_and_sell_accepted_to_exit_pending(session: MagicMock) -> None:
    slot = _slot(status=SLOT_OPEN, entry_order_id=1806, binding_id=55)
    orders = [
        _order(1806, side="BUY", status="FILLED", signal_reason="PORTFOLIO_BULLISH_STATE_ENTRY"),
        _order(1807, side="SELL", status="ACCEPTED", signal_reason="MA_DEAD_CROSS", minutes_ago=18),
    ]
    binding = SimpleNamespace(
        binding_id=55,
        status="OPEN",
        slot_id=7,
        entry_order_id=1806,
        meta_json={},
    )
    session.scalars = MagicMock(side_effect=[[slot], orders])
    session.scalar = MagicMock(return_value=binding)
    fm = MagicMock()
    fm.get_or_create.return_value = _portfolio_assignment()
    with patch(
        "stock_platform.operation.upbit_full_market.portfolio_lifecycle_sync.UpbitFullMarketAssignmentService",
        return_value=fm,
    ):
        out = reconcile_portfolio_slot_lifecycle(
            session, user_broker_account_id=1380, symbol="KRW-ETC"
        )
    assert out["changed"] is True
    assert slot.status == SLOT_EXIT_PENDING
    assert binding.meta_json.get("exit_order_id") == 1807


def test_sell_filled_closes_slot(session: MagicMock) -> None:
    slot = _slot(status=SLOT_EXIT_PENDING, entry_order_id=1806, binding_id=55)
    orders = [
        _order(1806, side="BUY", status="FILLED", signal_reason="PORTFOLIO_BULLISH_STATE_ENTRY"),
        _order(1807, side="SELL", status="FILLED", signal_reason="MA_DEAD_CROSS", minutes_ago=15),
    ]
    binding = SimpleNamespace(
        binding_id=55,
        status="OPEN",
        slot_id=7,
        entry_order_id=1806,
        meta_json={},
    )
    session.scalars = MagicMock(side_effect=[[slot], orders])
    session.scalar = MagicMock(return_value=binding)
    fm = MagicMock()
    fm.get_or_create.return_value = _portfolio_assignment()
    fm.mark_position_closed.return_value = {"ok": True, "closed_bindings": 1}
    session.get = MagicMock(return_value=slot)
    with patch(
        "stock_platform.operation.upbit_full_market.portfolio_lifecycle_sync.UpbitFullMarketAssignmentService",
        return_value=fm,
    ):
        out = reconcile_portfolio_slot_lifecycle(
            session, user_broker_account_id=1380, symbol="KRW-ETC"
        )
    assert out["changed"] is True
    fm.mark_position_closed.assert_called_once_with(1380, symbol="KRW-ETC")


def test_restart_after_buy_filled_recovers_open(session: MagicMock) -> None:
    slot = _slot(entry_order_id=1806)
    orders = [
        _order(1806, side="BUY", status="FILLED", signal_reason="PORTFOLIO_BULLISH_STATE_ENTRY"),
    ]
    _scalars_cycle(session, slot, orders)
    session.scalar = MagicMock(return_value=None)
    fm = MagicMock()
    fm.get_or_create.return_value = _portfolio_assignment()
    fm.mark_position_open.return_value = {"ok": True, "binding_id": 1}
    session.get = MagicMock(
        return_value=SimpleNamespace(
            binding_id=1, status="OPEN", slot_id=7, entry_order_id=1806, meta_json={}
        )
    )
    with patch(
        "stock_platform.operation.upbit_full_market.portfolio_lifecycle_sync.UpbitFullMarketAssignmentService",
        return_value=fm,
    ):
        out = reconcile_portfolio_slot_lifecycle(session, user_broker_account_id=1380)
    assert out["changed"] is True


def test_restart_while_sell_accepted_exit_pending(session: MagicMock) -> None:
    slot = _slot(status=SLOT_OPEN, entry_order_id=1806, binding_id=1)
    orders = [
        _order(1806, side="BUY", status="FILLED", signal_reason="PORTFOLIO_BULLISH_STATE_ENTRY"),
        _order(1807, side="SELL", status="ACCEPTED", signal_reason="MA_DEAD_CROSS"),
    ]
    binding = SimpleNamespace(
        binding_id=1, status="OPEN", slot_id=7, entry_order_id=1806, meta_json={}
    )
    session.scalars = MagicMock(side_effect=[[slot], orders])
    session.scalar = MagicMock(return_value=binding)
    fm = MagicMock()
    fm.get_or_create.return_value = _portfolio_assignment()
    with patch(
        "stock_platform.operation.upbit_full_market.portfolio_lifecycle_sync.UpbitFullMarketAssignmentService",
        return_value=fm,
    ):
        out = reconcile_portfolio_slot_lifecycle(session, user_broker_account_id=1380)
    assert slot.status == SLOT_EXIT_PENDING


def test_stale_entry_pending_with_filled_buy_reconciles_not_release() -> None:
    slot = _slot()
    session = MagicMock()
    session.scalars = MagicMock(return_value=[slot])
    session.scalar = MagicMock(return_value=0)
    svc = UpbitPortfolioService(session)
    assignment = SimpleNamespace(
        mode="FULL_MARKET_PORTFOLIO", current_symbol="KRW-ETC", signals_paused=False, state="IDLE"
    )
    svc._assignment = MagicMock()
    svc._assignment.get_or_create = MagicMock(return_value=assignment)
    with patch(
        "stock_platform.operation.upbit_full_market.portfolio_lifecycle_sync.reconcile_portfolio_slot_lifecycle",
        return_value={"ok": True, "changed": True, "transitions": [{"to": SLOT_OPEN}]},
    ):
        svc._has_local_open_order = MagicMock(return_value=True)  # type: ignore[method-assign]
        out = svc.recover_stale_entry_pending_without_order(1380, timeout_seconds=120)
    assert out["released"] == 0
    assert any(b.get("reason") == "LIFECYCLE_RECONCILED" for b in out["blocked"])


def test_stale_entry_pending_with_open_sell_reconciles(session: MagicMock) -> None:
    slot = _slot()
    orders = [
        _order(1806, side="BUY", status="FILLED", signal_reason="PORTFOLIO_BULLISH_STATE_ENTRY"),
        _order(1807, side="SELL", status="ACCEPTED", signal_reason="MA_DEAD_CROSS"),
    ]
    _scalars_cycle(session, slot, orders)
    session.scalar = MagicMock(return_value=None)
    fm = MagicMock()
    fm.get_or_create.return_value = _portfolio_assignment()
    fm.mark_position_open.return_value = {"ok": True, "binding_id": 2}
    binding = SimpleNamespace(
        binding_id=2, status="OPEN", slot_id=7, entry_order_id=1806, meta_json={}
    )

    def _get(model, pk):  # noqa: ANN001
        if pk == 2:
            return binding
        return slot

    session.get = MagicMock(side_effect=_get)
    with patch(
        "stock_platform.operation.upbit_full_market.portfolio_lifecycle_sync.UpbitFullMarketAssignmentService",
        return_value=fm,
    ):
        out = reconcile_portfolio_slot_lifecycle(session, user_broker_account_id=1380)
    assert out["changed"] is True
    assert slot.status == SLOT_EXIT_PENDING


def test_duplicate_reconcile_idempotent(session: MagicMock) -> None:
    slot = _slot(status=SLOT_EXIT_PENDING, entry_order_id=1806, binding_id=3)
    orders = [
        _order(1806, side="BUY", status="FILLED", signal_reason="PORTFOLIO_BULLISH_STATE_ENTRY"),
        _order(1807, side="SELL", status="ACCEPTED", signal_reason="MA_DEAD_CROSS"),
    ]
    binding = SimpleNamespace(
        binding_id=3,
        status="OPEN",
        slot_id=7,
        entry_order_id=1806,
        meta_json={"exit_order_id": 1807},
    )
    session.scalars = MagicMock(side_effect=itertools.cycle([[slot], orders]))
    session.scalar = MagicMock(return_value=binding)
    fm = MagicMock()
    fm.get_or_create.return_value = _portfolio_assignment()
    with patch(
        "stock_platform.operation.upbit_full_market.portfolio_lifecycle_sync.UpbitFullMarketAssignmentService",
        return_value=fm,
    ):
        out1 = reconcile_portfolio_slot_lifecycle(session, user_broker_account_id=1380)
        out2 = reconcile_portfolio_slot_lifecycle(session, user_broker_account_id=1380)
    assert out1.get("changed") in {True, False}
    assert out2["changed"] is False
    fm.mark_position_open.assert_not_called()
    fm.mark_position_closed.assert_not_called()


def test_manual_symbol_unaffected(session: MagicMock) -> None:
    """MANUAL 주문은 AUTO 필터로 reconcile 대상 아님."""
    slot = _slot(symbol="KRW-BTC")
    session.scalars = MagicMock(side_effect=[[slot], []])
    fm = MagicMock()
    fm.get_or_create.return_value = _portfolio_assignment()
    with patch(
        "stock_platform.operation.upbit_full_market.portfolio_lifecycle_sync.UpbitFullMarketAssignmentService",
        return_value=fm,
    ):
        out = reconcile_portfolio_slot_lifecycle(
            session, user_broker_account_id=1380, symbol="KRW-BTC"
        )
    assert out["changed"] is False
    fm.mark_position_open.assert_not_called()


def test_no_duplicate_sell_creation(session: MagicMock) -> None:
    """reconcile은 주문을 생성하지 않음."""
    slot = _slot(status=SLOT_OPEN, entry_order_id=1806)
    orders = [
        _order(1807, side="SELL", status="ACCEPTED", signal_reason="MA_DEAD_CROSS"),
    ]
    binding = SimpleNamespace(
        binding_id=4, status="OPEN", slot_id=7, entry_order_id=1806, meta_json={}
    )
    session.scalars = MagicMock(side_effect=[[slot], orders])
    session.scalar = MagicMock(return_value=binding)
    fm = MagicMock()
    fm.get_or_create.return_value = _portfolio_assignment()
    with patch(
        "stock_platform.operation.upbit_full_market.portfolio_lifecycle_sync.UpbitFullMarketAssignmentService",
        return_value=fm,
    ):
        out = reconcile_portfolio_slot_lifecycle(session, user_broker_account_id=1380)
    assert out["orders_created"] == 0
