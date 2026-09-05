"""Overlapping AUTO entry occupancy + C3 SHADOW_DECISION + MA exit telemetry."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from contextlib import nullcontext

from stock_platform.operation.upbit_full_market.constants import (
    BINDING_STATUS_OPEN,
    SLOT_ENTRY_PENDING,
    SLOT_OPEN,
)
from stock_platform.operation.upbit_full_market.entry_occupancy import (
    REASON_ACTIVE_ENTRY_LIFECYCLE,
    REASON_EXISTING_SYMBOL_EXPOSURE,
    REASON_PENDING_RECONCILIATION,
    inspect_symbol_auto_occupancy,
)
from stock_platform.operation.upbit_full_market.portfolio_service import (
    UpbitPortfolioService,
)
from stock_platform.operation.upbit_opportunity_shadow.profitability_improvement_shadow.constants import (
    VARIANT_C0,
    VARIANT_C1,
    VARIANT_C2,
    VARIANT_C3,
)
from stock_platform.operation.upbit_opportunity_shadow.profitability_improvement_shadow.reentry_engine import (
    decide_reentry_block,
)


def test_occupancy_open_slot_blocks() -> None:
    session = MagicMock()
    slot = SimpleNamespace(
        slot_id=1,
        status=SLOT_OPEN,
        entry_order_id=100,
    )
    session.scalar = MagicMock(return_value=slot)
    out = inspect_symbol_auto_occupancy(
        session, user_broker_account_id=1380, symbol="KRW-XLM"
    )
    assert out["occupied"] is True
    assert out["reason"] == REASON_EXISTING_SYMBOL_EXPOSURE


def test_occupancy_entry_pending_with_order_blocks() -> None:
    session = MagicMock()
    slot = SimpleNamespace(
        slot_id=2,
        status=SLOT_ENTRY_PENDING,
        entry_order_id=200,
    )
    session.scalar = MagicMock(return_value=slot)
    out = inspect_symbol_auto_occupancy(
        session, user_broker_account_id=1380, symbol="KRW-XLM"
    )
    assert out["occupied"] is True
    assert out["reason"] == REASON_ACTIVE_ENTRY_LIFECYCLE


def test_occupancy_entry_pending_orderless_pending_reconcile() -> None:
    session = MagicMock()
    slot = SimpleNamespace(
        slot_id=3,
        status=SLOT_ENTRY_PENDING,
        entry_order_id=None,
    )
    session.scalar = MagicMock(return_value=slot)
    out = inspect_symbol_auto_occupancy(
        session, user_broker_account_id=1380, symbol="KRW-XLM"
    )
    assert out["occupied"] is True
    assert out["reason"] == REASON_PENDING_RECONCILIATION


def test_occupancy_free_when_no_active() -> None:
    session = MagicMock()
    session.scalar = MagicMock(return_value=None)
    out = inspect_symbol_auto_occupancy(
        session, user_broker_account_id=1380, symbol="KRW-SOL"
    )
    assert out["occupied"] is False
    assert out["reason"] is None


def test_begin_entry_blocks_when_occupancy_open() -> None:
    session = MagicMock()
    svc = UpbitPortfolioService(session)
    policy = SimpleNamespace(
        portfolio_max_pending_entries=2,
        enabled=True,
        entry_state="RUNNING",
        max_positions=6,
    )
    with (
        patch.object(svc, "get_or_create_policy", return_value=policy),
        patch(
            "stock_platform.operation.upbit_full_market.buy_concurrency.acquire_buy_admission_xact_lock",
            return_value=nullcontext(),
        ),
        patch(
            "stock_platform.operation.upbit_full_market.entry_occupancy.inspect_symbol_auto_occupancy",
            return_value={
                "occupied": True,
                "reason": REASON_EXISTING_SYMBOL_EXPOSURE,
                "details": {"slot_status": SLOT_OPEN},
            },
        ),
    ):
        out = svc.begin_entry_from_signal(
            1380, symbol="KRW-XLM", available_krw=Decimal("50000")
        )
        assert out.get("ok") is False
        assert out.get("reason") == REASON_EXISTING_SYMBOL_EXPOSURE


def test_begin_entry_pending_with_order_fails_closed() -> None:
    """ENTRY_PENDING + entry_order_id → 신규 BUY 금지 (already로 통과 금지)."""

    session = MagicMock()
    svc = UpbitPortfolioService(session)
    policy = SimpleNamespace(
        portfolio_max_pending_entries=2,
        enabled=True,
        entry_state="RUNNING",
        max_positions=6,
    )
    existing = SimpleNamespace(
        slot_id=99,
        status=SLOT_ENTRY_PENDING,
        reserved_amount_krw=10000,
        allocated_amount_krw=10000,
        candidate_selection_id=None,
        entry_order_id=777,
    )
    with (
        patch.object(svc, "get_or_create_policy", return_value=policy),
        patch(
            "stock_platform.operation.upbit_full_market.buy_concurrency.acquire_buy_admission_xact_lock",
            return_value=nullcontext(),
        ),
        patch(
            "stock_platform.operation.upbit_full_market.entry_occupancy.inspect_symbol_auto_occupancy",
            return_value={"occupied": False, "reason": None, "details": {}},
        ),
    ):
        session.scalar = MagicMock(return_value=existing)
        out = svc.begin_entry_from_signal(
            1380, symbol="KRW-XRP", available_krw=Decimal("50000")
        )
        assert out.get("ok") is False
        assert out.get("reason") == REASON_ACTIVE_ENTRY_LIFECYCLE
        assert out.get("already_pending") is True


def test_c3_shadow_decision_never_null() -> None:
    for vid in (VARIANT_C0, VARIANT_C1, VARIANT_C2, VARIANT_C3):
        d = decide_reentry_block(
            variant_id=vid, delay_seconds=30.0, context={}
        )
        assert d.get("SHADOW_DECISION") in {"ALLOW", "BLOCK", "UNKNOWN"}
        assert d.get("SHADOW_DECISION") is not None
        assert "WOULD_BLOCK" in d
        assert "REASON" in d


def test_c3_unknown_context_is_unknown_not_null() -> None:
    d = decide_reentry_block(
        variant_id=VARIANT_C3,
        delay_seconds=200.0,
        context={},  # all flags UNKNOWN
    )
    assert d["SHADOW_DECISION"] == "UNKNOWN"
    assert d["REASON"] == "CONTEXTUAL_CONFIRMATION_UNKNOWN"
    assert d["WOULD_BLOCK"] is True


def test_c3_confirmed_allow() -> None:
    d = decide_reentry_block(
        variant_id=VARIANT_C3,
        delay_seconds=200.0,
        context={"new_signal": True, "ma_improved": False, "score_improved": False, "momentum_reset": False},
    )
    assert d["SHADOW_DECISION"] == "ALLOW"
    assert d["WOULD_BLOCK"] is False


def test_c3_no_confirmation_block() -> None:
    d = decide_reentry_block(
        variant_id=VARIANT_C3,
        delay_seconds=200.0,
        context={
            "new_signal": False,
            "ma_improved": False,
            "score_improved": False,
            "momentum_reset": False,
        },
    )
    assert d["SHADOW_DECISION"] == "BLOCK"
    assert d["REASON"] == "NO_INDEPENDENT_CONFIRMATION"


def test_ma_exit_intent_detail_passed() -> None:
    """create_intent_on_ma_emit forwards detail to create_on_confirmed."""

    from stock_platform.operation.upbit_exit_intent import hooks as h

    fake_row = SimpleNamespace(exit_intent_id=42)
    svc = MagicMock()
    svc.create_on_confirmed = MagicMock(return_value=fake_row)
    session = MagicMock()
    session_factory = MagicMock(return_value=session)

    with (
        patch.object(h, "feature_enabled", return_value=True),
        patch.object(h, "get_session_factory", return_value=session_factory),
        patch.object(h, "resolve_open_binding", return_value=(10, 11)),
        patch.object(h, "UpbitExitIntentService", return_value=svc),
    ):
        detail = {
            "sma_fast_value": 248.1,
            "sma_slow_value": 249.0,
            "current_price": 247.0,
            "holding_seconds": 120,
        }
        out = h.create_intent_on_ma_emit(
            user_broker_account_id=1380,
            symbol="KRW-XLM",
            signal_id=None,
            strategy_id=17483,
            strategy_version="1",
            quantity=Decimal("40"),
            detail=detail,
        )
        assert out == 42
        kwargs = svc.create_on_confirmed.call_args.kwargs
        assert kwargs["detail"]["sma_fast_value"] == 248.1
        assert kwargs["detail"]["current_price"] == 247.0
