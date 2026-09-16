# -*- coding: utf-8 -*-
"""CONTROLLED_AUTO_RESIDUAL_CLEANUP focused tests (P3-C)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from stock_platform.broker.upbit.rules import UPBIT_MIN_NOTIONAL_KRW
from stock_platform.operation.upbit_auto_residual_cleanup.constants import (
    ARCHITECTURE,
    KIND_CURRENT_DUST,
    KIND_CURRENT_RESIDUAL,
    KIND_HISTORICAL_ONLY,
    KIND_SELLABLE_CURRENT,
    REASON_AMBIGUOUS_ORDER,
    REASON_APPROVAL_REQUIRED,
    REASON_BELOW_MIN_NOTIONAL,
    REASON_HISTORICAL_ONLY_BLOCKED,
    REASON_IDEMPOTENCY_BLOCK,
    REASON_KILL_SWITCH,
    REASON_MANUAL_CONTAMINATION,
    REASON_MANUAL_PROTECTED,
    REASON_OPEN_SELL_CONFLICT,
    REASON_QTY_EXCEEDS_ATTRIBUTABLE,
    REASON_UNSELLABLE_AUTO_DUST,
    STATUS_AMBIGUOUS,
    STATUS_FILLED,
    STATUS_PARTIAL_FILLED,
)
from stock_platform.operation.upbit_auto_residual_cleanup.eligibility import (
    ResidualCleanupContext,
    evaluate_eligibility,
)
from stock_platform.operation.upbit_auto_residual_cleanup.lifecycle import (
    apply_verified_fill_to_residual,
)
from stock_platform.operation.upbit_auto_residual_cleanup.quantity import (
    resolve_cleanup_sell_quantity,
)
from stock_platform.operation.upbit_auto_residual_cleanup.service import (
    ProductionBrokerSubmitDisabled,
    apply_cleanup,
    assert_architecture_invariants,
    prepare_cleanup,
    preview_cleanup,
)


def _truth(
    kind: str,
    *,
    owned: str,
    binding_id: int = 1,
    sellable: bool = False,
) -> dict:
    return {
        "kind": kind,
        "binding_id": binding_id,
        "owned_qty": owned,
        "historical_remaining_qty": owned,
        "sellable": sellable,
        "current_balance_match": True,
    }


def _ctx(
    *,
    binding_id: int = 537,
    symbol: str = "KRW-NEAR",
    kind: str = KIND_SELLABLE_CURRENT,
    owned: str = "1.61768791",
    broker_qty: str = "1.61768791",
    price: str = "3215",
    **kwargs,
) -> ResidualCleanupContext:
    base = dict(
        uba_id=1380,
        binding_id=binding_id,
        broker_code="UPBIT",
        symbol=symbol,
        binding_status="CLOSED",
        ownership_code="STRATEGY_OWNED",
        truth=_truth(kind, owned=owned, binding_id=binding_id, sellable=True),
        broker_qty=Decimal(broker_qty),
        mark_price=Decimal(price),
        kill_switch_active=False,
        has_ambiguous_order=False,
        has_unresolved_exit=False,
        has_recovery_conflict=False,
        broker_account_ready=True,
        credential_ready=True,
        existing_open_sell_qty=Decimal("0"),
        existing_cleanup_request_status=None,
        manual_contamination=False,
        ownership_confidence="HIGH",
        same_symbol_other_current_qty=Decimal("0"),
    )
    base.update(kwargs)
    return ResidualCleanupContext(**base)


# 1. NEAR #537 sellable preview
def test_near_537_sellable_preview() -> None:
    r = preview_cleanup(_ctx())
    assert r.eligible is True
    assert r.eligible_qty == Decimal("1.61768791")
    assert r.estimated_notional is not None
    assert r.estimated_notional >= UPBIT_MIN_NOTIONAL_KRW
    assert r.broker_submit is False


# 2. CLOSED binding을 reopen하지 않음
def test_closed_binding_not_reopened() -> None:
    plan = prepare_cleanup(_ctx())
    assert plan.binding_status_mutated is False
    assert ARCHITECTURE["closed_binding_reopened"] is False
    assert plan.eligibility.expected_post_cleanup_state["binding_status_unchanged"] is True


# 3. preview에서 broker order 0
def test_preview_broker_submit_false() -> None:
    r = preview_cleanup(_ctx())
    assert r.broker_submit is False
    out = apply_cleanup(_ctx(), approval_token="OP_OK", broker_submit=False)
    assert out["order_created"] is False
    assert out["broker_submit"] is False


# 4–5. historical-only #145 / #207 금지
@pytest.mark.parametrize("binding_id,owned", [(145, "0.17146188"), (207, "0.00875321")])
def test_historical_only_blocked(binding_id: int, owned: str) -> None:
    truth = {
        "kind": KIND_HISTORICAL_ONLY,
        "binding_id": binding_id,
        "historical_remaining_qty": owned,
        "current_owned_qty": "0",
        "broker_current_qty": "0",
    }
    r = evaluate_eligibility(
        _ctx(
            binding_id=binding_id,
            symbol="KRW-GRVT" if binding_id == 145 else "KRW-TRUMP",
            broker_qty="1.50573694" if binding_id == 207 else "0",
            price="100",
            truth=truth,
        )
    )
    assert r.eligible is False
    assert r.reason == REASON_HISTORICAL_ONLY_BLOCKED
    assert resolve_cleanup_sell_quantity(truth=truth, broker_qty=Decimal("9")) == 0


# 6. TRUMP #240 only — #207 double-count 금지
def test_trump_no_double_count() -> None:
    truth_240 = _truth(KIND_CURRENT_RESIDUAL, owned="1.50573694", binding_id=240)
    # broker = #240 exact; #207 historical 합치면 1.51449015 — 절대 안 됨
    qty = resolve_cleanup_sell_quantity(
        truth=truth_240,
        broker_qty=Decimal("1.50573694"),
        same_symbol_other_current_qty=Decimal("0"),
    )
    assert qty == Decimal("1.50573694")
    assert qty != Decimal("1.51449015")
    # historical #207을 other로 넣어도 CURRENT에 가산하지 않음(caller 책임) —
    # other에 잘못 넣으면 차감되므로 여전히 1.505를 넘지 않음
    qty2 = resolve_cleanup_sell_quantity(
        truth=truth_240,
        broker_qty=Decimal("1.50573694"),
        same_symbol_other_current_qty=Decimal("0.00875321"),
    )
    assert qty2 < Decimal("1.50573694")
    assert qty2 != Decimal("1.51449015")


# 7. PROM below min notional
def test_prom_below_min_notional() -> None:
    r = preview_cleanup(
        _ctx(
            binding_id=480,
            symbol="KRW-PROM",
            kind=KIND_CURRENT_RESIDUAL,
            owned="0.45289302",
            broker_qty="0.45289302",
            price="7700",  # ~3490 KRW
        )
    )
    assert r.eligible is False
    assert r.reason == REASON_BELOW_MIN_NOTIONAL


# 8–9. XRP / WLD dust
@pytest.mark.parametrize(
    "binding_id,symbol,owned,price",
    [
        (118, "KRW-XRP", "0.00938817", "1900"),
        (165, "KRW-WLD", "0.00000004", "3000"),
    ],
)
def test_dust_blocked(
    binding_id: int, symbol: str, owned: str, price: str
) -> None:
    r = preview_cleanup(
        _ctx(
            binding_id=binding_id,
            symbol=symbol,
            kind=KIND_CURRENT_DUST,
            owned=owned,
            broker_qty=owned,
            price=price,
        )
    )
    assert r.eligible is False
    assert r.reason == REASON_UNSELLABLE_AUTO_DUST


# 10. manual protection (BTC/ETH/DOGE/SKY + contamination)
def test_manual_protected_symbols() -> None:
    for sym in ("KRW-BTC", "KRW-ETH", "KRW-DOGE", "KRW-SKY"):
        r = preview_cleanup(_ctx(symbol=sym, broker_qty="1", price="100000"))
        assert r.eligible is False
        assert r.reason == REASON_MANUAL_PROTECTED


def test_same_symbol_manual_auto_contamination() -> None:
    r = preview_cleanup(_ctx(manual_contamination=True))
    assert r.eligible is False
    assert r.reason == REASON_MANUAL_CONTAMINATION


# 11. existing open SELL conflict
def test_existing_open_sell_conflict() -> None:
    r = preview_cleanup(_ctx(existing_open_sell_qty=Decimal("0.5")))
    assert r.eligible is False
    assert r.reason == REASON_OPEN_SELL_CONFLICT


# 12. AMBIGUOUS cleanup 차단
def test_ambiguous_blocks() -> None:
    r = preview_cleanup(_ctx(has_ambiguous_order=True))
    assert r.eligible is False
    assert r.reason == REASON_AMBIGUOUS_ORDER
    life = apply_verified_fill_to_residual(
        previous_residual_qty=Decimal("1.6"),
        verified_executed_qty=Decimal("0"),
        mark_price=Decimal("3200"),
        request_status=STATUS_AMBIGUOUS,
    )
    assert life["additional_sell_allowed"] is False
    assert life["residual_qty"] == "1.6"


# 13. zero-fill residual unchanged
def test_zero_fill_residual_unchanged() -> None:
    life = apply_verified_fill_to_residual(
        previous_residual_qty=Decimal("1.61768791"),
        verified_executed_qty=Decimal("0"),
        mark_price=Decimal("3200"),
        request_status=STATUS_FILLED,
    )
    assert life["residual_qty"] == "1.61768791"
    assert life["cleared"] is False


# 14. partial-fill remaining qty
def test_partial_fill_remaining() -> None:
    life = apply_verified_fill_to_residual(
        previous_residual_qty=Decimal("1.61768791"),
        verified_executed_qty=Decimal("0.60000000"),
        mark_price=Decimal("3200"),
        request_status=STATUS_PARTIAL_FILLED,
    )
    assert Decimal(life["residual_qty"]) == Decimal("1.01768791")
    assert life["cleared"] is False


# 15. idempotent duplicate submit 차단
def test_idempotent_duplicate_submit_blocked() -> None:
    out = apply_cleanup(
        _ctx(),
        approval_token="OP_OK",
        broker_submit=False,
        prior_request_status="SUBMITTED",
    )
    assert out["ok"] is False
    assert out["reason"] == REASON_IDEMPOTENCY_BLOCK


# 16. kill switch 차단
def test_kill_switch_blocks() -> None:
    r = preview_cleanup(_ctx(kill_switch_active=True))
    assert r.eligible is False
    assert r.reason == REASON_KILL_SWITCH


# 17. broker qty < provenance → broker attributable만
def test_broker_qty_caps_sell() -> None:
    r = preview_cleanup(
        _ctx(broker_qty="1.00000000", owned="1.61768791", price="6000")
    )
    assert r.eligible is True
    assert r.eligible_qty == Decimal("1.00000000")
    out = apply_cleanup(
        _ctx(broker_qty="1.00000000", owned="1.61768791", price="6000"),
        approval_token="OP_OK",
        broker_submit=False,
        requested_qty=Decimal("1.50000000"),
    )
    assert out["ok"] is False
    assert out["reason"] == REASON_QTY_EXCEEDS_ATTRIBUTABLE


# 18–20. architecture: no slot / no exit supervisor / no unattended
def test_architecture_no_slot_exit_unattended() -> None:
    inv = assert_architecture_invariants()
    assert inv["uses_auto_slot"] is True  # assertion that flag is False → returns True
    assert inv["uses_normal_exit_supervisor"] is True
    assert inv["unattended_auto_submit"] is True
    assert inv["requires_explicit_approval"] is True
    assert inv["closed_binding_reopened"] is True
    plan = prepare_cleanup(_ctx())
    assert plan.uses_auto_slot is False
    assert plan.enrolled_in_exit_supervisor is False
    assert plan.approval_required is True


def test_apply_requires_approval() -> None:
    out = apply_cleanup(_ctx(), approval_token=None, broker_submit=False)
    assert out["ok"] is False
    assert out["reason"] == REASON_APPROVAL_REQUIRED


def test_apply_broker_submit_requires_port() -> None:
    with pytest.raises(ProductionBrokerSubmitDisabled):
        apply_cleanup(_ctx(), approval_token="OP_OK", broker_submit=True, order_port=None)


def test_apply_mock_port_once() -> None:
    calls: list[dict] = []

    class Port:
        def submit_market_sell(self, **kwargs):
            calls.append(kwargs)
            return {"status": "MOCK_ACCEPTED"}

    out = apply_cleanup(
        _ctx(),
        approval_token="OP_OK",
        broker_submit=True,
        order_port=Port(),
    )
    assert out["order_created"] is True
    assert len(calls) == 1
    assert calls[0]["quantity"] == Decimal("1.61768791")
