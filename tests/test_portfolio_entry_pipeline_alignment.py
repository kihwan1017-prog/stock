"""Portfolio entry pipeline alignment — WAITING_SIGNAL / reserve-on-signal / hold."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from stock_platform.operation.upbit_full_market.constants import (
    CONFIRM_ALIGN_PORTFOLIO_ENTRY_PIPELINE,
    SLOT_EMPTY,
    SLOT_ENTRY_PENDING,
    SLOT_WAITING_SIGNAL,
)
from stock_platform.operation.upbit_full_market.portfolio_service import (
    UpbitPortfolioService,
)


def _slot(
    *,
    slot_id: int = 1,
    status: str = SLOT_WAITING_SIGNAL,
    symbol: str | None = "KRW-WLD",
    reserved: float | None = None,
    age_seconds: float = 10.0,
    selection_id: int | None = 11,
) -> SimpleNamespace:
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        slot_id=slot_id,
        slot_no=1,
        status=status,
        symbol=symbol,
        candidate_selection_id=selection_id,
        scanner_run_id="run",
        reserved_amount_krw=reserved,
        allocated_amount_krw=reserved,
        recommended_amount_krw=None,
        clamp_reasons=[],
        entry_order_id=None,
        version=1,
        created_at=now - timedelta(seconds=age_seconds),
        updated_at=now - timedelta(seconds=age_seconds),
        ai_analysis_id=None,
    )


def test_begin_entry_from_signal_reserves() -> None:
    session = MagicMock()
    slot = _slot(status=SLOT_WAITING_SIGNAL, reserved=None, selection_id=None)
    session.scalar = MagicMock(return_value=slot)
    session.get = MagicMock(return_value=SimpleNamespace(user_id=61))
    svc = UpbitPortfolioService(session)
    svc.pending_entry_count = MagicMock(return_value=0)  # type: ignore[method-assign]
    svc._assignment._has_preexisting_holding = MagicMock(return_value=False)  # type: ignore[method-assign]
    policy = SimpleNamespace(
        enabled=True,
        entry_state="RUNNING",
        portfolio_capital_limit_krw=300000,
        min_cash_reserve_pct=0.6,
        per_position_target_pct=0.08,
        max_symbol_exposure_pct=0.12,
        max_total_exposure_pct=0.3,
    )
    svc.get_or_create_policy = MagicMock(return_value=policy)  # type: ignore[method-assign]
    svc.strategy_exposure_total = MagicMock(return_value=Decimal("0"))  # type: ignore[method-assign]
    svc.reserved_amount_total = MagicMock(return_value=Decimal("0"))  # type: ignore[method-assign]

    risk_limits = SimpleNamespace(
        max_order_amount=Decimal("10000"),
        max_position_amount=Decimal("1000000"),
        source_layers=("uba",),
    )

    with (
        patch(
            "stock_platform.operation.upbit_full_market.portfolio_service.resolve_portfolio_entry_risk_limits",
            return_value=risk_limits,
        ),
        patch(
            "stock_platform.trading.symbol_ownership.SymbolOwnershipService"
        ) as ownership_cls,
        patch(
            "stock_platform.operation.upbit_full_market.waiting_revalidation_gate.evaluate_waiting_buy_revalidation_gate",
            return_value={"allowed": True},
        ),
        patch(
            "stock_platform.operation.upbit_full_market.portfolio_daily_entry_count.summarize_portfolio_daily_entries",
            return_value={"entry_count": 0},
        ),
    ):
        ownership = MagicMock()
        ownership.entry_gate.return_value = (
            True,
            None,
            SimpleNamespace(owner="FREE", reasons=[]),
        )
        ownership_cls.return_value = ownership
        out = svc.begin_entry_from_signal(
            1380,
            symbol="KRW-WLD",
            available_krw=Decimal("500000"),
        )

    assert out["ok"] is True
    assert out["status"] == SLOT_ENTRY_PENDING
    assert float(out["reserved_amount_krw"]) > 0
    assert float(out["final_order_amount_krw"]) <= 10000.0
    assert slot.status == SLOT_ENTRY_PENDING
    assert float(slot.reserved_amount_krw or 0) > 0


def test_begin_entry_already_entry_pending_includes_approved_amount() -> None:
    """ENTRY_PENDING 재시도 — executor가 Risk 한도 내 approved 금액을 받아야 한다."""

    session = MagicMock()
    existing = _slot(
        status=SLOT_ENTRY_PENDING,
        symbol="KRW-ONDO",
        reserved=10000.0,
        selection_id=290,
    )
    svc = UpbitPortfolioService(session)
    svc.pending_entry_count = MagicMock(return_value=1)  # type: ignore[method-assign]
    session.scalar = MagicMock(return_value=existing)
    out = svc.begin_entry_from_signal(1380, symbol="KRW-ONDO")
    assert out["ok"] is True
    assert out.get("already") is True
    assert float(out["approved_amount_krw"]) == 10000.0
    assert float(out["reserved_amount_krw"]) == 10000.0


def test_begin_entry_max_pending_blocks_second_symbol() -> None:
    session = MagicMock()
    svc = UpbitPortfolioService(session)
    svc.pending_entry_count = MagicMock(return_value=1)  # type: ignore[method-assign]
    session.scalar = MagicMock(return_value=None)
    out = svc.begin_entry_from_signal(1380, symbol="KRW-BTC")
    assert out["ok"] is False
    assert out["reason"] == "PENDING_ENTRY_LIMIT"


def test_candidate_hold_blocks_churn() -> None:
    session = MagicMock()
    held = _slot(age_seconds=60, selection_id=11)
    session.scalars = MagicMock(return_value=[held])
    session.get = MagicMock(
        return_value=SimpleNamespace(score=90.0, confidence=0.9)
    )
    svc = UpbitPortfolioService(session)
    out = svc._candidate_hold_block(
        1380,
        candidates=[{"symbol": "KRW-ETH", "score": 91.0}],
    )
    assert out["blocked"] is True
    assert out["reason"] == "CANDIDATE_HOLD"


def test_align_legacy_entry_pending_to_waiting() -> None:
    session = MagicMock()
    slot = _slot(
        status=SLOT_ENTRY_PENDING,
        reserved=10000.0,
        age_seconds=600,
    )
    session.scalars = MagicMock(return_value=[slot])
    svc = UpbitPortfolioService(session)
    svc._has_local_open_order = MagicMock(return_value=False)  # type: ignore[method-assign]
    svc._has_pending_outbox_for_symbol = MagicMock(return_value=False)  # type: ignore[method-assign]

    from unittest.mock import patch

    with patch(
        "stock_platform.operation.upbit_full_market.portfolio_runtime_sync.sync_portfolio_runtime_symbols",
        return_value={"ok": True, "desired_symbols": ["KRW-WLD"]},
    ):
        out = svc.align_legacy_reserved_entry_pending(
            1380,
            confirmation_text=CONFIRM_ALIGN_PORTFOLIO_ENTRY_PIPELINE,
            actor="test",
        )
    assert out["ok"] is True
    assert slot.status == SLOT_WAITING_SIGNAL
    assert slot.reserved_amount_krw is None


def test_waiting_signal_has_zero_reservation_semantics() -> None:
    """문서화된 semantics: WAITING_SIGNAL reserved=0."""

    slot = _slot(status=SLOT_WAITING_SIGNAL, reserved=None)
    assert slot.status == SLOT_WAITING_SIGNAL
    assert not slot.reserved_amount_krw


def test_entry_pending_timeout_rolls_to_waiting_not_empty() -> None:
    session = MagicMock()
    slot = _slot(
        status=SLOT_ENTRY_PENDING,
        reserved=10000.0,
        age_seconds=200,
    )
    session.scalars = MagicMock(return_value=[slot])
    svc = UpbitPortfolioService(session)
    svc._has_local_open_order = MagicMock(return_value=False)  # type: ignore[method-assign]
    svc._has_pending_outbox_for_symbol = MagicMock(return_value=False)  # type: ignore[method-assign]
    assignment = SimpleNamespace(
        mode="FULL_MARKET_PORTFOLIO",
        current_symbol="KRW-WLD",
        signals_paused=False,
        state="IDLE",
    )
    svc._assignment.get_or_create = MagicMock(return_value=assignment)  # type: ignore[method-assign]

    out = svc.recover_stale_entry_pending_without_order(
        1380, timeout_seconds=120, broker_open_symbols=set()
    )
    assert out["released"] == 1
    assert slot.status == SLOT_WAITING_SIGNAL
    assert slot.symbol == "KRW-WLD"
    assert slot.status != SLOT_EMPTY
