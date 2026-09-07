# -*- coding: utf-8 -*-
"""Production APPLY focused tests — P3-C regression 포함 확장."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from stock_platform.operation.upbit_auto_residual_cleanup.approval import (
    ApprovalError,
    issue_cleanup_approval,
    preview_result_hash,
    validate_approval,
)
from stock_platform.operation.upbit_auto_residual_cleanup.constants import (
    KIND_CURRENT_DUST,
    KIND_CURRENT_RESIDUAL,
    KIND_HISTORICAL_ONLY,
    KIND_SELLABLE_CURRENT,
    STATUS_AMBIGUOUS,
    STATUS_FILLED,
    STATUS_PARTIAL_FILLED,
    STATUS_SUBMITTED,
)
from stock_platform.operation.upbit_auto_residual_cleanup.eligibility import (
    ResidualCleanupContext,
)
from stock_platform.operation.upbit_auto_residual_cleanup.production_apply import (
    SOURCE_OPERATOR_EXPLICIT,
    SOURCE_UNATTENDED,
    classify_remote_fill,
    create_operator_approval,
    execute_production_cleanup,
    ProductionApplyBlocked,
)
from stock_platform.operation.upbit_auto_residual_cleanup.service import preview_cleanup
from stock_platform.risk_engine.strategy_owned_entities import (
    StrategyPositionBindingEntity,
)


def _truth(kind: str, owned: str, binding_id: int = 537) -> dict:
    return {
        "kind": kind,
        "binding_id": binding_id,
        "owned_qty": owned,
        "historical_remaining_qty": owned,
        "sellable": kind == KIND_SELLABLE_CURRENT,
        "current_balance_match": True,
    }


def _ctx(**kwargs) -> ResidualCleanupContext:
    base = dict(
        uba_id=1380,
        binding_id=537,
        broker_code="UPBIT",
        symbol="KRW-NEAR",
        binding_status="CLOSED",
        ownership_code="STRATEGY_OWNED",
        truth=_truth(KIND_SELLABLE_CURRENT, "1.61768791"),
        broker_qty=Decimal("1.61768791"),
        mark_price=Decimal("3215"),
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


def _binding_entity(meta=None) -> StrategyPositionBindingEntity:
    return StrategyPositionBindingEntity(
        binding_id=537,
        user_broker_account_id=1380,
        broker_code="UPBIT",
        strategy_id=1,
        symbol="KRW-NEAR",
        status="CLOSED",
        ownership_code="STRATEGY_OWNED",
        entry_order_id=1,
        owned_quantity=Decimal("0"),
        entry_price=Decimal("1"),
        fees=Decimal("0"),
        realized_pnl=Decimal("0"),
        opened_at=datetime.now(timezone.utc),
        meta_json=meta or {"auto_residual_truth": _truth(KIND_SELLABLE_CURRENT, "1.61768791")},
    )


class _MockPort:
    def __init__(self, responses=None):
        self.calls = []
        self._responses = list(responses or [])
        self.remote = {
            "state": "done",
            "executed_volume": "1.61768791",
            "remaining_volume": "0",
            "paid_fee": "2.5",
            "uuid": "mock-uuid",
        }

    def submit_market_sell(self, **kwargs):
        self.calls.append(kwargs)
        if self._responses:
            return self._responses.pop(0)
        return {
            "accepted": True,
            "ambiguous": False,
            "status": "ACCEPTED",
            "broker_order_id": "mock-uuid",
            "identifier": "CRCMOCK",
            "submitted_at": datetime.now(timezone.utc).isoformat(),
        }

    def get_order(self, **kwargs):
        return dict(self.remote)


def _session_with_binding(entity):
    session = MagicMock()
    session.get = MagicMock(return_value=entity)
    session.flush = MagicMock()
    session.commit = MagicMock()
    session.rollback = MagicMock()
    return session


def test_approval_missing_blocked():
    ctx = _ctx()
    elig = preview_cleanup(ctx)
    with pytest.raises(Exception):
        issue_cleanup_approval(
            uba_id=1380,
            binding_id=537,
            symbol="KRW-NEAR",
            truth=ctx.truth,
            elig=elig,
            operator_intent="",
        )


def test_approval_expired_blocked():
    ctx = _ctx()
    appr = create_operator_approval(ctx, operator_intent="NEAR_CLEANUP_ONCE")
    appr.expires_at = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    elig = preview_cleanup(ctx)
    with pytest.raises(ApprovalError, match="EXPIRED"):
        validate_approval(
            appr,
            secret=appr.secret,
            uba_id=1380,
            binding_id=537,
            symbol="KRW-NEAR",
            truth=ctx.truth,
            elig=elig,
        )


def test_preview_hash_changed_blocked():
    ctx = _ctx()
    appr = create_operator_approval(ctx, operator_intent="NEAR_CLEANUP_ONCE")
    # price change → preview hash change
    ctx2 = _ctx(mark_price=Decimal("4000"))
    elig2 = preview_cleanup(ctx2)
    with pytest.raises(ApprovalError, match="PREVIEW_HASH"):
        validate_approval(
            appr,
            secret=appr.secret,
            uba_id=1380,
            binding_id=537,
            symbol="KRW-NEAR",
            truth=ctx2.truth,
            elig=elig2,
        )


def test_broker_qty_changed_revalidate_blocks_or_hash():
    ctx = _ctx()
    appr = create_operator_approval(ctx, operator_intent="NEAR_CLEANUP_ONCE")
    ctx2 = _ctx(broker_qty=Decimal("1.00000000"), mark_price=Decimal("6000"))
    elig2 = preview_cleanup(ctx2)
    assert elig2.eligible is True
    with pytest.raises(ApprovalError):
        validate_approval(
            appr,
            secret=appr.secret,
            uba_id=1380,
            binding_id=537,
            symbol="KRW-NEAR",
            truth=ctx2.truth,
            elig=elig2,
        )


def test_price_drop_below_min_blocked():
    r = preview_cleanup(_ctx(mark_price=Decimal("2000")))
    assert r.eligible is False


def test_open_sell_after_preview_blocked():
    r = preview_cleanup(_ctx(existing_open_sell_qty=Decimal("0.1")))
    assert r.eligible is False


def test_kill_switch_after_preview_blocked():
    assert preview_cleanup(_ctx(kill_switch_active=True)).eligible is False


def test_ambiguous_after_preview_blocked():
    assert preview_cleanup(_ctx(has_ambiguous_order=True)).eligible is False


def test_duplicate_approval_consume():
    ctx = _ctx()
    entity = _binding_entity()
    session = _session_with_binding(entity)
    port = _MockPort()
    appr = create_operator_approval(ctx, operator_intent="NEAR_CLEANUP_ONCE")
    out1 = execute_production_cleanup(
        session,
        ctx=ctx,
        approval=appr,
        approval_secret=appr.secret,
        order_port=port,
        source=SOURCE_OPERATOR_EXPLICIT,
        allowed_binding_ids=frozenset({537}),
    )
    assert out1["order_created"] is True
    assert appr.consumed is True
    # second with same approval
    out2 = execute_production_cleanup(
        session,
        ctx=ctx,
        approval=appr,
        approval_secret=appr.secret,
        order_port=port,
        source=SOURCE_OPERATOR_EXPLICIT,
        allowed_binding_ids=frozenset({537}),
    )
    assert out2["ok"] is False
    assert "CONSUMED" in str(out2["reason"]) or "BLOCK" in str(out2["reason"])


def test_duplicate_idempotency_prior_submitted():
    ctx = _ctx()
    entity = _binding_entity(
        {
            "auto_residual_truth": _truth(KIND_SELLABLE_CURRENT, "1.61768791"),
            "controlled_cleanup_intent": {"status": STATUS_SUBMITTED},
        }
    )
    session = _session_with_binding(entity)
    appr = create_operator_approval(ctx, operator_intent="NEAR_CLEANUP_ONCE")
    out = execute_production_cleanup(
        session,
        ctx=ctx,
        approval=appr,
        approval_secret=appr.secret,
        order_port=_MockPort(),
        source=SOURCE_OPERATOR_EXPLICIT,
        allowed_binding_ids=frozenset({537}),
    )
    assert out["ok"] is False
    assert out["reason"] == "EXISTING_CLEANUP_REQUEST_BLOCK"


def test_submit_exactly_once():
    ctx = _ctx()
    session = _session_with_binding(_binding_entity())
    port = _MockPort()
    appr = create_operator_approval(ctx, operator_intent="NEAR_CLEANUP_ONCE")
    execute_production_cleanup(
        session,
        ctx=ctx,
        approval=appr,
        approval_secret=appr.secret,
        order_port=port,
        source=SOURCE_OPERATOR_EXPLICIT,
        allowed_binding_ids=frozenset({537}),
    )
    assert len(port.calls) == 1


def test_zero_fill_residual_unchanged_classify():
    out = classify_remote_fill(
        previous_residual_qty=Decimal("1.61768791"),
        remote={"state": "done", "executed_volume": "0", "remaining_volume": "1.61768791"},
        mark_price=Decimal("3200"),
    )
    assert out["final_state"] == "ZERO_FILL"
    assert out["remaining_qty"] == "1.61768791"


def test_partial_fill_residual_correct():
    out = classify_remote_fill(
        previous_residual_qty=Decimal("1.61768791"),
        remote={"state": "done", "executed_volume": "0.6", "remaining_volume": "1.01768791"},
        mark_price=Decimal("3200"),
    )
    assert out["final_state"] == STATUS_PARTIAL_FILLED
    assert Decimal(out["remaining_qty"]) == Decimal("1.01768791")


def test_filled_residual_correct():
    out = classify_remote_fill(
        previous_residual_qty=Decimal("1.61768791"),
        remote={"state": "done", "executed_volume": "1.61768791", "remaining_volume": "0"},
        mark_price=Decimal("3200"),
    )
    assert out["final_state"] == STATUS_FILLED
    assert out["remaining_qty"] == "0"


def test_broker_persist_failure_ambiguous():
    ctx = _ctx()
    session = _session_with_binding(_binding_entity())
    appr = create_operator_approval(ctx, operator_intent="NEAR_CLEANUP_ONCE")
    out = execute_production_cleanup(
        session,
        ctx=ctx,
        approval=appr,
        approval_secret=appr.secret,
        order_port=_MockPort(),
        source=SOURCE_OPERATOR_EXPLICIT,
        allowed_binding_ids=frozenset({537}),
        simulate_persist_failure_after_broker=True,
    )
    assert out["final_state"] == STATUS_AMBIGUOUS
    assert out["order_created"] is True


@pytest.mark.parametrize("bid,kind", [(145, KIND_HISTORICAL_ONLY), (207, KIND_HISTORICAL_ONLY)])
def test_historical_only_apply_blocked(bid, kind):
    truth = {
        "kind": kind,
        "binding_id": bid,
        "historical_remaining_qty": "0.1",
        "current_owned_qty": "0",
    }
    ctx = _ctx(binding_id=bid, truth=truth, broker_qty=Decimal("0"), symbol="KRW-GRVT")
    assert preview_cleanup(ctx).eligible is False


def test_prom_trump_dust_blocked_for_apply():
    assert preview_cleanup(
        _ctx(
            binding_id=480,
            symbol="KRW-PROM",
            truth=_truth(KIND_CURRENT_RESIDUAL, "0.45", 480),
            broker_qty=Decimal("0.45"),
            mark_price=Decimal("7000"),
        )
    ).eligible is False
    assert preview_cleanup(
        _ctx(
            binding_id=118,
            symbol="KRW-XRP",
            truth=_truth(KIND_CURRENT_DUST, "0.009", 118),
            broker_qty=Decimal("0.009"),
            mark_price=Decimal("1900"),
        )
    ).eligible is False


def test_manual_protected_and_architecture():
    assert preview_cleanup(_ctx(symbol="KRW-BTC")).eligible is False
    assert preview_cleanup(_ctx(manual_contamination=True)).eligible is False


def test_unattended_cannot_invoke_production_submit():
    ctx = _ctx()
    session = _session_with_binding(_binding_entity())
    appr = create_operator_approval(ctx, operator_intent="NEAR_CLEANUP_ONCE")
    with pytest.raises(ProductionApplyBlocked, match="UNATTENDED"):
        execute_production_cleanup(
            session,
            ctx=ctx,
            approval=appr,
            approval_secret=appr.secret,
            order_port=_MockPort(),
            source=SOURCE_UNATTENDED,
            allowed_binding_ids=frozenset({537}),
        )


def test_allowlist_blocks_non_near():
    ctx = _ctx(binding_id=480, symbol="KRW-PROM")
    # force sellable-looking but allowlist rejects
    ctx = _ctx(
        binding_id=480,
        symbol="KRW-PROM",
        truth=_truth(KIND_SELLABLE_CURRENT, "1.0", 480),
        broker_qty=Decimal("1.0"),
        mark_price=Decimal("6000"),
    )
    session = _session_with_binding(
        StrategyPositionBindingEntity(
            binding_id=480,
            user_broker_account_id=1380,
            broker_code="UPBIT",
            strategy_id=1,
            symbol="KRW-PROM",
            status="CLOSED",
            ownership_code="STRATEGY_OWNED",
            entry_order_id=1,
            owned_quantity=Decimal("0"),
            entry_price=Decimal("1"),
            fees=Decimal("0"),
            realized_pnl=Decimal("0"),
            opened_at=datetime.now(timezone.utc),
            meta_json={"auto_residual_truth": ctx.truth},
        )
    )
    appr = create_operator_approval(ctx, operator_intent="NOPE")
    out = execute_production_cleanup(
        session,
        ctx=ctx,
        approval=appr,
        approval_secret=appr.secret,
        order_port=_MockPort(),
        source=SOURCE_OPERATOR_EXPLICIT,
        allowed_binding_ids=frozenset({537}),
    )
    assert out["reason"] == "BINDING_NOT_IN_ALLOWED_SET"
