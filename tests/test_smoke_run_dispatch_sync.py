"""one-shot dispatch 후 LiveValidationRun 동기화 — focused tests."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from stock_platform.order.outbox_models import OutboxStatus
from stock_platform.trading.smoke_run_dispatch_sync import (
    public_run_display_status,
    sync_live_validation_run_after_dispatch,
)
from stock_platform.trading.upbit_live_smoke_constants import (
    BrokerOrderStatus,
    InternalStatus,
)


def _run(**kwargs):
    base = dict(
        run_id="uvs-test",
        order_id=1685,
        status_code=InternalStatus.OUTBOX_PENDING.value,
        internal_status=InternalStatus.OUTBOX_PENDING.value,
        broker_order_status=BrokerOrderStatus.NOT_SUBMITTED.value,
        order_status="PENDING",
        broker_order_uuid=None,
        broker_identifier=None,
        submitted_at=None,
        watch_deadline_at=None,
        next_track_at=None,
        manual_review_required=False,
        detail={},
        updated_at=datetime.now(timezone.utc),
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def _order(**kwargs):
    base = dict(
        order_id=1685,
        status_code="ACCEPTED",
        broker_order_id="a0b431e3-4305-4547-9373-2be5a1fd61ca",
        metadata_payload={"smoke_run_id": "uvs-test"},
        user_broker_account_id=1380,
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def _outbox(**kwargs):
    base = dict(
        outbox_id=1122,
        status_code=OutboxStatus.DONE.value,
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def _sync(order, outbox, run, *, outcome=None, upbit_state=None):
    session = MagicMock()
    session.get.return_value = outbox
    session.scalar.return_value = run
    with patch(
        "stock_platform.order.repository.TradingOrderRepository.get",
        return_value=order,
    ):
        return sync_live_validation_run_after_dispatch(
            session,
            order_id=1685,
            outbox_id=1122,
            actor="test",
            outcome=outcome,
            upbit_state=upbit_state,
        )


def test_submitted_sets_tracking_not_not_submitted() -> None:
    run = _run()
    result = _sync(_order(), _outbox(), run)
    assert result["applied"] is True
    assert run.broker_order_status != BrokerOrderStatus.NOT_SUBMITTED.value
    assert run.broker_order_uuid.startswith("a0b431e3")
    assert run.internal_status == InternalStatus.BROKER_TRACKING.value
    assert run.order_status == "ACCEPTED"
    assert result["display_status"] == "SUBMITTED"


def test_uuid_present_forbids_not_submitted_display() -> None:
    assert (
        public_run_display_status(
            internal_status="OUTBOX_PENDING",
            broker_order_status="NOT_SUBMITTED",
            broker_order_uuid="uuid-1",
        )
        == "SUBMITTED"
    )


def test_wait_maps_to_open_tracking() -> None:
    run = _run()
    result = _sync(_order(), _outbox(), run, upbit_state="wait")
    assert run.broker_order_status == BrokerOrderStatus.OPEN.value
    assert run.internal_status == InternalStatus.BROKER_TRACKING.value
    assert result["display_status"] == "WAIT"


def test_filled_terminal_sync() -> None:
    run = _run()
    result = _sync(_order(), _outbox(), run, upbit_state="done")
    assert run.broker_order_status == BrokerOrderStatus.FILLED.value
    assert run.internal_status == InternalStatus.FILLED.value
    assert result["display_status"] == "FILLED"


def test_ambiguous_manual_review() -> None:
    run = _run()
    order = _order(broker_order_id=None, status_code="PENDING")
    outbox = _outbox(status_code=OutboxStatus.AMBIGUOUS.value)
    result = _sync(order, outbox, run, outcome="AMBIGUOUS")
    assert run.internal_status == InternalStatus.MANUAL_REVIEW_REQUIRED.value
    assert run.broker_order_status == (
        BrokerOrderStatus.SUBMISSION_UNKNOWN.value
    )
    assert run.manual_review_required is True
    assert result["display_status"] == "AMBIGUOUS"


def test_confirmed_not_submitted() -> None:
    run = _run()
    order = _order(broker_order_id=None, status_code="CANCELLED")
    outbox = _outbox(status_code=OutboxStatus.FAILED.value)
    result = _sync(
        order, outbox, run, outcome="CONFIRMED_NOT_SUBMITTED"
    )
    assert run.broker_order_status == BrokerOrderStatus.NOT_SUBMITTED.value
    assert run.internal_status == InternalStatus.CANCELED.value
    assert result["display_status"] == "CANCELED"


def test_idempotent_duplicate_sync() -> None:
    run = _run(
        internal_status=InternalStatus.BROKER_TRACKING.value,
        status_code=InternalStatus.BROKER_TRACKING.value,
        broker_order_status=BrokerOrderStatus.ACCEPTED.value,
        broker_order_uuid="a0b431e3-4305-4547-9373-2be5a1fd61ca",
    )
    first = _sync(_order(), _outbox(), run)
    second = _sync(_order(), _outbox(), run)
    assert first["applied"] is True
    assert second["applied"] is True
    assert run.broker_order_status != BrokerOrderStatus.NOT_SUBMITTED.value


def test_retire_display_queued_vs_not_submitted() -> None:
    assert (
        public_run_display_status(
            internal_status="OUTBOX_PENDING",
            broker_order_status="NOT_SUBMITTED",
            broker_order_uuid=None,
        )
        == "QUEUED"
    )
