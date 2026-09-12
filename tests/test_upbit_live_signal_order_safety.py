"""UPBIT LIVE signal→order dispatch + duplicate EXIT safety.

fixture/mock only. 실 UPBIT/KIWOOM API · Activation/LIVE/ARM/Runner START 금지.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.broker.live_config_gate import evaluate_live_flag_consistency
from stock_platform.broker.upbit.rules import (
    REASON_UPBIT_MIN_NOTIONAL_NOT_MET,
    UPBIT_MIN_NOTIONAL_KRW,
    describe_upbit_exit_notional,
    evaluate_upbit_min_notional,
    minimum_sellable_limit_price,
)
from stock_platform.order.execution_service import (
    OrderExecutionCommand,
    OrderExecutionService,
)
from stock_platform.order.models import OrderSide, OrderStatus, OrderType
from stock_platform.order.outbox_dispatch_safety import (
    OutboxDispatchSafetyError,
    assert_live_outbox_dispatch_safety,
)
from stock_platform.order.outbox_dispatcher import OrderOutboxDispatcher
from stock_platform.order.pre_persist_exit_gate import (
    evaluate_pre_persist_exit_gate,
)
from stock_platform.position.exit_monitor_live import has_blocking_live_exit_sell
from stock_platform.risk_engine.exit_risk import (
    REASON_NO_POSITION_TO_SELL,
    REASON_SELL_QUANTITY,
    classify_risk_reducing_exit,
    exit_sell_transaction_fence,
    is_order_outstanding_for_sell,
    load_pending_sell_quantity,
    order_counts_as_outstanding_sell,
)
from tests.test_outbox_dispatch_fail_closed import (
    CountingAdapter,
    _enter_live_pass,
    _exit_patches,
    _payload,
    _uba,
)


ZERO = Decimal("0")
UBA1380 = 1380
UBA_OTHER = 9999
HELD_XRP = Decimal("3.44827587")
SYMBOL = "KRW-XRP"


def _flags(**overrides) -> SimpleNamespace:
    base = dict(
        global_live_order_enabled=True,
        kiwoom_live_order_enabled=True,
        kiwoom_use_mock=True,
        upbit_live_order_enabled=True,
        upbit_use_mock=False,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _sell_row(
    *,
    status: str,
    qty: Decimal = HELD_XRP,
    remaining: Decimal | None = None,
    filled: Decimal = ZERO,
    broker_order_id: str | None = None,
    reason_code: str | None = None,
    metadata: dict | None = None,
    uba_id: int = UBA1380,
    broker: str = "UPBIT",
    symbol: str = SYMBOL,
):
    rem = qty if remaining is None else remaining
    return SimpleNamespace(
        status_code=status,
        order_quantity=qty,
        remaining_quantity=rem,
        filled_quantity=filled,
        broker_order_id=broker_order_id,
        reason_code=reason_code,
        metadata_payload=metadata or {},
        user_broker_account_id=uba_id,
        broker_code=broker,
        symbol=symbol,
        side_code="SELL",
    )


def _classify_with_orders(orders: list, *, qty: Decimal = HELD_XRP, uba: int = UBA1380):
    pos = SimpleNamespace(
        symbol=SYMBOL, exchange_code="UPBIT", quantity=HELD_XRP
    )
    session = MagicMock()
    session.scalars.return_value = orders
    with patch(
        "stock_platform.broker.account_repository.BrokerAccountSnapshotRepository"
    ) as Repo:
        Repo.return_value.get_active_by_uba.return_value = (object(), [pos])
        return classify_risk_reducing_exit(
            session,
            side="SELL",
            symbol=SYMBOL,
            exchange_code="UPBIT",
            quantity=qty,
            user_broker_account_id=uba,
            environment="LIVE",
            broker_code="UPBIT",
        )


# ---------------------------------------------------------------------------
# FIX #1 — broker-scoped live flags
# ---------------------------------------------------------------------------


def test_a_upbit_pass_ignores_kiwoom_mock_live_conflict() -> None:
    with patch(
        "stock_platform.broker.live_config_gate.get_settings",
        return_value=_flags(),
    ):
        result = evaluate_live_flag_consistency(broker_code="UPBIT")
    assert result.allowed is True
    assert result.code == "UPBIT_FLAGS_OK"


def test_b_upbit_live_false_blocks() -> None:
    with patch(
        "stock_platform.broker.live_config_gate.get_settings",
        return_value=_flags(upbit_live_order_enabled=False),
    ):
        result = evaluate_live_flag_consistency(broker_code="UPBIT")
    assert result.allowed is False
    assert result.code == "UPBIT_LIVE_OFF"


def test_c_upbit_mock_true_blocks() -> None:
    with patch(
        "stock_platform.broker.live_config_gate.get_settings",
        return_value=_flags(upbit_use_mock=True),
    ):
        result = evaluate_live_flag_consistency(broker_code="UPBIT")
    assert result.allowed is False
    assert result.code == "UPBIT_MOCK_LIVE_CONFLICT"


def test_d_kiwoom_live_mock_conflict_contract_preserved() -> None:
    with patch(
        "stock_platform.broker.live_config_gate.get_settings",
        return_value=_flags(),
    ):
        global_result = evaluate_live_flag_consistency()
        kiwoom_result = evaluate_live_flag_consistency(broker_code="KIWOOM")
    assert global_result.code == "LIVE_MOCK_CONFLICT"
    assert global_result.allowed is False
    assert kiwoom_result.code == "LIVE_MOCK_CONFLICT"
    assert kiwoom_result.allowed is False


def test_e_upbit_fix_does_not_grant_kiwoom_permission() -> None:
    session = MagicMock()
    with (
        patch(
            "stock_platform.broker.live_config_gate.get_settings",
            return_value=_flags(),
        ),
        patch(
            "stock_platform.broker.kiwoom.execution_env.kiwoom_global_mock_blocks_live_execution",
            return_value=True,
        ),
    ):
        with pytest.raises(OutboxDispatchSafetyError) as exc:
            assert_live_outbox_dispatch_safety(
                session,
                _payload(broker="KIWOOM", uba_id=1381),
                outbox_id=1,
            )
    assert exc.value.reason_code == "LIVE_MOCK_CONFLICT"


# ---------------------------------------------------------------------------
# FIX #2 — duplicate EXIT / outstanding SELL
# ---------------------------------------------------------------------------


def test_repeated_stop_loss_enqueues_exactly_one() -> None:
    orders: list = []
    first = _classify_with_orders(orders)
    assert first.is_risk_reducing_exit is True
    orders.append(_sell_row(status=OrderStatus.PENDING.value))
    second = _classify_with_orders(orders)
    third = _classify_with_orders(orders)
    assert second.reason_code == REASON_SELL_QUANTITY
    assert third.reason_code == REASON_SELL_QUANTITY
    assert load_pending_sell_quantity(
        MagicMock(scalars=MagicMock(return_value=orders)),
        symbol=SYMBOL,
        user_broker_account_id=UBA1380,
        paper_account_id=None,
    ) == HELD_XRP


def test_concurrent_stop_loss_serialized_to_one() -> None:
    created: list[Decimal] = []
    barrier = threading.Barrier(2)

    def worker() -> None:
        session = MagicMock()
        barrier.wait()
        with exit_sell_transaction_fence(
            session,
            user_broker_account_id=UBA1380,
            paper_account_id=None,
            symbol=SYMBOL,
            side="SELL",
        ):
            outstanding = sum(created, ZERO)
            if HELD_XRP > (HELD_XRP - outstanding):
                return
            created.append(HELD_XRP)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for item in threads:
        item.start()
    for item in threads:
        item.join(timeout=5)
    assert len(created) == 1


def test_strategy_and_exit_monitor_share_outstanding_sot() -> None:
    orders = [_sell_row(status=OrderStatus.PENDING.value)]
    session = MagicMock()
    session.scalars.return_value = orders
    clf = _classify_with_orders(orders)
    blocked = has_blocking_live_exit_sell(
        session,
        user_broker_account_id=UBA1380,
        symbol=SYMBOL,
        snapshot_synchronized_at=None,
    )
    assert clf.reason_code == REASON_SELL_QUANTITY
    assert blocked is True


def test_pending_full_sell_blocks_new_full_exit() -> None:
    orders = [_sell_row(status=OrderStatus.ACCEPTED.value)]
    clf = _classify_with_orders(orders)
    assert clf.reason_code == REASON_SELL_QUANTITY
    assert clf.pending_sell_quantity == HELD_XRP
    assert clf.sellable_quantity == ZERO


def test_partial_fill_blocks_new_full_sell() -> None:
    orders = [
        _sell_row(
            status=OrderStatus.PARTIALLY_FILLED.value,
            qty=Decimal("100"),
            remaining=Decimal("70"),
            filled=Decimal("30"),
        )
    ]
    pos = SimpleNamespace(
        symbol=SYMBOL, exchange_code="UPBIT", quantity=Decimal("100")
    )
    session = MagicMock()
    session.scalars.return_value = orders
    with patch(
        "stock_platform.broker.account_repository.BrokerAccountSnapshotRepository"
    ) as Repo:
        Repo.return_value.get_active_by_uba.return_value = (object(), [pos])
        clf = classify_risk_reducing_exit(
            session,
            side="SELL",
            symbol=SYMBOL,
            exchange_code="UPBIT",
            quantity=Decimal("100"),
            user_broker_account_id=UBA1380,
            environment="LIVE",
        )
    assert clf.reason_code == REASON_SELL_QUANTITY
    assert clf.pending_sell_quantity == Decimal("70")
    assert clf.sellable_quantity == Decimal("30")


def test_submission_unknown_blocks_new_sell() -> None:
    orders = [
        _sell_row(
            status=OrderStatus.AMBIGUOUS_SUBMISSION.value,
            broker_order_id=None,
        )
    ]
    clf = _classify_with_orders(orders)
    assert clf.reason_code == REASON_SELL_QUANTITY
    assert order_counts_as_outstanding_sell(orders[0]) is True


def test_terminal_failed_no_broker_create_allows_new_exit() -> None:
    failed = _sell_row(
        status=OrderStatus.FAILED.value,
        broker_order_id=None,
        reason_code="LIVE_MOCK_CONFLICT",
    )
    assert order_counts_as_outstanding_sell(failed) is False
    clf = _classify_with_orders([failed])
    assert clf.is_risk_reducing_exit is True
    assert clf.pending_sell_quantity == ZERO


def test_failed_with_broker_order_id_still_outstanding() -> None:
    failed = _sell_row(
        status=OrderStatus.FAILED.value,
        broker_order_id="upbit-uuid-1",
    )
    assert order_counts_as_outstanding_sell(failed) is True
    clf = _classify_with_orders([failed])
    assert clf.reason_code == REASON_SELL_QUANTITY


def test_oversell_without_pending_blocks() -> None:
    clf = _classify_with_orders([], qty=HELD_XRP + Decimal("1"))
    assert clf.reason_code == REASON_SELL_QUANTITY


def test_cross_uba_has_no_position() -> None:
    session = MagicMock()
    session.scalars.return_value = []
    with patch(
        "stock_platform.broker.account_repository.BrokerAccountSnapshotRepository"
    ) as Repo:
        Repo.return_value.get_active_by_uba.return_value = (object(), [])
        clf = classify_risk_reducing_exit(
            session,
            side="SELL",
            symbol=SYMBOL,
            exchange_code="UPBIT",
            quantity=HELD_XRP,
            user_broker_account_id=UBA_OTHER,
            environment="LIVE",
        )
    assert clf.reason_code == REASON_NO_POSITION_TO_SELL
    Repo.return_value.get_active_by_uba.assert_called_with(UBA_OTHER)


# ---------------------------------------------------------------------------
# Dispatch — UPBIT mock adapter, 실 API 없음
# ---------------------------------------------------------------------------


def test_upbit_dispatch_not_blocked_by_kiwoom_mock_conflict() -> None:
    session = MagicMock()
    adapter = CountingAdapter()
    uba = _uba(broker="UPBIT")
    patches, _ = _enter_live_pass(session, uba)
    try:
        patches[0].stop()
        with patch(
            "stock_platform.broker.live_config_gate.get_settings",
            return_value=_flags(),
        ):
            with patch(
                "stock_platform.order.outbox_dispatcher.resolve_outbox_adapter",
                return_value=adapter,
            ):
                OrderOutboxDispatcher(adapter, session=session).dispatch(
                    event_type="SUBMIT_ORDER",
                    payload=_payload(broker="UPBIT"),
                    idempotency_key="upbit-flag-scope",
                    session=session,
                    outbox_id=99,
                )
    finally:
        for item in reversed(patches[1:]):
            item.stop()
    assert adapter.submit_order_calls == 1
    assert adapter.cancel_order_calls == 0
    assert adapter.amend_order_calls == 0


def test_paper_skips_live_flag_and_exit_fence() -> None:
    session = MagicMock()
    assert_live_outbox_dispatch_safety(
        session, _payload(environment="PAPER"), outbox_id=1
    )
    session.get.assert_not_called()
    clf = classify_risk_reducing_exit(
        session,
        side="BUY",
        symbol=SYMBOL,
        exchange_code="UPBIT",
        quantity=Decimal("1"),
        paper_account_id=1,
        environment="PAPER",
    )
    assert clf.is_risk_reducing_exit is False
    assert clf.reason_code is None


# ---------------------------------------------------------------------------
# Min-notional pre-persist + ambiguous outstanding
# ---------------------------------------------------------------------------

DUST_PRICE = Decimal("1407")
SELLABLE_PRICE = Decimal("1450")


def _gate(
    *,
    price: Decimal,
    orders: list | None = None,
    qty: Decimal = HELD_XRP,
    env: str = "LIVE",
    broker: str = "UPBIT",
    order_type: str = "LIMIT",
):
    session = MagicMock()
    session.scalars.return_value = orders or []
    pos = SimpleNamespace(
        symbol=SYMBOL, exchange_code="UPBIT", quantity=HELD_XRP
    )
    with patch(
        "stock_platform.broker.account_repository.BrokerAccountSnapshotRepository"
    ) as Repo:
        Repo.return_value.get_active_by_uba.return_value = (object(), [pos])
        return evaluate_pre_persist_exit_gate(
            session,
            side="SELL",
            symbol=SYMBOL,
            exchange_code="UPBIT",
            quantity=qty,
            price=price,
            order_type=order_type,
            broker_code=broker,
            environment=env,
            user_broker_account_id=UBA1380,
            paper_account_id=None,
        )


def _ambiguous_outbox():
    return SimpleNamespace(
        status_code="AMBIGUOUS",
        confirmation_status="BROKER_CONFIRMATION_REQUIRED",
        dispatch_intent_at=datetime(2026, 8, 18, 23, 17, 12, tzinfo=timezone.utc),
        manual_review_reason=None,
    )


def test_a_dust_exit_blocks_before_persist() -> None:
    reason = _gate(price=DUST_PRICE)
    assert reason == REASON_UPBIT_MIN_NOTIONAL_NOT_MET
    view = describe_upbit_exit_notional(
        held_quantity=HELD_XRP, current_price=DUST_PRICE
    )
    assert view["below_minimum"] is True
    assert Decimal(str(view["current_notional"])) < UPBIT_MIN_NOTIONAL_KRW
    assert minimum_sellable_limit_price(HELD_XRP) == Decimal("1450")


def test_b_repeated_dust_stop_loss_creates_no_orders() -> None:
    reasons = [_gate(price=DUST_PRICE) for _ in range(3)]
    assert reasons == [REASON_UPBIT_MIN_NOTIONAL_NOT_MET] * 3


def test_c_sellable_notional_passes_min_gate() -> None:
    assert (
        evaluate_upbit_min_notional(
            broker_code="UPBIT",
            environment="LIVE",
            side="SELL",
            order_type="LIMIT",
            quantity=HELD_XRP,
            price=SELLABLE_PRICE,
        )
        is None
    )
    reason = _gate(price=SELLABLE_PRICE)
    assert reason is None


def test_d_ambiguous_first_order_blocks_second() -> None:
    row = _sell_row(status=OrderStatus.FAILED.value, broker_order_id=None)
    row.outbox = _ambiguous_outbox()
    assert is_order_outstanding_for_sell(row, row.outbox) is True
    clf = _classify_with_orders([row])
    assert clf.reason_code == REASON_SELL_QUANTITY
    reason = _gate(price=SELLABLE_PRICE, orders=[row])
    assert reason == REASON_SELL_QUANTITY


def test_e_manual_review_outbox_blocks_second() -> None:
    row = _sell_row(status=OrderStatus.FAILED.value, broker_order_id=None)
    row.outbox = SimpleNamespace(
        status_code="MANUAL_REVIEW",
        confirmation_status="BROKER_CONFIRMATION_REQUIRED",
        dispatch_intent_at=datetime(2026, 8, 18, 23, 17, 12, tzinfo=timezone.utc),
        manual_review_reason=None,
    )
    clf = _classify_with_orders([row])
    assert clf.reason_code == REASON_SELL_QUANTITY


def test_f_submission_unknown_metadata_blocks() -> None:
    orders = [
        _sell_row(
            status=OrderStatus.FAILED.value,
            broker_order_id=None,
            metadata={"submission_unknown": True},
        )
    ]
    clf = _classify_with_orders(orders)
    assert clf.reason_code == REASON_SELL_QUANTITY


def test_g_dust_rejection_does_not_permanently_lock() -> None:
    assert _gate(price=DUST_PRICE) == REASON_UPBIT_MIN_NOTIONAL_NOT_MET
    assert _gate(price=SELLABLE_PRICE) is None


def test_h_terminal_failed_definitive_no_create_allows_new_exit() -> None:
    failed = _sell_row(
        status=OrderStatus.FAILED.value,
        broker_order_id=None,
        reason_code="LIVE_MOCK_CONFLICT",
    )
    assert is_order_outstanding_for_sell(failed) is False
    reason = _gate(price=SELLABLE_PRICE, orders=[failed])
    assert reason is None


def test_h2_confirmed_absent_outbox_does_not_block_new_exit() -> None:
    """resolve-not-submitted 이후: CANCELLED + CONFIRMED_ABSENT.

    dispatch_intent_at 는 원본 증거로 보존되지만 outstanding에서 제외해야 한다.
    """

    row = _sell_row(
        status=OrderStatus.CANCELLED.value,
        broker_order_id=None,
        remaining=HELD_XRP,
    )
    row.outbox = SimpleNamespace(
        status_code="FAILED",
        confirmation_status="CONFIRMED_ABSENT",
        dispatch_intent_at=datetime(2026, 8, 18, 23, 17, 12, tzinfo=timezone.utc),
        last_error=(
            "UNSUBMITTED_LIVE_ORDER_RETIRED:"
            "BROKER_NOT_REACHED_LOCAL_VALIDATION_FAILURE:operator"
        ),
        manual_review_reason=None,
    )
    assert is_order_outstanding_for_sell(row, row.outbox) is False
    reason = _gate(price=SELLABLE_PRICE, orders=[row])
    assert reason is None


def test_i_strategy_and_exit_monitor_dust_and_sellable() -> None:
    session = MagicMock()
    session.scalars.return_value = []
    blocked = has_blocking_live_exit_sell(
        session,
        user_broker_account_id=UBA1380,
        symbol=SYMBOL,
        snapshot_synchronized_at=None,
    )
    assert blocked is False
    assert _gate(price=DUST_PRICE) == REASON_UPBIT_MIN_NOTIONAL_NOT_MET

    orders = [_sell_row(status=OrderStatus.PENDING.value)]
    session.scalars.return_value = orders
    clf = _classify_with_orders(orders)
    monitor_blocked = has_blocking_live_exit_sell(
        session,
        user_broker_account_id=UBA1380,
        symbol=SYMBOL,
        snapshot_synchronized_at=None,
    )
    assert clf.reason_code == REASON_SELL_QUANTITY
    assert monitor_blocked is True


def test_j_concurrent_two_signals_at_most_one() -> None:
    created: list[Decimal] = []
    barrier = threading.Barrier(2)

    def worker() -> None:
        session = MagicMock()
        barrier.wait()
        with exit_sell_transaction_fence(
            session,
            user_broker_account_id=UBA1380,
            paper_account_id=None,
            symbol=SYMBOL,
            side="SELL",
        ):
            if created:
                return
            created.append(HELD_XRP)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for item in threads:
        item.start()
    for item in threads:
        item.join(timeout=5)
    assert len(created) == 1


def test_k_partial_fill_no_new_full_sell() -> None:
    orders = [
        _sell_row(
            status=OrderStatus.PARTIALLY_FILLED.value,
            qty=HELD_XRP,
            remaining=Decimal("2.0"),
            filled=Decimal("1.44827587"),
        )
    ]
    clf = _classify_with_orders(orders, qty=HELD_XRP)
    assert clf.reason_code == REASON_SELL_QUANTITY
    assert clf.pending_sell_quantity == Decimal("2.0")


def test_paper_ignores_upbit_min_notional() -> None:
    assert (
        evaluate_upbit_min_notional(
            broker_code="UPBIT",
            environment="PAPER",
            side="SELL",
            order_type="LIMIT",
            quantity=HELD_XRP,
            price=DUST_PRICE,
        )
        is None
    )


def test_kiwoom_ignores_upbit_min_notional() -> None:
    assert (
        evaluate_upbit_min_notional(
            broker_code="KIWOOM",
            environment="LIVE",
            side="SELL",
            order_type="LIMIT",
            quantity=HELD_XRP,
            price=DUST_PRICE,
        )
        is None
    )


def test_market_sell_does_not_guess_price() -> None:
    assert (
        evaluate_upbit_min_notional(
            broker_code="UPBIT",
            environment="LIVE",
            side="SELL",
            order_type="MARKET",
            quantity=HELD_XRP,
            price=None,
        )
        is None
    )


def test_oes_skip_risk_still_blocks_dust_before_create() -> None:
    session = MagicMock()
    session.scalars.return_value = []
    svc = OrderExecutionService(session)
    svc._order_service.create = MagicMock()
    pos = SimpleNamespace(
        symbol=SYMBOL, exchange_code="UPBIT", quantity=HELD_XRP
    )
    command = OrderExecutionCommand(
        account_id=None,
        broker_code="UPBIT",
        exchange_code="UPBIT",
        symbol=SYMBOL,
        side=OrderSide.SELL,
        order_type=OrderType.LIMIT,
        price=DUST_PRICE,
        quantity=HELD_XRP,
        skip_risk_checks=True,
        environment="LIVE",
        user_broker_account_id=UBA1380,
        account_number="UBA:1380",
    )
    with (
        patch(
            "stock_platform.trading.upbit_24x7_control.live_outbox_queue_block_reason",
            return_value=None,
        ),
        patch.object(
            svc, "_resolve_account_ownership", return_value=(None, UBA1380)
        ),
        patch.object(
            svc, "_resolve_size", return_value=(HELD_XRP, DUST_PRICE, {})
        ),
        patch(
            "stock_platform.broker.account_repository.BrokerAccountSnapshotRepository"
        ) as Repo,
    ):
        Repo.return_value.get_active_by_uba.return_value = (object(), [pos])
        result = svc.submit(command)
    assert result.allowed is False
    assert result.reason_code == REASON_UPBIT_MIN_NOTIONAL_NOT_MET
    assert result.order_id is None
    svc._order_service.create.assert_not_called()
