"""Historical test AMBIGUOUS outbox resolution — focused unit tests."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.order.historical_test_outbox_resolution_service import (
    APPROVAL_PHRASE,
    CONFIRMATION_STATUS,
    HistoricalTestOutboxResolutionError,
    HistoricalTestOutboxResolutionService,
    RESOLUTION,
)
from stock_platform.order.models import OrderStatus
from stock_platform.order.outbox_models import OutboxStatus


def _order(**kwargs):
    base = dict(
        order_id=396,
        client_order_id="race-a093fb8df367458e",
        broker_order_id=None,
        submission_attempt_count=0,
        user_broker_account_id=None,
        account_id=1,
        broker_code="KIWOOM",
        symbol="005930",
        status_code=OrderStatus.CREATED.value,
        filled_quantity=Decimal("0"),
        filled_at=None,
        first_submitted_at=None,
        sent_at=None,
        accepted_at=None,
        strategy_id=None,
        strategy_deployment_id=None,
        account_strategy_link_id=None,
        runtime_scope_hash=None,
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def _outbox(**kwargs):
    base = dict(
        outbox_id=205,
        order_id=396,
        event_type="SUBMIT",
        status_code=OutboxStatus.AMBIGUOUS.value,
        payload_json={"test": True},
        idempotency_key="race-9993ac0aab894d2f8b453382fac83f8e",
        request_hash="26ccf2eaaace12271e0332ea38ea7255ba2a85cbfc0c43da6df2c18cc714b43a",
        client_order_id=None,
        broker_code=None,
        user_broker_account_id=None,
        dispatch_intent_at=datetime(2026, 7, 28, 11, 31, 22, tzinfo=timezone.utc),
        last_error="RETRY_BLOCKED_AFTER_INTENT:'SUBMIT' is not a valid OutboxEventType",
        confirmation_status="BROKER_CONFIRMATION_REQUIRED",
        confirmation_checked_at=None,
        manual_review_reason=None,
        ambiguous_at=datetime(2026, 7, 28, 11, 31, 22, tzinfo=timezone.utc),
        next_retry_at=None,
        locked_at=None,
        locked_by=None,
        lease_expires_at=None,
        processed_at=None,
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def _svc(order, outbox, *, attempt_rows=0, broker_audits=0):
    from stock_platform.order.entities import TradingOrderEntity
    from stock_platform.order.outbox_entities import OrderOutbox

    session = MagicMock()

    def _get(model, pk):
        if model is OrderOutbox:
            return outbox if int(pk) == int(outbox.outbox_id) else None
        if model is TradingOrderEntity:
            return order if int(pk) == int(order.order_id) else None
        return None

    session.get.side_effect = _get
    session.scalar.return_value = attempt_rows

    svc = HistoricalTestOutboxResolutionService(session)
    svc._count_broker_submit_audits = MagicMock(return_value=broker_audits)  # type: ignore[method-assign]
    svc._orders = MagicMock()
    return svc, session


def test_preview_pass_for_test_fixture() -> None:
    order, outbox = _order(), _outbox()
    svc, _ = _svc(order, outbox)
    preview = svc.preview(outbox_id=205, order_id=396)
    assert preview.resolvable is True
    assert preview.blockers == []
    assert preview.fingerprint
    assert preview.resolution == RESOLUTION


def test_block_when_broker_order_id_present() -> None:
    order, outbox = _order(broker_order_id="ABC"), _outbox()
    svc, _ = _svc(order, outbox)
    preview = svc.preview(outbox_id=205, order_id=396)
    assert preview.resolvable is False
    assert "broker_order_id_present" in preview.blockers


def test_block_when_submission_attempt() -> None:
    order, outbox = _order(submission_attempt_count=1), _outbox()
    svc, _ = _svc(order, outbox, attempt_rows=1)
    preview = svc.preview(outbox_id=205, order_id=396)
    assert "submission_attempt_present" in preview.blockers


def test_block_when_broker_submit_audit() -> None:
    order, outbox = _order(), _outbox()
    svc, _ = _svc(order, outbox, broker_audits=1)
    preview = svc.preview(outbox_id=205, order_id=396)
    assert "broker_submit_audit_present" in preview.blockers


def test_block_when_production_uba() -> None:
    order, outbox = _order(user_broker_account_id=1380), _outbox()
    svc, _ = _svc(order, outbox)
    preview = svc.preview(outbox_id=205, order_id=396)
    assert "production_uba_binding" in preview.blockers


def test_wrong_phrase_no_mutation() -> None:
    order, outbox = _order(), _outbox()
    svc, session = _svc(order, outbox)
    preview = svc.preview(outbox_id=205, order_id=396)
    with pytest.raises(HistoricalTestOutboxResolutionError) as exc:
        svc.resolve(
            outbox_id=205,
            order_id=396,
            approval_phrase="WRONG",
            fingerprint=preview.fingerprint or "",
            actor="admin",
            reason="cleanup",
        )
    assert exc.value.code == "approval_phrase_mismatch"
    svc._orders.change_status.assert_not_called()
    assert session.flush.call_count == 0


def test_fingerprint_mismatch_no_mutation() -> None:
    order, outbox = _order(), _outbox()
    svc, _ = _svc(order, outbox)
    with pytest.raises(HistoricalTestOutboxResolutionError) as exc:
        svc.resolve(
            outbox_id=205,
            order_id=396,
            approval_phrase=APPROVAL_PHRASE,
            fingerprint="0" * 64,
            actor="admin",
            reason="cleanup",
        )
    assert exc.value.code == "fingerprint_mismatch"
    svc._orders.change_status.assert_not_called()


def test_apply_terminal_and_idempotent() -> None:
    order, outbox = _order(), _outbox()
    svc, _ = _svc(order, outbox)
    preview = svc.preview(outbox_id=205, order_id=396)
    assert preview.fingerprint

    with patch(
        "stock_platform.order.live_safety_audit.emit_live_safety_audit"
    ) as emit:
        result = svc.resolve(
            outbox_id=205,
            order_id=396,
            approval_phrase=APPROVAL_PHRASE,
            fingerprint=preview.fingerprint,
            actor="admin",
            reason="resolve race fixture",
        )
    assert result["ok"] is True
    assert result["idempotent"] is False
    assert outbox.status_code == OutboxStatus.FAILED.value
    assert outbox.confirmation_status == CONFIRMATION_STATUS
    svc._orders.change_status.assert_called_once()
    assert (
        svc._orders.change_status.call_args.kwargs["new_status"]
        == OrderStatus.FAILED
    )
    emit.assert_called_once()

    # duplicate apply
    order.status_code = OrderStatus.FAILED.value
    outbox.last_error = "HISTORICAL_TEST_RESOLVED:HISTORICAL_TEST_ARTIFACT:x"
    again = svc.resolve(
        outbox_id=205,
        order_id=396,
        approval_phrase=APPROVAL_PHRASE,
        fingerprint=preview.fingerprint,
        actor="admin",
        reason="again",
    )
    assert again["idempotent"] is True
    assert again["code"] == "ALREADY_RESOLVED"
    assert svc._orders.change_status.call_count == 1


def test_production_ambiguous_not_allowlisted() -> None:
    order = _order(order_id=1684, client_order_id="ORD-LIVE", user_broker_account_id=1380)
    outbox = _outbox(
        outbox_id=1121,
        order_id=1684,
        payload_json={"environment": "LIVE"},
        idempotency_key="live-key",
    )
    svc, _ = _svc(order, outbox)
    preview = svc.preview(outbox_id=1121, order_id=1684)
    assert preview.resolvable is False
    assert "outbox_not_allowlisted" in preview.blockers
