"""STEP 8-9A — Upbit Live Tracking (Fake Adapter, 실주문 금지)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.trading.upbit_live_smoke_constants import (
    BrokerOrderStatus,
    InternalStatus,
    mask_broker_uuid,
    smoke_broker_identifier,
)
from stock_platform.trading.upbit_live_tracking_service import (
    UpbitLiveTrackingService,
    map_broker_raw_status,
)


class FakeProbe:
    """Mock Upbit Adapter — create_order 최대 1회, get/cancel 제어."""

    def __init__(self) -> None:
        self.create_calls = 0
        self.get_calls = 0
        self.cancel_calls = 0
        self.orders: dict[str, SimpleNamespace] = {}
        self.by_identifier: dict[str, str] = {}
        self.get_raises: Exception | None = None
        self.cancel_mode = "ok"  # ok | timeout | reject

    def register(
        self,
        *,
        uuid: str,
        identifier: str,
        status: str = "wait",
        filled: str = "0",
    ) -> None:
        self.orders[uuid] = SimpleNamespace(
            accepted=True,
            broker_order_id=uuid,
            status=SimpleNamespace(value=status),
            reject_code=None,
            filled_quantity=Decimal(filled),
            avg_fill_price=Decimal("500"),
            paid_fee=Decimal("1"),
        )
        self.by_identifier[identifier] = uuid

    def get_order(self, broker_order_id: str, **kwargs):
        self.get_calls += 1
        if self.get_raises:
            raise self.get_raises
        identifier = kwargs.get("identifier")
        if identifier:
            uuid = self.by_identifier.get(str(identifier))
            if not uuid:
                return SimpleNamespace(
                    accepted=False,
                    broker_order_id=None,
                    status=SimpleNamespace(value="FAILED"),
                    reject_code="NOT_FOUND",
                )
            return self.orders[uuid]
        if broker_order_id in self.orders:
            return self.orders[broker_order_id]
        return SimpleNamespace(
            accepted=False,
            broker_order_id=broker_order_id,
            status=SimpleNamespace(value="FAILED"),
            reject_code="NOT_FOUND",
        )

    def cancel_order(self, broker_order_id: str, **kwargs):
        self.cancel_calls += 1
        if self.cancel_mode == "timeout":
            raise TimeoutError("cancel timeout")
        if self.cancel_mode == "reject":
            return SimpleNamespace(
                accepted=False,
                broker_order_id=broker_order_id,
                status=SimpleNamespace(value="REJECTED"),
                reject_code="CANCEL_REJECT",
            )
        order = self.orders.get(broker_order_id)
        if order:
            order.status = SimpleNamespace(value="cancel")
        return SimpleNamespace(
            accepted=True,
            broker_order_id=broker_order_id,
            status=SimpleNamespace(value="cancel"),
            reject_code=None,
        )


def _run(**overrides):
    base = dict(
        run_id="uvs-test001",
        user_id=1,
        user_broker_account_id=7,
        market="KRW-XRP",
        side_code="BUY",
        amount=Decimal("5000"),
        quantity=Decimal("10"),
        limit_price=Decimal("500"),
        execute_live=True,
        status_code=InternalStatus.OUTBOX_PENDING.value,
        internal_status=InternalStatus.OUTBOX_PENDING.value,
        broker_order_status=BrokerOrderStatus.NOT_SUBMITTED.value,
        broker_identifier=smoke_broker_identifier("uvs-test001"),
        broker_order_uuid=None,
        order_id=101,
        submission_attempt_count=0,
        track_attempt_count=0,
        last_broker_query_at=None,
        status_confirmed_at=None,
        next_track_at=None,
        watch_deadline_at=datetime.now(timezone.utc) + timedelta(seconds=60),
        filled_quantity=None,
        avg_fill_price=None,
        filled_amount=None,
        fee_amount=None,
        manual_review_required=False,
        correlation_id="uvs-test001",
        failure_code=None,
        detail={},
        completed_at=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture
def session():
    s = MagicMock()
    s.scalars.return_value.first.return_value = None
    s.scalars.return_value.all.return_value = []
    return s


def test_outbox_pending_is_not_broker_accepted() -> None:
    run = _run()
    assert run.internal_status == InternalStatus.OUTBOX_PENDING.value
    assert run.broker_order_status == BrokerOrderStatus.NOT_SUBMITTED.value
    assert run.internal_status != "ORDER_ACCEPTED"
    assert run.broker_order_status != BrokerOrderStatus.ACCEPTED.value


def test_attach_sets_identifier_and_outbox_pending(session) -> None:
    probe = FakeProbe()
    svc = UpbitLiveTrackingService(session, probe=probe)
    run = _run(broker_identifier=None)
    with patch(
        "stock_platform.trading.upbit_live_tracking_service.emit_live_safety_audit"
    ), patch(
        "stock_platform.trading.upbit_live_tracking_service.emit_live_order_telegram"
    ):
        svc.attach_after_execution(run, order_id=101, actor="t")
    assert run.broker_identifier == "live-smoke:uvs-test001"
    assert run.internal_status == InternalStatus.OUTBOX_PENDING.value
    assert run.broker_order_status == BrokerOrderStatus.NOT_SUBMITTED.value


def test_uuid_saved_and_broker_lookup(session) -> None:
    probe = FakeProbe()
    probe.register(
        uuid="uuid-1", identifier="live-smoke:uvs-test001", status="wait"
    )
    run = _run(broker_order_uuid=None)
    svc = UpbitLiveTrackingService(session, probe=probe)
    with patch(
        "stock_platform.trading.upbit_live_tracking_service.emit_live_safety_audit"
    ), patch(
        "stock_platform.trading.upbit_live_tracking_service.emit_live_order_telegram"
    ):
        view = svc.resolve_by_identifier(run, actor="t")
    assert run.broker_order_uuid == "uuid-1"
    assert run.broker_order_status == BrokerOrderStatus.OPEN.value
    assert view["internal_status"] == InternalStatus.BROKER_TRACKING.value


def test_timeout_finds_existing_order_no_resubmit(session) -> None:
    probe = FakeProbe()
    probe.register(
        uuid="uuid-t", identifier="live-smoke:uvs-test001", status="wait"
    )
    run = _run()
    svc = UpbitLiveTrackingService(session, probe=probe)
    with patch(
        "stock_platform.trading.upbit_live_tracking_service.emit_live_safety_audit"
    ), patch(
        "stock_platform.trading.upbit_live_tracking_service.emit_live_order_telegram"
    ):
        svc.mark_submission_timeout(run, actor="t")
    assert probe.create_calls == 0
    assert run.broker_order_uuid == "uuid-t"
    assert run.broker_order_status == BrokerOrderStatus.OPEN.value


def test_timeout_not_found_fail_closed(session) -> None:
    probe = FakeProbe()
    run = _run()
    svc = UpbitLiveTrackingService(session, probe=probe)
    with (
        patch(
            "stock_platform.trading.upbit_live_tracking_service.emit_live_safety_audit"
        ),
        patch(
            "stock_platform.trading.upbit_live_tracking_service.emit_live_order_telegram"
        ),
        patch(
            "stock_platform.trading.upbit_live_tracking_service.KillSwitchService"
        ),
        patch(
            "stock_platform.trading.upbit_live_tracking_service.LiveArmService"
        ),
    ):
        view = svc.mark_submission_timeout(run, actor="t")
    assert view["status"] == InternalStatus.FAILED_CLOSED.value


def test_timeout_lookup_failure_unknown(session) -> None:
    probe = FakeProbe()
    probe.get_raises = ConnectionError("down")
    run = _run()
    svc = UpbitLiveTrackingService(session, probe=probe)
    with patch(
        "stock_platform.trading.upbit_live_tracking_service.emit_live_safety_audit"
    ), patch(
        "stock_platform.trading.upbit_live_tracking_service.emit_live_order_telegram"
    ):
        view = svc.mark_submission_timeout(run, actor="t")
    assert run.broker_order_status == BrokerOrderStatus.UNKNOWN.value
    assert view["manual_review_required"] is True
    assert view["new_order_blocked"] is True


def test_unknown_blocks_new_order(session) -> None:
    run = _run(
        broker_order_status=BrokerOrderStatus.UNKNOWN.value,
        manual_review_required=True,
        completed_at=None,
    )
    session.scalars.return_value.first.return_value = run
    svc = UpbitLiveTrackingService(session, probe=FakeProbe())
    assert svc.blocks_new_order(7) is True


def test_filled_does_not_complete_before_post_fill(session) -> None:
    probe = FakeProbe()
    probe.register(
        uuid="u-f", identifier="live-smoke:uvs-test001", status="done"
    )
    run = _run(broker_order_uuid="u-f")
    svc = UpbitLiveTrackingService(session, probe=probe)
    with patch(
        "stock_platform.trading.upbit_live_tracking_service.emit_live_safety_audit"
    ), patch(
        "stock_platform.trading.upbit_live_tracking_service.emit_live_order_telegram"
    ):
        view = svc.refresh(run, actor="t")
    assert run.internal_status == InternalStatus.POST_FILL_VERIFYING.value
    assert view["status"] != InternalStatus.COMPLETED.value


def test_cancel_requested_not_canceled(session) -> None:
    probe = FakeProbe()
    probe.register(
        uuid="u-c", identifier="live-smoke:uvs-test001", status="wait"
    )
    run = _run(broker_order_uuid="u-c", order_id=101)
    svc = UpbitLiveTrackingService(session, probe=probe)
    with (
        patch(
            "stock_platform.trading.upbit_live_tracking_service.emit_live_safety_audit"
        ),
        patch(
            "stock_platform.trading.upbit_live_tracking_service.emit_live_order_telegram"
        ),
        patch.object(svc, "_enqueue_cancel", return_value=55),
    ):
        view = svc.request_cancel(run, actor="t")
    assert view["cancel_request_accepted"] is True
    assert view["cancel_completed"] is False
    assert run.broker_order_status == BrokerOrderStatus.CANCEL_PENDING.value
    assert run.internal_status != InternalStatus.CANCELED.value


def test_cancel_confirmed(session) -> None:
    probe = FakeProbe()
    probe.register(
        uuid="u-c2", identifier="live-smoke:uvs-test001", status="cancel"
    )
    run = _run(
        broker_order_uuid="u-c2",
        broker_order_status=BrokerOrderStatus.CANCEL_PENDING.value,
        internal_status=InternalStatus.CANCEL_TRACKING.value,
    )
    svc = UpbitLiveTrackingService(session, probe=probe)
    with patch(
        "stock_platform.trading.upbit_live_tracking_service.emit_live_safety_audit"
    ), patch(
        "stock_platform.trading.upbit_live_tracking_service.emit_live_order_telegram"
    ):
        view = svc.confirm_cancel_or_fail(run, actor="t")
    assert run.broker_order_status == BrokerOrderStatus.CANCELED.value
    assert view["cancel_completed"] is True


def test_cancel_before_filled_switches_to_post_fill(session) -> None:
    probe = FakeProbe()
    probe.register(
        uuid="u-cf", identifier="live-smoke:uvs-test001", status="done"
    )
    run = _run(broker_order_uuid="u-cf", order_id=101)
    svc = UpbitLiveTrackingService(session, probe=probe)
    with patch(
        "stock_platform.trading.upbit_live_tracking_service.emit_live_safety_audit"
    ), patch(
        "stock_platform.trading.upbit_live_tracking_service.emit_live_order_telegram"
    ):
        view = svc.request_cancel(run, actor="t")
    assert run.broker_order_status == BrokerOrderStatus.FILLED.value
    assert view["internal_status"] == InternalStatus.POST_FILL_VERIFYING.value


def test_cancel_failure_kill(session) -> None:
    probe = FakeProbe()
    probe.register(
        uuid="u-fail", identifier="live-smoke:uvs-test001", status="wait"
    )
    run = _run(
        broker_order_uuid="u-fail",
        broker_order_status=BrokerOrderStatus.CANCEL_PENDING.value,
        track_attempt_count=99,
    )
    svc = UpbitLiveTrackingService(session, probe=probe)
    with (
        patch(
            "stock_platform.trading.upbit_live_tracking_service.emit_live_safety_audit"
        ),
        patch(
            "stock_platform.trading.upbit_live_tracking_service.emit_live_order_telegram"
        ),
        patch(
            "stock_platform.trading.upbit_live_tracking_service.KillSwitchService"
        ) as KS,
        patch(
            "stock_platform.trading.upbit_live_tracking_service.LiveArmService"
        ) as ARM,
    ):
        view = svc.confirm_cancel_or_fail(run, actor="t")
    assert view["status"] == InternalStatus.FAILED_CLOSED.value
    KS.return_value.activate.assert_called()
    ARM.return_value.disarm.assert_called()


def test_mask_uuid() -> None:
    assert mask_broker_uuid("12345678-abcd-ef00") is not None
    assert "arm_token" not in (mask_broker_uuid("secret") or "")


def test_map_statuses() -> None:
    assert map_broker_raw_status("wait") == BrokerOrderStatus.OPEN.value
    assert map_broker_raw_status("done") == BrokerOrderStatus.FILLED.value
    assert map_broker_raw_status("cancel") == BrokerOrderStatus.CANCELED.value


def test_open_auto_cancel_on_deadline(session) -> None:
    probe = FakeProbe()
    probe.register(
        uuid="u-o", identifier="live-smoke:uvs-test001", status="wait"
    )
    run = _run(
        broker_order_uuid="u-o",
        watch_deadline_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    svc = UpbitLiveTrackingService(session, probe=probe)
    with (
        patch(
            "stock_platform.trading.upbit_live_tracking_service.emit_live_safety_audit"
        ),
        patch(
            "stock_platform.trading.upbit_live_tracking_service.emit_live_order_telegram"
        ),
        patch.object(svc, "_enqueue_cancel", return_value=1),
    ):
        view = svc.refresh(run, actor="t")
    assert view["cancel_request_accepted"] is True
    assert run.broker_order_status == BrokerOrderStatus.CANCEL_PENDING.value
