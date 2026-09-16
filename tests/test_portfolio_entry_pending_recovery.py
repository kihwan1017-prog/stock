"""ENTRY_PENDING without order — timeout recovery (REAL 주문 없음)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from stock_platform.operation.upbit_full_market.constants import (
    CONFIRM_RECOVER_STALE_ENTRY_PENDING,
    SLOT_EMPTY,
    SLOT_ENTRY_PENDING,
)
from stock_platform.operation.upbit_full_market.portfolio_service import (
    UpbitPortfolioService,
)


def _slot(
    *,
    slot_id: int = 1,
    status: str = SLOT_ENTRY_PENDING,
    symbol: str | None = "KRW-NEAR",
    entry_order_id: int | None = None,
    age_seconds: float = 200.0,
) -> SimpleNamespace:
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        slot_id=slot_id,
        slot_no=1,
        status=status,
        symbol=symbol,
        candidate_selection_id=2,
        scanner_run_id="run-1",
        reserved_amount_krw=10000.0,
        allocated_amount_krw=10000.0,
        recommended_amount_krw=10000.0,
        clamp_reasons=[],
        entry_order_id=entry_order_id,
        position_binding_id=None,
        version=2,
        created_at=now - timedelta(seconds=age_seconds),
        updated_at=now - timedelta(seconds=age_seconds),
    )


def _svc_with_slots(slots: list[SimpleNamespace]) -> UpbitPortfolioService:
    session = MagicMock()

    def _scalars(_query):  # noqa: ANN001
        return list(slots)

    session.scalars = MagicMock(side_effect=_scalars)
    session.scalar = MagicMock(return_value=0)
    session.get = MagicMock(return_value=None)
    svc = UpbitPortfolioService(session)
    assignment = SimpleNamespace(
        mode="FULL_MARKET_PORTFOLIO",
        current_symbol="KRW-NEAR",
        signals_paused=True,
        state="IDLE",
    )
    svc._assignment = MagicMock()
    svc._assignment.get_or_create = MagicMock(return_value=assignment)
    svc.active_symbols = MagicMock(return_value=[])
    return svc


def test_stale_entry_pending_without_order_releases() -> None:
    slot = _slot(age_seconds=200)
    svc = _svc_with_slots([slot])
    svc._has_local_open_order = MagicMock(return_value=False)  # type: ignore[method-assign]
    svc._has_pending_outbox_for_symbol = MagicMock(return_value=False)  # type: ignore[method-assign]

    out = svc.recover_stale_entry_pending_without_order(
        1380,
        timeout_seconds=120,
        confirmation_text=CONFIRM_RECOVER_STALE_ENTRY_PENDING,
        broker_open_symbols=set(),
        actor="test",
    )
    assert out["ok"] is True
    assert out["released"] == 1
    assert slot.status == "WAITING_SIGNAL"
    assert slot.reserved_amount_krw is None
    assert slot.entry_order_id is None


def test_fresh_entry_pending_not_released() -> None:
    slot = _slot(age_seconds=30)
    svc = _svc_with_slots([slot])
    svc._has_local_open_order = MagicMock(return_value=False)  # type: ignore[method-assign]
    svc._has_pending_outbox_for_symbol = MagicMock(return_value=False)  # type: ignore[method-assign]

    out = svc.recover_stale_entry_pending_without_order(
        1380, timeout_seconds=120, broker_open_symbols=set()
    )
    assert out["released"] == 0
    assert out["blocked"][0]["reason"] == "NOT_YET_TIMEOUT"
    assert slot.status == SLOT_ENTRY_PENDING


def test_local_open_order_blocks_release() -> None:
    slot = _slot(age_seconds=300)
    svc = _svc_with_slots([slot])
    svc._has_local_open_order = MagicMock(return_value=True)  # type: ignore[method-assign]
    svc._has_pending_outbox_for_symbol = MagicMock(return_value=False)  # type: ignore[method-assign]

    out = svc.recover_stale_entry_pending_without_order(
        1380, timeout_seconds=120, broker_open_symbols=set()
    )
    assert out["released"] == 0
    assert out["blocked"][0]["reason"] == "LOCAL_OPEN_ORDER"
    assert slot.status == SLOT_ENTRY_PENDING


def test_outbox_pending_blocks_release() -> None:
    slot = _slot(age_seconds=300)
    svc = _svc_with_slots([slot])
    svc._has_local_open_order = MagicMock(return_value=False)  # type: ignore[method-assign]
    svc._has_pending_outbox_for_symbol = MagicMock(return_value=True)  # type: ignore[method-assign]

    out = svc.recover_stale_entry_pending_without_order(
        1380, timeout_seconds=120, broker_open_symbols=set()
    )
    assert out["released"] == 0
    assert out["blocked"][0]["reason"] == "OUTBOX_PENDING"


def test_broker_open_order_blocks_release() -> None:
    slot = _slot(age_seconds=300, symbol="KRW-NEAR")
    svc = _svc_with_slots([slot])
    svc._has_local_open_order = MagicMock(return_value=False)  # type: ignore[method-assign]
    svc._has_pending_outbox_for_symbol = MagicMock(return_value=False)  # type: ignore[method-assign]

    out = svc.recover_stale_entry_pending_without_order(
        1380,
        timeout_seconds=120,
        broker_open_symbols={"KRW-NEAR"},
    )
    assert out["released"] == 0
    assert out["blocked"][0]["reason"] == "BROKER_OPEN_ORDER"


def test_entry_order_id_present_not_in_query_path() -> None:
    """entry_order_id 있는 slot은 recover 쿼리 대상 자체가 아님."""

    slot = _slot(age_seconds=300, entry_order_id=1799)
    # recover 쿼리가 entry_order_id IS NULL 이므로 빈 목록으로 시뮬레이션
    svc = _svc_with_slots([])
    out = svc.recover_stale_entry_pending_without_order(
        1380, timeout_seconds=60, broker_open_symbols=set()
    )
    assert out["released"] == 0
    assert slot.status == SLOT_ENTRY_PENDING
    assert slot.entry_order_id == 1799


def test_confirm_mismatch() -> None:
    svc = _svc_with_slots([_slot()])
    out = svc.recover_stale_entry_pending_without_order(
        1380, confirmation_text="WRONG"
    )
    assert out["ok"] is False
    assert out["reason"] == "CONFIRMATION_MISMATCH"


def test_market_feed_evaluator_requires_freshness() -> None:
    from stock_platform.trading.autotrading_master_gate import (
        _evaluate_market_feed_for_auto_live,
    )

    now = datetime.now(timezone.utc).isoformat()
    healthy = _evaluate_market_feed_for_auto_live(
        quote_ws={
            "connected": True,
            "running": True,
            "last_received_at": now,
        },
        hub={"dispatch_running": True, "ok": True},
        strategy_symbols=["KRW-NEAR"],
    )
    assert healthy["ok"] is True

    stale = _evaluate_market_feed_for_auto_live(
        quote_ws={"connected": False, "running": False},
        hub={"dispatch_running": False},
        strategy_symbols=["KRW-NEAR"],
    )
    assert stale["ok"] is False
    assert stale["reason"] == "QUOTE_WS_NOT_CONNECTED"
