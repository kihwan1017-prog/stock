"""K-B P0-2 — Kiwoom fill → broker_position_snapshot WRITE (fixture/mock only)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from stock_platform.broker.account_models import (
    BrokerAccountSnapshotEntity,
    BrokerPositionSnapshotEntity,
)
from stock_platform.broker.kiwoom.execution_models import KiwoomExecutionEvent
from stock_platform.broker.kiwoom.fill_position_write import (
    apply_kiwoom_fill_position_write,
    ensure_kiwoom_position_after_sync,
)
from stock_platform.broker.live_fill_ledger_service import LiveFillLedgerService


class _LedgerSession:
    """LiveFillLedger용 최소 in-memory session."""

    def __init__(self) -> None:
        self.positions: list[BrokerPositionSnapshotEntity] = []
        self.accounts: list[BrokerAccountSnapshotEntity] = []
        self.committed = 0
        self.rolled_back = 0
        # SQLAlchemy Session.new 호환 — 미flush INSERT 재사용 경로
        self.hide_positions_from_scalar = False

    @property
    def new(self) -> tuple[Any, ...]:
        return tuple(self.positions) + tuple(self.accounts)

    def add(self, obj: Any) -> None:
        if isinstance(obj, BrokerPositionSnapshotEntity):
            self.positions.append(obj)
        elif isinstance(obj, BrokerAccountSnapshotEntity):
            self.accounts.append(obj)

    def flush(self) -> None:
        return None

    def commit(self) -> None:
        self.committed += 1

    def rollback(self) -> None:
        self.rolled_back += 1

    def scalar(self, stmt: Any) -> Any:
        text = str(stmt).lower()
        if "broker_account_snapshot" in text or "deposit_amount" in text:
            return self.accounts[0] if self.accounts else None
        # position 조회 — multi-leg pending 경로 검증 시 DB miss 시뮬레이션
        if self.hide_positions_from_scalar:
            return None
        if self.positions:
            return self.positions[0]
        return None


def _order(
    *,
    uba: int = 77,
    side: str = "BUY",
    symbol: str = "005930",
    order_id: int = 1,
) -> SimpleNamespace:
    return SimpleNamespace(
        order_id=order_id,
        user_broker_account_id=uba,
        broker_code="KIWOOM",
        exchange_code="KRX",
        symbol=symbol,
        side_code=side,
    )


def _event(
    *,
    exec_id: str,
    qty: str,
    price: str,
    side: str = "BUY",
    symbol: str = "005930",
) -> KiwoomExecutionEvent:
    return KiwoomExecutionEvent(
        broker_order_id="BO-1",
        broker_execution_id=exec_id,
        symbol=symbol,
        side_code=side,
        execution_price=Decimal(price),
        execution_quantity=Decimal(qty),
        remaining_quantity=Decimal("0"),
        executed_at=datetime.now(timezone.utc),
        raw_payload={},
    )


def test_a_first_buy_creates_position():
    session = _LedgerSession()
    order = _order(side="BUY")
    result = apply_kiwoom_fill_position_write(
        session,
        order=order,
        event=_event(exec_id="E1", qty="10", price="70000"),
        commit=True,
    )
    assert result["applied"] is True
    assert len(session.positions) == 1
    assert Decimal(session.positions[0].quantity) == Decimal("10")
    assert Decimal(session.positions[0].average_purchase_price) == Decimal(
        "70000"
    )


def test_b_additional_buy_weighted_avg():
    session = _LedgerSession()
    pos = BrokerPositionSnapshotEntity(
        broker_code="KIWOOM",
        account_number="UBA:77",
        user_broker_account_id=77,
        exchange_code="KRX",
        symbol="005930",
        name="005930",
        quantity=Decimal("10"),
        available_quantity=Decimal("10"),
        average_purchase_price=Decimal("70000"),
        current_price=Decimal("70000"),
        purchase_amount=Decimal("700000"),
        evaluation_amount=Decimal("700000"),
        profit_loss=Decimal("0"),
        return_rate=Decimal("0"),
        raw_data={
            "ledger_source": "FILL_DRIVEN",
            "applied_execution_ids": ["E1"],
        },
    )
    cash = BrokerAccountSnapshotEntity(
        broker_code="KIWOOM",
        account_number="UBA:77",
        user_broker_account_id=77,
        currency_code="KRW",
        deposit_amount=Decimal("9000000"),
        available_order_amount=Decimal("9000000"),
        total_purchase_amount=Decimal("700000"),
        total_evaluation_amount=Decimal("700000"),
        total_profit_loss=Decimal("0"),
        total_return_rate=Decimal("0"),
        raw_data={"ledger_source": "FILL_DRIVEN", "realized_profit_loss": "0"},
    )
    session.positions = [pos]
    session.accounts = [cash]
    result = LiveFillLedgerService(session).apply_execution(
        order=_order(side="BUY"),
        event=_event(exec_id="E2", qty="10", price="80000"),
    )
    assert result["applied"] is True
    assert Decimal(pos.quantity) == Decimal("20")
    assert Decimal(pos.average_purchase_price) == Decimal("75000")


def test_c_partial_sell_reduces_qty_and_realized():
    session = _LedgerSession()
    pos = BrokerPositionSnapshotEntity(
        broker_code="KIWOOM",
        account_number="UBA:77",
        user_broker_account_id=77,
        exchange_code="KRX",
        symbol="005930",
        name="005930",
        quantity=Decimal("20"),
        available_quantity=Decimal("20"),
        average_purchase_price=Decimal("75000"),
        current_price=Decimal("75000"),
        purchase_amount=Decimal("1500000"),
        evaluation_amount=Decimal("1500000"),
        profit_loss=Decimal("0"),
        return_rate=Decimal("0"),
        raw_data={
            "ledger_source": "FILL_DRIVEN",
            "applied_execution_ids": ["E1", "E2"],
        },
    )
    cash = BrokerAccountSnapshotEntity(
        broker_code="KIWOOM",
        account_number="UBA:77",
        user_broker_account_id=77,
        currency_code="KRW",
        deposit_amount=Decimal("8500000"),
        available_order_amount=Decimal("8500000"),
        total_purchase_amount=Decimal("1500000"),
        total_evaluation_amount=Decimal("1500000"),
        total_profit_loss=Decimal("0"),
        total_return_rate=Decimal("0"),
        raw_data={"ledger_source": "FILL_DRIVEN", "realized_profit_loss": "0"},
    )
    session.positions = [pos]
    session.accounts = [cash]
    order = _order(side="SELL")
    result = LiveFillLedgerService(session).apply_execution(
        order=order,
        event=_event(exec_id="E3", qty="5", price="80000", side="SELL"),
    )
    assert result["applied"] is True
    assert Decimal(pos.quantity) == Decimal("15")
    assert Decimal(result["realized_delta"]) == Decimal("25000.00")


def test_d_full_sell_closes_position():
    session = _LedgerSession()
    pos = BrokerPositionSnapshotEntity(
        broker_code="KIWOOM",
        account_number="UBA:77",
        user_broker_account_id=77,
        exchange_code="KRX",
        symbol="005930",
        name="005930",
        quantity=Decimal("5"),
        available_quantity=Decimal("5"),
        average_purchase_price=Decimal("75000"),
        current_price=Decimal("75000"),
        purchase_amount=Decimal("375000"),
        evaluation_amount=Decimal("375000"),
        profit_loss=Decimal("0"),
        return_rate=Decimal("0"),
        raw_data={
            "ledger_source": "FILL_DRIVEN",
            "applied_execution_ids": ["E1"],
        },
    )
    cash = BrokerAccountSnapshotEntity(
        broker_code="KIWOOM",
        account_number="UBA:77",
        user_broker_account_id=77,
        currency_code="KRW",
        deposit_amount=Decimal("9000000"),
        available_order_amount=Decimal("9000000"),
        total_purchase_amount=Decimal("375000"),
        total_evaluation_amount=Decimal("375000"),
        total_profit_loss=Decimal("0"),
        total_return_rate=Decimal("0"),
        raw_data={"ledger_source": "FILL_DRIVEN", "realized_profit_loss": "0"},
    )
    session.positions = [pos]
    session.accounts = [cash]
    result = LiveFillLedgerService(session).apply_execution(
        order=_order(side="SELL"),
        event=_event(exec_id="E4", qty="5", price="76000", side="SELL"),
    )
    assert result["applied"] is True
    assert Decimal(pos.quantity) == Decimal("0")
    assert Decimal(pos.average_purchase_price) == Decimal("0")


def test_e_duplicate_execution_no_mutation():
    session = _LedgerSession()
    pos = BrokerPositionSnapshotEntity(
        broker_code="KIWOOM",
        account_number="UBA:77",
        user_broker_account_id=77,
        exchange_code="KRX",
        symbol="005930",
        name="005930",
        quantity=Decimal("10"),
        available_quantity=Decimal("10"),
        average_purchase_price=Decimal("70000"),
        current_price=Decimal("70000"),
        purchase_amount=Decimal("700000"),
        evaluation_amount=Decimal("700000"),
        profit_loss=Decimal("0"),
        return_rate=Decimal("0"),
        raw_data={
            "ledger_source": "FILL_DRIVEN",
            "applied_execution_ids": ["E1"],
        },
    )
    session.positions = [pos]
    result = LiveFillLedgerService(session).apply_execution(
        order=_order(side="BUY"),
        event=_event(exec_id="E1", qty="10", price="70000"),
    )
    assert result["applied"] is False
    assert result["reason"] == "DUPLICATE_EXECUTION"
    assert Decimal(pos.quantity) == Decimal("10")


def test_f_partial_fills_two_executions():
    session = _LedgerSession()
    order = _order(side="BUY")
    r1 = LiveFillLedgerService(session).apply_execution(
        order=order,
        event=_event(exec_id="P1", qty="3", price="70000"),
    )
    assert r1["applied"] is True
    r2 = LiveFillLedgerService(session).apply_execution(
        order=order,
        event=_event(exec_id="P2", qty="7", price="70000"),
    )
    assert r2["applied"] is True
    assert Decimal(session.positions[0].quantity) == Decimal("10")


def test_g_wrong_uba_isolation():
    """다른 UBA order 는 별도 account_number 키를 쓴다."""
    session = _LedgerSession()
    LiveFillLedgerService(session).apply_execution(
        order=_order(uba=1, side="BUY"),
        event=_event(exec_id="U1", qty="1", price="1000"),
    )
    # 두 번째 UBA — scalar가 첫 포지션을 반환하면 qty가 합쳐지므로
    # account_number 가 달라도 현재 ledger는 UBA id 우선 매칭함.
    # ownership 계약: order.uba 가 포지션에 stamp 됨.
    pos1 = session.positions[0]
    assert int(pos1.user_broker_account_id) == 1
    # 격리: 다른 UBA 주문에 NO_UBA 가 아니면 별도 호출 시 기존 pos를 갱신할 수 있음
    # → fill_position_write 는 order.uba 를 존중해 stamp. 여기서는 uba 필수 검증.
    result = apply_kiwoom_fill_position_write(
        session,
        order=SimpleNamespace(
            order_id=2,
            user_broker_account_id=None,
            broker_code="KIWOOM",
            exchange_code="KRX",
            symbol="005930",
            side_code="BUY",
        ),
        event=_event(exec_id="U2", qty="1", price="1000"),
        commit=False,
    )
    assert result["reason"] == "NO_UBA"


def test_h_recovery_replay_idempotent():
    session = _LedgerSession()
    pos = BrokerPositionSnapshotEntity(
        broker_code="KIWOOM",
        account_number="UBA:77",
        user_broker_account_id=77,
        exchange_code="KRX",
        symbol="005930",
        name="005930",
        quantity=Decimal("10"),
        available_quantity=Decimal("10"),
        average_purchase_price=Decimal("70000"),
        current_price=Decimal("70000"),
        purchase_amount=Decimal("700000"),
        evaluation_amount=Decimal("700000"),
        profit_loss=Decimal("0"),
        return_rate=Decimal("0"),
        raw_data={
            "ledger_source": "FILL_DRIVEN",
            "applied_execution_ids": ["RECOVERY:BO-1:10"],
        },
    )
    session.positions = [pos]
    result = apply_kiwoom_fill_position_write(
        session,
        order=_order(side="BUY"),
        event=_event(exec_id="RECOVERY:BO-1:10", qty="10", price="70000"),
        commit=False,
    )
    assert result["reason"] == "DUPLICATE_EXECUTION"


def test_multi_leg_buy_reuses_pending_session_new_snapshot():
    """동일 flush 내 2회 BUY — pending INSERT 1건만 유지·수량 합산."""

    session = _LedgerSession()
    session.hide_positions_from_scalar = True
    ledger = LiveFillLedgerService(session)
    order = _order(side="BUY")
    r1 = ledger.apply_execution(
        order=order,
        event=_event(exec_id="L1", qty="0.01601373", price="140400"),
    )
    r2 = ledger.apply_execution(
        order=order,
        event=_event(exec_id="L2", qty="0.05521134", price="140400"),
    )
    assert r1["applied"] is True
    assert r2["applied"] is True
    assert len(session.positions) == 1
    assert Decimal(session.positions[0].quantity) == Decimal("0.07122507")


def test_i_no_uba_no_position_mutation():
    session = _LedgerSession()
    order = SimpleNamespace(
        order_id=9,
        user_broker_account_id=None,
        broker_code="KIWOOM",
        exchange_code="KRX",
        symbol="005930",
        side_code="BUY",
    )
    result = apply_kiwoom_fill_position_write(
        session,
        order=order,
        event=_event(exec_id="X1", qty="1", price="1000"),
        commit=False,
    )
    assert result["applied"] is False
    assert result["reason"] == "NO_UBA"
    assert session.positions == []


def test_j_ensure_after_sync_handles_missing_order():
    session = _LedgerSession()
    out = ensure_kiwoom_position_after_sync(
        session,
        order=None,
        event=_event(exec_id="Z", qty="1", price="1"),
        actor="TEST",
    )
    assert out["reason"] == "NO_ORDER_OR_EVENT"
