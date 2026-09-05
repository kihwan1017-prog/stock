"""UPBIT limited buy concurrency V1 — clamp / admission / pending limit."""

from __future__ import annotations

from contextlib import nullcontext
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from stock_platform.operation.upbit_full_market.buy_concurrency import (
    V1_MAX_CONCURRENT_ENTRIES,
    clamp_concurrency_v1,
    resolve_executor_concurrency,
    resolve_max_concurrent_entries,
    resolve_order_submit_concurrency,
)
from stock_platform.operation.upbit_full_market.constants import (
    SLOT_ENTRY_PENDING,
)
from stock_platform.operation.upbit_full_market.portfolio_service import (
    UpbitPortfolioService,
)
from stock_platform.order.outbox_worker import OrderOutboxWorker, OutboxRunSummary


def test_clamp_invalid_to_one() -> None:
    assert clamp_concurrency_v1(0) == 1
    assert clamp_concurrency_v1(-1) == 1
    assert clamp_concurrency_v1(3) == 1
    assert clamp_concurrency_v1("x") == 1
    assert clamp_concurrency_v1(2) == 2
    assert clamp_concurrency_v1(1) == 1
    assert V1_MAX_CONCURRENT_ENTRIES == 2


def test_resolve_max_concurrent_from_policy() -> None:
    assert (
        resolve_max_concurrent_entries(
            SimpleNamespace(portfolio_max_pending_entries=2)
        )
        == 2
    )
    assert (
        resolve_max_concurrent_entries(
            SimpleNamespace(portfolio_max_pending_entries=10)
        )
        == 1
    )
    assert (
        resolve_max_concurrent_entries(
            SimpleNamespace(portfolio_max_pending_entries=1)
        )
        == 1
    )


def test_executor_submit_settings_clamp(monkeypatch) -> None:
    monkeypatch.setattr(
        "stock_platform.common.settings.get_settings",
        lambda: SimpleNamespace(
            upbit_buy_executor_concurrency=2,
            upbit_buy_order_submit_concurrency=2,
        ),
    )
    assert resolve_executor_concurrency() == 2
    assert resolve_order_submit_concurrency() == 2

    monkeypatch.setattr(
        "stock_platform.common.settings.get_settings",
        lambda: SimpleNamespace(
            upbit_buy_executor_concurrency=9,
            upbit_buy_order_submit_concurrency=0,
        ),
    )
    assert resolve_executor_concurrency() == 1
    assert resolve_order_submit_concurrency() == 1


def test_begin_entry_rejects_when_pending_at_max() -> None:
    session = MagicMock()
    svc = UpbitPortfolioService(session)

    policy = SimpleNamespace(
        portfolio_max_pending_entries=2,
        enabled=True,
        entry_state="RUNNING",
        max_positions=6,
        portfolio_capital_limit_krw=100000,
        min_cash_reserve_pct=10,
        per_position_target_pct=10,
        max_symbol_exposure_pct=20,
        max_total_exposure_pct=80,
        portfolio_daily_entry_limit=10,
        portfolio_daily_entry_limit_mode="LIMITED",
    )

    with (
        patch.object(svc, "get_or_create_policy", return_value=policy),
        patch.object(svc, "pending_entry_count", return_value=2),
        patch(
            "stock_platform.operation.upbit_full_market.buy_concurrency.acquire_buy_admission_xact_lock",
            return_value=nullcontext(),
        ),
        patch(
            "stock_platform.operation.upbit_full_market.auto_slot_count.count_auto_slots_used",
            return_value=0,
        ),
    ):
        session.scalar = MagicMock(return_value=None)
        out = svc.begin_entry_from_signal(
            1380, symbol="KRW-SOL", available_krw=Decimal("50000")
        )
        assert out.get("ok") is False
        assert out.get("reason") == "PENDING_ENTRY_LIMIT"
        assert out.get("max_concurrent_entries") == 2


def test_begin_entry_duplicate_symbol_pending_order_blocks() -> None:
    """ENTRY_PENDING + entry_order_id 는 already 통과가 아니라 fail-closed."""

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
        entry_order_id=555,
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
        assert "ENTRY_SKIPPED" in str(out.get("reason") or "")


def test_begin_entry_duplicate_symbol_orderless_already() -> None:
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
        entry_order_id=None,
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
        assert out.get("ok") is True
        assert out.get("already") is True
        assert out.get("slot_id") == 99


def test_begin_entry_position_limit_blocks() -> None:
    session = MagicMock()
    svc = UpbitPortfolioService(session)
    policy = SimpleNamespace(
        portfolio_max_pending_entries=2,
        enabled=True,
        entry_state="RUNNING",
        max_positions=6,
    )
    risk = SimpleNamespace(max_position_count=6)
    with (
        patch.object(svc, "get_or_create_policy", return_value=policy),
        patch.object(svc, "pending_entry_count", return_value=0),
        patch(
            "stock_platform.operation.upbit_full_market.buy_concurrency.acquire_buy_admission_xact_lock",
            return_value=nullcontext(),
        ),
        patch(
            "stock_platform.operation.upbit_full_market.auto_slot_count.count_auto_slots_used",
            return_value=6,
        ),
        patch(
            "stock_platform.risk_engine.resolved_policy.ResolvedRiskPolicyResolver"
        ) as resolver_cls,
    ):
        resolver_cls.return_value.resolve.return_value = risk
        session.scalar = MagicMock(return_value=None)
        out = svc.begin_entry_from_signal(
            1380, symbol="KRW-XRP", available_krw=Decimal("50000")
        )
        assert out.get("ok") is False
        assert out.get("reason") == "AUTO_POSITION_LIMIT_REACHED"


def test_outbox_parallel_wrapper_falls_back_serial() -> None:
    worker = OrderOutboxWorker(
        session_factory=MagicMock(),
        dispatcher=MagicMock(),
        worker_id="live-outbox-1",
        batch_size=2,
        live_only=True,
    )
    serial = OutboxRunSummary(
        claimed=1, succeeded=1, retried=0, failed=0, ambiguous=0
    )
    with patch.object(worker, "_run_claimed_serial", return_value=serial) as ser:
        out = worker._run_claimed([(1, 1)])
        assert out.succeeded == 1
        ser.assert_called_once()

    with (
        patch(
            "stock_platform.operation.upbit_full_market.buy_concurrency.resolve_order_submit_concurrency",
            return_value=2,
        ),
        patch.object(worker, "_run_claimed_serial", return_value=serial) as ser2,
    ):
        out2 = worker._run_claimed([(1, 1), (2, 1)])
        assert out2.claimed == 2
        assert ser2.call_count == 2
