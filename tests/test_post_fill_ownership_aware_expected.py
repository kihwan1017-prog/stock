# -*- coding: utf-8 -*-
"""Post-fill ownership-aware expected + cleanup re-entry regression tests."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

from stock_platform.order.post_fill_runner import PostFillVerifyRunner
from stock_platform.order.post_fill_verifier import PostFillBalanceVerifier
from stock_platform.risk_engine.strategy_owned_entities import (
    BINDING_STATUS_CLOSED,
    BINDING_STATUS_OPEN,
    StrategyPositionBindingEntity,
)


def _binding(
    *,
    binding_id: int,
    status: str,
    owned: str,
    entry_order_id: int | None,
    truth_kind: str | None = None,
) -> StrategyPositionBindingEntity:
    meta = {}
    if truth_kind:
        meta["auto_residual_truth"] = {
            "kind": truth_kind,
            "cleanup": {"final_remaining_qty": "0", "state": "CLEARED"},
        }
    return StrategyPositionBindingEntity(
        binding_id=binding_id,
        user_broker_account_id=1380,
        broker_code="UPBIT",
        strategy_id=1,
        symbol="KRW-NEAR",
        status=status,
        ownership_code="STRATEGY_OWNED",
        entry_order_id=entry_order_id,
        owned_quantity=Decimal(owned),
        entry_price=Decimal("3000"),
        fees=Decimal("0"),
        realized_pnl=Decimal("0"),
        opened_at=datetime.now(timezone.utc),
        meta_json=meta,
    )


def test_cleanup_cleared_contributes_zero_new_binding_owns_new_qty() -> None:
    """same-symbol cleanup→new AUTO re-entry: old #537 = 0, new = fill qty."""

    old = _binding(
        binding_id=537,
        status=BINDING_STATUS_CLOSED,
        owned="0",
        entry_order_id=2895,
        truth_kind="CLEARED_VIA_CONTROLLED_CLEANUP",
    )
    new = _binding(
        binding_id=659,
        status=BINDING_STATUS_OPEN,
        owned="3.16455696",
        entry_order_id=3143,
    )
    session = MagicMock()
    session.scalars = MagicMock(return_value=iter([new]))  # CLOSED 제외 쿼리
    session.get = MagicMock(return_value=None)
    runner = PostFillVerifyRunner(session)
    expected = runner.build_expected_positions_from_orders(
        user_broker_account_id=1380,
        symbol="KRW-NEAR",
        seed_order_id=3143,
    )
    assert len(expected) == 1
    assert expected[0]["quantity"] == "3.16455696"
    # legacy order-net would be 4.78224487 — ownership path must not
    assert expected[0]["quantity"] != "4.78224487"
    assert old.status == BINDING_STATUS_CLOSED  # retained for clarity


def test_manual_excess_does_not_false_mismatch() -> None:
    verifier = PostFillBalanceVerifier(MagicMock())
    result = verifier.verify(
        user_broker_account_id=1380,
        user_id=1,
        broker_code="UPBIT",
        broker_positions=[{"symbol": "KRW-BTC", "quantity": "1.5"}],
        broker_cash=None,
        db_positions=[
            {
                "symbol": "KRW-BTC",
                "quantity": "0.5",
                "source": "STRATEGY_OWNED_OPEN_BINDINGS",
            }
        ],
        db_cash=None,
        activate_kill_on_mismatch=False,
    )
    assert result.ok is True


def test_broker_shortfall_still_mismatch() -> None:
    verifier = PostFillBalanceVerifier(MagicMock())
    result = verifier.verify(
        user_broker_account_id=1380,
        user_id=1,
        broker_code="UPBIT",
        broker_positions=[{"symbol": "KRW-NEAR", "quantity": "3.16455696"}],
        broker_cash=None,
        db_positions=[{"symbol": "KRW-NEAR", "quantity": "4.78224487"}],
        db_cash=None,
        activate_kill_on_mismatch=False,
    )
    assert result.ok is False
    assert result.reason_code == "POSITION_MISMATCH"
    assert result.detail.get("difference") == str(
        Decimal("3.16455696") - Decimal("4.78224487")
    )
    assert "tolerance" in result.detail


def test_exact_ownership_match_pass() -> None:
    verifier = PostFillBalanceVerifier(MagicMock())
    result = verifier.verify(
        user_broker_account_id=1380,
        user_id=1,
        broker_code="UPBIT",
        broker_positions=[{"symbol": "KRW-NEAR", "quantity": "3.16455696"}],
        broker_cash=None,
        db_positions=[{"symbol": "KRW-NEAR", "quantity": "3.16455696"}],
        db_cash=None,
        activate_kill_on_mismatch=False,
    )
    assert result.ok is True


def test_seed_order_fill_before_binding_race() -> None:
    session = MagicMock()
    session.scalars = MagicMock(return_value=iter([]))  # binding not yet
    order = SimpleNamespace(
        order_id=3143,
        symbol="KRW-NEAR",
        side_code="BUY",
        status_code="FILLED",
        filled_quantity=Decimal("3.16455696"),
    )
    session.get = MagicMock(return_value=order)
    runner = PostFillVerifyRunner(session)
    expected = runner.build_expected_positions_from_orders(
        user_broker_account_id=1380,
        symbol="KRW-NEAR",
        seed_order_id=3143,
    )
    assert expected[0]["quantity"] == "3.16455696"
