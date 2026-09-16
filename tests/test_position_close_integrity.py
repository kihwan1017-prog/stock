"""P0 position residual / dust / allocation integrity tests."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

from stock_platform.broker.upbit.rules import UPBIT_MIN_NOTIONAL_KRW
from stock_platform.risk_engine.position_close_integrity import (
    allocated_realized_from_orders,
    classify_residual_for_close,
    incremental_exit_qty,
)
from stock_platform.risk_engine.strategy_owned_entities import (
    BINDING_STATUS_CLOSED,
    BINDING_STATUS_OPEN,
    BINDING_STATUS_PARTIAL_EXIT,
    StrategyPositionBindingEntity,
)
from stock_platform.risk_engine.strategy_owned_risk_service import (
    StrategyOwnedRiskService,
)


def _svc(rows: list) -> tuple[StrategyOwnedRiskService, MagicMock]:
    session = MagicMock()

    def _scalars(stmt):  # noqa: ARG001
        # mark_position_closed가 session.add로 다른 entity를 넣어도 binding만 반환
        only = [
            r
            for r in rows
            if isinstance(r, StrategyPositionBindingEntity)
        ]
        return iter(list(only))

    session.scalars = MagicMock(side_effect=_scalars)
    session.scalar = MagicMock(return_value=None)
    session.get = MagicMock(return_value=None)
    session.add = MagicMock(side_effect=lambda r: rows.append(r))
    session.flush = MagicMock()
    return StrategyOwnedRiskService(session), session


def test_full_fill_exit_closes() -> None:
    buy = SimpleNamespace(order_id=1, filled_quantity=Decimal("10"), status_code="FILLED")
    row = StrategyPositionBindingEntity(
        binding_id=1,
        user_broker_account_id=1380,
        broker_code="UPBIT",
        strategy_id=1,
        symbol="KRW-AAA",
        status=BINDING_STATUS_OPEN,
        ownership_code="STRATEGY_OWNED",
        entry_order_id=1,
        owned_quantity=Decimal("10"),
        entry_price=Decimal("100"),
        fees=Decimal("0"),
        realized_pnl=Decimal("0"),
        opened_at=datetime.now(timezone.utc),
        meta_json={},
    )
    rows = [row]
    svc, session = _svc(rows)
    session.get = MagicMock(return_value=buy)
    out = svc.ensure_binding_from_fill(
        user_broker_account_id=1380,
        broker_code="UPBIT",
        strategy_id=1,
        deployment_id=None,
        symbol="KRW-AAA",
        entry_order_id=None,
        broker_order_id="s1",
        quantity=Decimal("10"),
        entry_price=None,
        side="SELL",
        fees=Decimal("1"),
        fill_price=Decimal("110"),
        exit_order_id=99,
    )
    assert out is row
    assert row.status == BINDING_STATUS_CLOSED
    assert Decimal(str(row.owned_quantity)) == Decimal("0")


def test_partial_sell_sellable_residual_not_closed() -> None:
    """NEAR-like: remaining value >= min notional → PARTIAL_EXIT."""
    buy = SimpleNamespace(
        order_id=2, filled_quantity=Decimal("3.44115623"), status_code="FILLED"
    )
    row = StrategyPositionBindingEntity(
        binding_id=2,
        user_broker_account_id=1380,
        broker_code="UPBIT",
        strategy_id=1,
        symbol="KRW-NEAR",
        status=BINDING_STATUS_OPEN,
        ownership_code="STRATEGY_OWNED",
        entry_order_id=2,
        owned_quantity=Decimal("3.44115623"),
        entry_price=Decimal("2906"),
        fees=Decimal("0"),
        realized_pnl=Decimal("0"),
        opened_at=datetime.now(timezone.utc),
        meta_json={},
    )
    rows = [row]
    svc, session = _svc(rows)
    session.get = MagicMock(return_value=buy)
    svc.ensure_binding_from_fill(
        user_broker_account_id=1380,
        broker_code="UPBIT",
        strategy_id=1,
        deployment_id=None,
        symbol="KRW-NEAR",
        entry_order_id=None,
        broker_order_id="s2",
        quantity=Decimal("1.82346832"),
        entry_price=None,
        side="SELL",
        fees=Decimal("1"),
        fill_price=Decimal("3240"),
        exit_order_id=2896,
    )
    # remaining ≈1.617 * 3240 ≈ 5240 >= 5000 → PARTIAL_EXIT
    assert row.status == BINDING_STATUS_PARTIAL_EXIT
    assert Decimal(str(row.owned_quantity)) > Decimal("1.6")
    assert row.meta_json.get("lifecycle_state") == "PARTIAL_EXIT"
    assert row.meta_json.get("exit_order_id") is None


def test_partial_sell_dust_closes_with_auto_dust_provenance() -> None:
    """PROM-like: remaining below min notional → CLOSED + AUTO_DUST."""
    buy = SimpleNamespace(
        order_id=3, filled_quantity=Decimal("1.45666424"), status_code="FILLED"
    )
    # 가격을 낮게 잡아 remaining notional < 5000
    row = StrategyPositionBindingEntity(
        binding_id=3,
        user_broker_account_id=1380,
        broker_code="UPBIT",
        strategy_id=1,
        symbol="KRW-PROM",
        status=BINDING_STATUS_OPEN,
        ownership_code="STRATEGY_OWNED",
        entry_order_id=3,
        owned_quantity=Decimal("1.45666424"),
        entry_price=Decimal("6865"),
        fees=Decimal("0"),
        realized_pnl=Decimal("0"),
        opened_at=datetime.now(timezone.utc),
        meta_json={},
    )
    rows = [row]
    svc, session = _svc(rows)
    session.get = MagicMock(return_value=buy)
    svc.ensure_binding_from_fill(
        user_broker_account_id=1380,
        broker_code="UPBIT",
        strategy_id=1,
        deployment_id=None,
        symbol="KRW-PROM",
        entry_order_id=None,
        broker_order_id="s3",
        quantity=Decimal("1.00377122"),
        entry_price=None,
        side="SELL",
        fees=Decimal("1"),
        fill_price=Decimal("6865"),
        exit_order_id=2776,
    )
    rem_value = Decimal("0.45289302") * Decimal("6865")
    assert rem_value < UPBIT_MIN_NOTIONAL_KRW
    assert row.status == BINDING_STATUS_CLOSED
    assert row.meta_json.get("auto_dust") is not None
    assert row.meta_json["auto_dust"]["status"] == "AUTO_DUST"
    assert Decimal(str(row.meta_json["closed_quantity"])) == Decimal("1.00377122")


def test_cumulative_sell_resync_idempotent() -> None:
    buy = SimpleNamespace(order_id=4, filled_quantity=Decimal("10"), status_code="FILLED")
    row = StrategyPositionBindingEntity(
        binding_id=4,
        user_broker_account_id=1380,
        broker_code="UPBIT",
        strategy_id=1,
        symbol="KRW-BBB",
        status=BINDING_STATUS_OPEN,
        ownership_code="STRATEGY_OWNED",
        entry_order_id=4,
        owned_quantity=Decimal("10"),
        entry_price=Decimal("100"),
        fees=Decimal("0"),
        realized_pnl=Decimal("0"),
        opened_at=datetime.now(timezone.utc),
        meta_json={},
    )
    rows = [row]
    svc, session = _svc(rows)
    session.get = MagicMock(return_value=buy)
    kwargs = dict(
        user_broker_account_id=1380,
        broker_code="UPBIT",
        strategy_id=1,
        deployment_id=None,
        symbol="KRW-BBB",
        entry_order_id=None,
        broker_order_id="s4",
        quantity=Decimal("4"),
        entry_price=None,
        side="SELL",
        fees=Decimal("0"),
        fill_price=Decimal("100"),
        exit_order_id=40,
    )
    svc.ensure_binding_from_fill(**kwargs)
    owned_after = Decimal(str(row.owned_quantity))
    svc.ensure_binding_from_fill(**kwargs)  # same cumulative
    assert Decimal(str(row.owned_quantity)) == owned_after


def test_duplicate_exit_allocation_pnl_not_double_count() -> None:
    """BCH-like: one sell covers two buys — PnL uses closed_qty ratio."""
    gross1, _ = allocated_realized_from_orders(
        buy_filled_qty=Decimal("0.02949853"),
        buy_filled_amount=Decimal("10000.00"),
        sell_filled_qty=Decimal("0.05899706"),
        sell_filled_amount=Decimal("20005.90"),
        closed_qty=Decimal("0.02949853"),
    )
    gross2, _ = allocated_realized_from_orders(
        buy_filled_qty=Decimal("0.02949853"),
        buy_filled_amount=Decimal("10000.00"),
        sell_filled_qty=Decimal("0.05899706"),
        sell_filled_amount=Decimal("20005.90"),
        closed_qty=Decimal("0.02949853"),
    )
    # 각 lot ≈ +2.95, 합 ≈ +5.9 — 예전 방식(+10005×2) 금지
    assert abs(gross1 - Decimal("2.95")) < Decimal("0.5")
    assert abs(gross1 + gross2) < Decimal("10")
    assert gross1 + gross2 < Decimal("100")


def test_classify_sellable_blocks_close() -> None:
    v = classify_residual_for_close(
        Decimal("1.61768791"), mark_price=Decimal("3240")
    )
    assert v.decision == "KEEP_PARTIAL_EXIT"
    assert v.sellable_now is True


def test_classify_dust_allows_close_with_provenance() -> None:
    v = classify_residual_for_close(
        Decimal("0.009"), mark_price=Decimal("1900")
    )
    assert v.decision == "CLOSE_AS_AUTO_DUST"
    assert v.sellable_now is False


def test_incremental_exit_qty() -> None:
    assert incremental_exit_qty(
        cumulative_fill_qty=Decimal("5"),
        already_allocated_on_binding=Decimal("5"),
    ) == Decimal("0")
    assert incremental_exit_qty(
        cumulative_fill_qty=Decimal("8"),
        already_allocated_on_binding=Decimal("5"),
    ) == Decimal("3")


def test_manual_holding_not_in_strategy_owned_loader() -> None:
    from stock_platform.risk_engine.exit_sell_quantity import (
        load_strategy_owned_open_quantity,
    )

    session = MagicMock()
    manual = StrategyPositionBindingEntity(
        binding_id=9,
        user_broker_account_id=1380,
        broker_code="UPBIT",
        strategy_id=1,
        symbol="KRW-BTC",
        status=BINDING_STATUS_OPEN,
        ownership_code="MANUAL",
        owned_quantity=Decimal("1"),
        entry_price=Decimal("1"),
        fees=Decimal("0"),
        realized_pnl=Decimal("0"),
        meta_json={},
    )
    # scalars returns empty because filter ownership=STRATEGY — mock returns []
    session.scalars = MagicMock(return_value=iter([]))
    q = load_strategy_owned_open_quantity(
        session, user_broker_account_id=1380, symbol="KRW-BTC", broker_code="UPBIT"
    )
    assert q == Decimal("0")
    del manual
