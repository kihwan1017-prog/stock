"""AMBIGUOUS CONFIRMED_NOT_SUBMITTED resolution — adapter/POST 0회 단위 테스트."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.broker.upbit.exceptions import (
    UpbitNetworkError,
    UpbitOrderNotFoundError,
)
from stock_platform.order.ambiguous_not_submitted_resolution_service import (
    REASON_CODE_RESOLUTION,
    RESOLUTION,
    AmbiguousNotSubmittedResolutionError,
    AmbiguousNotSubmittedResolutionService,
)
from stock_platform.order.models import OrderStatus
from stock_platform.order.outbox_models import OutboxStatus
from stock_platform.order.unsubmitted_live_order_retire_service import (
    OUTBOX_ERROR,
    UnsubmittedLiveOrderRetireError,
    UnsubmittedLiveOrderRetireService,
)


def _order(**kwargs):
    base = dict(
        order_id=1684,
        client_order_id="ORD-TEST-1684",
        client_order_identifier=None,  # factory 복원 경로 검증
        submission_generation=1,
        status_code=OrderStatus.PENDING.value,
        broker_order_id=None,
        submission_attempt_count=0,
        user_broker_account_id=1380,
        account_id=None,
        broker_code="UPBIT",
        exchange_code="UPBIT",
        symbol="KRW-XRP",
        side_code="BUY",
        order_quantity=Decimal("3.46020761"),
        order_price=Decimal("1445"),
        metadata_payload={"environment": "LIVE"},
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def _outbox(**kwargs):
    base = dict(
        outbox_id=1121,
        order_id=1684,
        event_type="SUBMIT_ORDER",
        status_code=OutboxStatus.AMBIGUOUS.value,
        dispatch_intent_at=datetime.now(timezone.utc),
        locked_at=None,
        locked_by=None,
        lease_expires_at=None,
        processed_at=None,
        ambiguous_at=datetime.now(timezone.utc),
        last_error=(
            "RETRY_BLOCKED_AFTER_INTENT:"
            "Upbit minimum order amount is 5000 KRW, got 4999.99999645"
        ),
        manual_review_reason=None,
        confirmation_status="BROKER_CONFIRMATION_REQUIRED",
        payload_json={
            "environment": "LIVE",
            "broker_code": "UPBIT",
            "user_broker_account_id": 1380,
        },
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def _service(
    order,
    outbox,
    *,
    attempt_exists=False,
    audit_exists=False,
    upbit_lookup=None,
):
    session = MagicMock()
    lookup = upbit_lookup
    if lookup is None:

        def _not_found(_identifier: str):
            raise UpbitOrderNotFoundError("not found")

        lookup = _not_found

    svc = AmbiguousNotSubmittedResolutionService(
        session, upbit_order_lookup=lookup
    )
    svc._orders = MagicMock()
    svc._orders.get.return_value = order
    svc._find_submit_outbox = lambda _oid: outbox  # type: ignore[method-assign]
    svc._has_broker_submit_audit = lambda _oid: audit_exists  # type: ignore[method-assign]
    svc._linked_run_ids = lambda _oid: ["uvs-ca01cf7c4b6a4cd2"]  # type: ignore[method-assign]
    svc._consume_grants = MagicMock()  # type: ignore[method-assign]

    def scalar(_stmt):
        return 1 if attempt_exists else None

    session.scalar.side_effect = scalar
    # OUTBOX_DISPATCH_AMBIGUOUS 조회 등 — MagicMock list() 무한루프 방지
    session.scalars.return_value = []
    return svc, session


def test_preview_resolvable_ok() -> None:
    svc, _ = _service(_order(), _outbox())
    preview = svc.preview(1684)
    assert preview.resolvable is True
    assert preview.blockers == []
    assert preview.resolution == RESOLUTION
    assert preview.reason_code == REASON_CODE_RESOLUTION
    assert "minimum order amount" in (preview.local_failure_evidence or "").lower()


def test_block_submission_attempt_count() -> None:
    svc, _ = _service(_order(submission_attempt_count=1), _outbox())
    assert "submission_attempt_not_zero" in svc.preview(1684).blockers


def test_block_submission_attempt_row() -> None:
    svc, _ = _service(_order(), _outbox(), attempt_exists=True)
    assert "submission_attempt_row_exists" in svc.preview(1684).blockers


def test_block_broker_uuid() -> None:
    svc, _ = _service(_order(broker_order_id="uuid-present"), _outbox())
    assert "broker_order_id_present" in svc.preview(1684).blockers


def test_block_broker_submit_audit() -> None:
    svc, _ = _service(_order(), _outbox(), audit_exists=True)
    assert "broker_submit_audit_present" in svc.preview(1684).blockers


def test_block_without_local_failure_evidence() -> None:
    svc, _ = _service(
        _order(),
        _outbox(last_error="RETRY_BLOCKED_AFTER_INTENT:timeout mystery"),
    )
    assert "local_pre_send_failure_not_proven" in svc.preview(1684).blockers


def test_block_broker_order_found() -> None:
    svc, _ = _service(
        _order(),
        _outbox(),
        upbit_lookup=lambda _i: {"uuid": "found-uuid", "state": "wait"},
    )
    with pytest.raises(AmbiguousNotSubmittedResolutionError) as exc:
        svc.resolve_and_retire(1684, reason="try", actor="admin")
    assert "broker_order_found" in exc.value.blockers


def test_block_broker_lookup_timeout_still_ambiguous() -> None:
    def boom(_i: str):
        raise UpbitNetworkError("timeout")

    svc, _ = _service(_order(), _outbox(), upbit_lookup=boom)
    with pytest.raises(AmbiguousNotSubmittedResolutionError) as exc:
        svc.resolve_and_retire(1684, reason="try", actor="admin")
    assert "STILL_AMBIGUOUS" in exc.value.blockers
    assert exc.value.code == "STILL_AMBIGUOUS"


def test_regular_retire_still_blocks_ambiguous() -> None:
    """일반 retire API 게이트는 AMBIGUOUS를 계속 차단."""

    order = _order()
    outbox = _outbox()
    session = MagicMock()
    retire = UnsubmittedLiveOrderRetireService(session)
    retire._orders = MagicMock()
    retire._orders.get.return_value = order
    retire._find_submit_outbox = lambda _oid: outbox  # type: ignore[method-assign]
    retire._has_broker_submit_audit = lambda _oid: False  # type: ignore[method-assign]
    session.scalar.return_value = None
    preview = retire.preview(1684)
    assert preview.retirable is False
    assert "outbox_not_pending" in preview.blockers
    assert "dispatch_intent_present" in preview.blockers
    assert "outbox_ambiguous_or_review" in preview.blockers
    with pytest.raises(UnsubmittedLiveOrderRetireError):
        retire.retire(1684, reason="should fail", actor="admin")


def test_resolve_success_no_create_order_no_post(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order = _order()
    outbox = _outbox()
    create_order_calls: list[str] = []
    post_calls: list[str] = []

    def boom_create(*_a, **_k):
        create_order_calls.append("create_order")
        raise AssertionError("create_order must not run")

    def boom_post(*_a, **_k):
        post_calls.append("POST")
        raise AssertionError("POST /v1/orders must not run")

    monkeypatch.setattr(
        "stock_platform.broker.upbit.order_client.UpbitOrderRestClient.create_order",
        boom_create,
        raising=False,
    )
    monkeypatch.setattr(
        "stock_platform.broker.upbit.order_client.UpbitOrderRestClient._request",
        boom_post,
        raising=False,
    )

    svc, session = _service(_order(), outbox)

    def change_status(*, entity, new_status, commit=True, **kwargs):
        entity.status_code = new_status.value
        return entity

    svc._orders.change_status.side_effect = change_status

    with (
        patch(
            "stock_platform.order.live_safety_audit.emit_live_safety_audit"
        ) as emit,
        patch.object(
            UnsubmittedLiveOrderRetireService,
            "_sync_linked_validation_runs",
            return_value=["uvs-ca01cf7c4b6a4cd2"],
        ),
    ):
        result = svc.resolve_and_retire(
            1684, reason="confirmed not submitted", actor="admin"
        )

    assert result["ok"] is True
    assert result["idempotent"] is False
    assert result["resolution"] == RESOLUTION
    assert result["reason_code"] == REASON_CODE_RESOLUTION
    assert result["order_status"] == "CANCELLED"
    assert result["outbox_status"] == "FAILED"
    assert result["broker_api_calls"] == 0
    assert result["create_order_calls"] == 0
    assert create_order_calls == []
    assert post_calls == []
    assert outbox.status_code == OutboxStatus.FAILED.value
    assert REASON_CODE_RESOLUTION in str(outbox.last_error)
    assert str(outbox.last_error).startswith(OUTBOX_ERROR)
    assert outbox.confirmation_status == "CONFIRMED_ABSENT"
    emit.assert_called_once()
    assert emit.call_args.kwargs["event_type"] == (
        "AMBIGUOUS_CONFIRMED_NOT_SUBMITTED"
    )
    svc._consume_grants.assert_called_once()
    session.commit.assert_not_called()


def test_idempotent_already_resolved() -> None:
    order = _order(status_code=OrderStatus.CANCELLED.value)
    outbox = _outbox(
        status_code=OutboxStatus.FAILED.value,
        last_error=f"{OUTBOX_ERROR}:{REASON_CODE_RESOLUTION}:done",
    )
    svc, _ = _service(order, outbox)
    with patch.object(
        UnsubmittedLiveOrderRetireService,
        "_sync_linked_validation_runs",
        return_value=["uvs-1"],
    ):
        result = svc.resolve_and_retire(
            1684, reason="again", actor="admin"
        )
    assert result["idempotent"] is True
    assert result["resolution"] == RESOLUTION
    svc._orders.change_status.assert_not_called()


def test_requires_reason() -> None:
    svc, _ = _service(_order(), _outbox())
    with pytest.raises(AmbiguousNotSubmittedResolutionError) as exc:
        svc.resolve_and_retire(1684, reason="  ", actor="admin")
    assert exc.value.code == "reason_required"
