"""ENTRY_PENDING orderless terminal reject → WAITING_SIGNAL rollback.

REAL broker 호출 없음. max_open_positions / stale timeout 정책 변경 없음.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from stock_platform.common.settings import get_settings
from stock_platform.operation.upbit_full_market.constants import (
    SLOT_ENTRY_PENDING,
    SLOT_WAITING_SIGNAL,
)
from stock_platform.operation.upbit_full_market.portfolio_service import (
    UpbitPortfolioService,
)
from stock_platform.realtime.execution_models import (
    RealtimeExecutionConfig,
    RealtimeExecutionMode,
)
from stock_platform.realtime.risk_integrated_order_executor import (
    RiskIntegratedRealtimeOrderExecutor,
)
from stock_platform.realtime.strategy_models import (
    RealtimeSignal,
    RealtimeSignalAction,
)


def _slot(
    *,
    status: str = SLOT_ENTRY_PENDING,
    symbol: str = "KRW-DOS",
    entry_order_id: int | None = None,
    reserved: float | None = 12000.0,
    allocated: float | None = 12000.0,
    selection_id: int | None = 369,
) -> SimpleNamespace:
    return SimpleNamespace(
        slot_id=7,
        slot_no=1,
        status=status,
        symbol=symbol,
        candidate_selection_id=selection_id,
        scanner_run_id="run-1",
        reserved_amount_krw=reserved,
        allocated_amount_krw=allocated,
        recommended_amount_krw=reserved,
        clamp_reasons=[],
        entry_order_id=entry_order_id,
        position_binding_id=None,
        version=3,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def _svc(slot: SimpleNamespace | None) -> UpbitPortfolioService:
    session = MagicMock()
    session.scalar = MagicMock(return_value=slot)
    session.flush = MagicMock()
    svc = UpbitPortfolioService(session)
    svc._has_local_open_order = MagicMock(return_value=False)  # type: ignore[method-assign]
    svc._has_pending_outbox_for_symbol = MagicMock(return_value=False)  # type: ignore[method-assign]
    svc._order_has_broker_uuid = MagicMock(return_value=False)  # type: ignore[method-assign]
    svc._has_active_cancel_or_recovery = MagicMock(return_value=False)  # type: ignore[method-assign]
    return svc


def test_max_open_positions_orderless_reject_rolls_to_waiting() -> None:
    """1. begin_entry 후 MAX_OPEN_POSITIONS → WAITING_SIGNAL"""
    slot = _slot()
    svc = _svc(slot)

    out = svc.rollback_entry_pending_after_terminal_reject(
        1380,
        symbol="KRW-DOS",
        reason_code="MAX_OPEN_POSITIONS_REACHED",
        actor="test",
        signal_id="sig_test",
        selection_id=369,
    )

    assert out["ok"] is True
    assert out["rolled_back"] is True
    assert slot.status == SLOT_WAITING_SIGNAL
    assert slot.entry_order_id is None
    assert slot.symbol == "KRW-DOS"
    assert slot.candidate_selection_id == 369
    assert "EXECUTOR_REJECTED_NO_ORDER_ROLLBACK:MAX_OPEN_POSITIONS_REACHED" in (
        slot.clamp_reasons or []
    )
    assert out["new_state"] == SLOT_WAITING_SIGNAL


def test_reservation_released_on_rollback() -> None:
    """2. reservation 존재 시 canonical release (reserve/alloc clear)"""
    slot = _slot(reserved=15000.0, allocated=14000.0)
    svc = _svc(slot)

    out = svc.rollback_entry_pending_after_terminal_reject(
        1380,
        symbol="KRW-CHIP",
        reason_code="MAX_OPEN_POSITIONS_REACHED",
    )

    assert out["reservation_released"] is True
    assert slot.reserved_amount_krw is None
    assert slot.allocated_amount_krw is None
    assert slot.status == SLOT_WAITING_SIGNAL


def test_trading_order_exists_no_rollback() -> None:
    """3. local TradingOrder 존재 → rollback 금지"""
    slot = _slot()
    svc = _svc(slot)
    svc._has_local_open_order = MagicMock(return_value=True)  # type: ignore[method-assign]

    out = svc.rollback_entry_pending_after_terminal_reject(
        1380,
        symbol="KRW-DOS",
        reason_code="MAX_OPEN_POSITIONS_REACHED",
    )

    assert out["rolled_back"] is False
    assert out["reason"] == "LOCAL_OPEN_ORDER"
    assert slot.status == SLOT_ENTRY_PENDING
    assert slot.reserved_amount_krw == 12000.0


def test_broker_uuid_or_entry_order_id_no_rollback() -> None:
    """4. entry_order_id / broker_uuid 존재 → rollback 금지"""
    slot_oid = _slot(entry_order_id=1927)
    svc_oid = _svc(slot_oid)
    out_oid = svc_oid.rollback_entry_pending_after_terminal_reject(
        1380,
        symbol="KRW-DOS",
        reason_code="MAX_OPEN_POSITIONS_REACHED",
    )
    assert out_oid["rolled_back"] is False
    assert out_oid["reason"] == "ENTRY_ORDER_ID_PRESENT"
    assert slot_oid.status == SLOT_ENTRY_PENDING

    slot_uuid = _slot(entry_order_id=None)
    svc_uuid = _svc(slot_uuid)
    svc_uuid._order_has_broker_uuid = MagicMock(return_value=True)  # type: ignore[method-assign]
    out_uuid = svc_uuid.rollback_entry_pending_after_terminal_reject(
        1380,
        symbol="KRW-DOS",
        reason_code="MAX_OPEN_POSITIONS_REACHED",
    )
    assert out_uuid["rolled_back"] is False
    assert out_uuid["reason"] == "BROKER_UUID_PRESENT"
    assert slot_uuid.status == SLOT_ENTRY_PENDING


def test_inflight_outbox_no_rollback() -> None:
    """5. order submission in-flight → rollback 금지"""
    slot = _slot()
    svc = _svc(slot)
    svc._has_pending_outbox_for_symbol = MagicMock(return_value=True)  # type: ignore[method-assign]

    out = svc.rollback_entry_pending_after_terminal_reject(
        1380,
        symbol="KRW-DOS",
        reason_code="MAX_OPEN_POSITIONS_REACHED",
    )
    assert out["rolled_back"] is False
    assert out["reason"] == "ORDER_SUBMISSION_INFLIGHT"
    assert slot.status == SLOT_ENTRY_PENDING


def test_recovery_or_cancel_no_rollback() -> None:
    """6. active recovery/cancel → rollback 금지"""
    slot = _slot()
    svc = _svc(slot)
    svc._has_active_cancel_or_recovery = MagicMock(return_value=True)  # type: ignore[method-assign]

    out = svc.rollback_entry_pending_after_terminal_reject(
        1380,
        symbol="KRW-DOS",
        reason_code="MAX_OPEN_POSITIONS_REACHED",
    )
    assert out["rolled_back"] is False
    assert out["reason"] == "ACTIVE_RECOVERY_OR_CANCEL"
    assert slot.status == SLOT_ENTRY_PENDING


def test_idempotent_repeated_reject() -> None:
    """7. 동일 reject 반복 → 중복 transition 오류 없음"""
    slot = _slot()
    svc = _svc(slot)

    first = svc.rollback_entry_pending_after_terminal_reject(
        1380,
        symbol="KRW-DOS",
        reason_code="MAX_OPEN_POSITIONS_REACHED",
    )
    assert first["rolled_back"] is True

    # 두 번째: 이미 WAITING_SIGNAL
    slot.status = SLOT_WAITING_SIGNAL
    slot.reserved_amount_krw = None
    slot.allocated_amount_krw = None
    second = svc.rollback_entry_pending_after_terminal_reject(
        1380,
        symbol="KRW-DOS",
        reason_code="MAX_OPEN_POSITIONS_REACHED",
    )
    assert second["ok"] is True
    assert second["noop"] is True
    assert second["rolled_back"] is False
    assert second["reason"] == "ALREADY_WAITING_SIGNAL"
    assert slot.status == SLOT_WAITING_SIGNAL


def test_waiting_signal_same_reject_noop() -> None:
    """8. WAITING_SIGNAL에서 same reject → safe no-op"""
    slot = _slot(status=SLOT_WAITING_SIGNAL, reserved=None, allocated=None)
    svc = _svc(slot)

    out = svc.rollback_entry_pending_after_terminal_reject(
        1380,
        symbol="KRW-CHIP",
        reason_code="MAX_OPEN_POSITIONS_REACHED",
    )
    assert out["noop"] is True
    assert out["rolled_back"] is False
    assert slot.status == SLOT_WAITING_SIGNAL


def test_stale_timeout_setting_unchanged() -> None:
    """9. stale timer 120초 정책 미변경"""
    settings = get_settings()
    timeout = float(
        getattr(settings, "upbit_portfolio_entry_pending_timeout_seconds", 120)
        or 120
    )
    assert timeout == 120.0


def test_successful_order_path_unchanged_guard() -> None:
    """10. entry_order_id 연결 성공 경로 — rollback 대상 아님"""
    slot = _slot(entry_order_id=5555)
    svc = _svc(slot)
    out = svc.rollback_entry_pending_after_terminal_reject(
        1380,
        symbol="KRW-XRP",
        reason_code="SOME_LATER_REJECT",
    )
    assert out["rolled_back"] is False
    assert out["reason"] == "ENTRY_ORDER_ID_PRESENT"
    assert slot.status == SLOT_ENTRY_PENDING
    assert slot.entry_order_id == 5555


def test_risk_reject_also_rolls_back_orderless() -> None:
    """11. Risk/기타 terminal reject도 주문 없으면 동일 rollback (회귀 가드)"""
    slot = _slot(symbol="KRW-ADA")
    svc = _svc(slot)
    out = svc.rollback_entry_pending_after_terminal_reject(
        1380,
        symbol="KRW-ADA",
        reason_code="RISK_ENGINE_BLOCKED",
    )
    assert out["rolled_back"] is True
    assert slot.status == SLOT_WAITING_SIGNAL


def test_executor_skipped_invokes_rollback_no_real_broker() -> None:
    """12. executor _skipped → rollback 호출 (REAL broker 없음)"""
    from decimal import Decimal

    session = MagicMock()
    config = RealtimeExecutionConfig(
        mode=RealtimeExecutionMode.LIVE,
        account_id=1,
        user_broker_account_id=1380,
        broker_code="UPBIT",
        order_amount=Decimal("5500"),
    )
    guard = MagicMock()
    executor = RiskIntegratedRealtimeOrderExecutor(
        session=session, execution_config=config, safety_guard=guard
    )

    signal = RealtimeSignal(
        signal_id="sig_rollback_test",
        exchange_code="UPBIT",
        symbol="KRW-DOS",
        action=RealtimeSignalAction.BUY,
        signal_price=Decimal("100"),
        short_average=Decimal("101"),
        long_average=Decimal("99"),
        change_rate=Decimal("0.01"),
        reason_code="PORTFOLIO_ENTRY",
        generated_at=datetime.now(timezone.utc),
        account_id=1380,
        account_kind="USER_BROKER",
        broker_code="UPBIT",
        user_broker_account_id=1380,
        execution_trace_id="trace-rollback-1",
        candidate_selection_id=369,
    )

    with patch.object(
        UpbitPortfolioService,
        "rollback_entry_pending_after_terminal_reject",
        return_value={"ok": True, "rolled_back": True},
    ) as mocked:
        with patch(
            "stock_platform.realtime.order_executor.RealtimePaperOrderExecutor._skipped",
            return_value=MagicMock(
                accepted=False, reason_code="MAX_OPEN_POSITIONS_REACHED"
            ),
        ):
            executor._skipped(signal, "MAX_OPEN_POSITIONS_REACHED")

        assert mocked.called
        kwargs = mocked.call_args.kwargs
        assert kwargs["symbol"] == "KRW-DOS"
        assert kwargs["reason_code"] == "MAX_OPEN_POSITIONS_REACHED"
        assert kwargs["execution_trace_id"] == "trace-rollback-1"
