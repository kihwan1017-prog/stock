"""미전송 LIVE 주문 내부 폐기 — 브로커 API 0회 단위 테스트."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.order.models import OrderStatus
from stock_platform.order.outbox_models import OutboxStatus
from stock_platform.order.state_machine import OrderStateMachine
from stock_platform.order.unsubmitted_live_order_retire_service import (
    OUTBOX_ERROR,
    UnsubmittedLiveOrderRetireError,
    UnsubmittedLiveOrderRetireService,
)


def test_pending_to_cancelled_allowed() -> None:
    assert OrderStateMachine.can_transition(
        OrderStatus.PENDING, OrderStatus.CANCELLED
    )


def _order(**kwargs):
    base = dict(
        order_id=1679,
        client_order_id="ORD-TEST",
        status_code=OrderStatus.PENDING.value,
        broker_order_id=None,
        submission_attempt_count=0,
        user_broker_account_id=1380,
        account_id=None,
        broker_code="UPBIT",
        exchange_code="UPBIT",
        symbol="KRW-XRP",
        side_code="BUY",
        order_quantity=Decimal("3.42465753"),
        order_price=Decimal("1460"),
        metadata_payload={"environment": "LIVE"},
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def _outbox(**kwargs):
    base = dict(
        outbox_id=1116,
        order_id=1679,
        event_type="SUBMIT_ORDER",
        status_code=OutboxStatus.PENDING.value,
        dispatch_intent_at=None,
        locked_at=None,
        locked_by=None,
        processed_at=None,
        last_error=None,
        payload_json={
            "environment": "LIVE",
            "broker_code": "UPBIT",
            "user_broker_account_id": 1380,
        },
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def _service(order, outbox, *, attempt_exists=False, audit_exists=False):
    session = MagicMock()
    svc = UnsubmittedLiveOrderRetireService(session)
    svc._orders = MagicMock()
    svc._orders.get.return_value = order

    def _find(_oid):
        return outbox

    svc._find_submit_outbox = _find  # type: ignore[method-assign]
    svc._has_broker_submit_audit = lambda _oid: audit_exists  # type: ignore[method-assign]

    def scalar(stmt):
        # attempt_id select → None or 1
        return 1 if attempt_exists else None

    session.scalar.side_effect = scalar
    return svc, session


def test_preview_retirable_ok() -> None:
    svc, _ = _service(_order(), _outbox())
    preview = svc.preview(1679)
    assert preview.retirable is True
    assert preview.blockers == []
    assert preview.outbox_id == 1116


def test_block_broker_order_id() -> None:
    svc, _ = _service(_order(broker_order_id="uuid-1"), _outbox())
    preview = svc.preview(1679)
    assert preview.retirable is False
    assert "broker_order_id_present" in preview.blockers


def test_block_attempt_count() -> None:
    svc, _ = _service(_order(submission_attempt_count=1), _outbox())
    assert "submission_attempt_not_zero" in svc.preview(1679).blockers


def test_block_dispatch_intent() -> None:
    svc, _ = _service(
        _order(),
        _outbox(dispatch_intent_at=datetime.now(timezone.utc)),
    )
    assert "dispatch_intent_present" in svc.preview(1679).blockers


def test_block_paper_with_live_broker() -> None:
    # PAPER env인데 UPBIT broker면 paper 경로 아님
    svc, _ = _service(
        _order(
            metadata_payload={"environment": "PAPER"},
            user_broker_account_id=None,
            account_id=1,
            broker_code="UPBIT",
        ),
        _outbox(payload_json={"environment": "PAPER", "broker_code": "UPBIT"}),
    )
    blockers = svc.preview(1679).blockers
    assert "paper_broker_mismatch" in blockers


def test_paper_unsubmitted_retirable_ok() -> None:
    svc, _ = _service(
        _order(
            metadata_payload={"environment": "PAPER"},
            user_broker_account_id=None,
            account_id=5228,
            broker_code="PAPER",
        ),
        _outbox(
            payload_json={
                "environment": "PAPER",
                "broker_code": "PAPER",
            }
        ),
    )
    preview = svc.preview(1679)
    assert preview.retirable is True
    assert preview.blockers == []


def test_block_terminal() -> None:
    svc, _ = _service(
        _order(status_code=OrderStatus.CANCELLED.value),
        _outbox(status_code=OutboxStatus.FAILED.value),
    )
    assert "order_already_terminal" in svc.preview(1679).blockers


def test_retire_success_no_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order = _order()
    outbox = _outbox()
    svc, session = _service(order, outbox)

    changed = []

    def change_status(*, entity, new_status, commit=True, **kwargs):
        entity.status_code = new_status.value
        changed.append(new_status)
        return entity

    svc._orders.change_status.side_effect = change_status

    adapter_calls: list[str] = []

    def boom(*_a, **_k):
        adapter_calls.append("adapter")
        raise AssertionError("adapter must not be created")

    monkeypatch.setattr(
        "stock_platform.broker.factory.BrokerAdapterFactory.create",
        boom,
        raising=False,
    )

    with patch(
        "stock_platform.order.live_safety_audit.emit_live_safety_audit"
    ) as emit:
        result = svc.retire(1679, reason="test retire", actor="admin")
        emit.assert_called_once()
        assert emit.call_args.kwargs["event_type"] == (
            "UNSUBMITTED_LIVE_ORDER_RETIRED"
        )

    assert result["ok"] is True
    assert result["order_status"] == "CANCELLED"
    assert result["outbox_status"] == "FAILED"
    assert result["broker_api_calls"] == 0
    assert outbox.status_code == OutboxStatus.FAILED.value
    assert str(outbox.last_error).startswith(OUTBOX_ERROR)
    assert changed == [OrderStatus.CANCELLED]
    assert adapter_calls == []
    # commit은 API 계층 — 서비스는 flush만
    session.commit.assert_not_called()


def test_retire_requires_reason() -> None:
    svc, _ = _service(_order(), _outbox())
    with pytest.raises(UnsubmittedLiveOrderRetireError) as exc:
        svc.retire(1679, reason="  ", actor="admin")
    assert exc.value.code == "reason_required"


def test_retire_blocks_when_not_retirable() -> None:
    svc, _ = _service(_order(broker_order_id="x"), _outbox())
    with pytest.raises(UnsubmittedLiveOrderRetireError) as exc:
        svc.retire(1679, reason="no", actor="admin")
    assert "broker_order_id_present" in exc.value.blockers


def test_idempotent_already_retired_syncs_run() -> None:
    order = _order(status_code=OrderStatus.CANCELLED.value)
    outbox = _outbox(
        status_code=OutboxStatus.FAILED.value,
        last_error=f"{OUTBOX_ERROR}:done",
    )
    svc, _ = _service(order, outbox)
    with patch.object(
        svc, "_sync_linked_validation_runs", return_value=["uvs-1"]
    ) as sync:
        result = svc.retire(1679, reason="again", actor="admin")
    assert result["idempotent"] is True
    assert result["synced_run_ids"] == ["uvs-1"]
    sync.assert_called_once()
    svc._orders.change_status.assert_not_called()


def test_retire_syncs_validation_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order = _order()
    outbox = _outbox()
    svc, session = _service(order, outbox)

    def change_status(*, entity, new_status, commit=True, **kwargs):
        entity.status_code = new_status.value
        return entity

    svc._orders.change_status.side_effect = change_status
    with (
        patch(
            "stock_platform.order.live_safety_audit.emit_live_safety_audit"
        ),
        patch.object(
            svc, "_sync_linked_validation_runs", return_value=["uvs-x"]
        ) as sync,
    ):
        result = svc.retire(1679, reason="retire", actor="admin")
    assert result["synced_run_ids"] == ["uvs-x"]
    sync.assert_called_once()
    assert result["broker_api_calls"] == 0
