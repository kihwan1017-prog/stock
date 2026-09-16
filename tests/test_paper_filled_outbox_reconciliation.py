"""PAPER 체결완료 잔존 outbox reconciliation — CLASS_B 전용 단위 테스트.

MINIPC-PAPER-OUTBOX-RECON-CODE-02: allowlist 3건(outbox 1138/1139/1140,
order 1701/1702/1703)만 대상으로 하는 narrowly-scoped 서비스 검증.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.order.entities import TradingOrderEntity
from stock_platform.order.models import OrderStatus
from stock_platform.order.outbox_entities import OrderOutbox
from stock_platform.order.outbox_models import OutboxStatus
from stock_platform.order.paper_filled_outbox_reconciliation_service import (
    ALLOWED_ORDER_IDS,
    ALLOWED_OUTBOX_IDS,
    APPROVAL_PHRASE,
    CONFIRMATION_STATUS,
    OUTBOX_NOTE_PREFIX,
    PaperFilledOutboxReconciliationError,
    PaperFilledOutboxReconciliationService,
    RESOLUTION,
)


def _order(**kwargs):
    base = dict(
        order_id=1701,
        client_order_id="PAPER-ORD-1701",
        broker_order_id=None,
        submission_attempt_count=0,
        account_id=5228,
        broker_code="PAPER",
        symbol="KRW-BTC",
        status_code=OrderStatus.FILLED.value,
        filled_quantity=Decimal("2.00000000"),
        order_quantity=Decimal("2.00000000"),
        metadata_payload={"environment": "PAPER"},
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def _outbox(**kwargs):
    base = dict(
        outbox_id=1138,
        order_id=1701,
        event_type="SUBMIT_ORDER",
        status_code=OutboxStatus.PENDING.value,
        broker_code="PAPER",
        payload_json={"environment": "PAPER"},
        dispatch_intent_at=None,
        locked_at=None,
        locked_by=None,
        processed_at=None,
        last_error=None,
        confirmation_status=None,
        confirmation_checked_at=None,
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def _svc(order, outbox, *, attempt_row_found=False, broker_audits=0):
    session = MagicMock()

    def _get(model, pk):
        if model is OrderOutbox:
            return outbox if outbox is not None and int(pk) == int(outbox.outbox_id) else None
        if model is TradingOrderEntity:
            return order if order is not None and int(pk) == int(order.order_id) else None
        return None

    session.get.side_effect = _get
    session.scalar.return_value = (1 if attempt_row_found else None)

    svc = PaperFilledOutboxReconciliationService(session)
    svc._count_broker_submit_audits = MagicMock(return_value=broker_audits)  # type: ignore[method-assign]
    return svc, session


# 1. 정확한 CLASS_B eligible case
def test_preview_eligible_case() -> None:
    svc, _ = _svc(_order(), _outbox())
    preview = svc.preview(outbox_id=1138, order_id=1701)
    assert preview.resolvable is True
    assert preview.blockers == []
    assert preview.fingerprint
    assert preview.resolution == RESOLUTION


# 2. wrong environment 차단
def test_block_wrong_environment() -> None:
    svc, _ = _svc(
        _order(metadata_payload={"environment": "LIVE"}),
        _outbox(payload_json={"environment": "LIVE"}),
    )
    preview = svc.preview(outbox_id=1138, order_id=1701)
    assert preview.resolvable is False
    assert "environment_not_paper" in preview.blockers


# 3. wrong broker 차단
def test_block_wrong_broker() -> None:
    svc, _ = _svc(
        _order(broker_code="UPBIT"),
        _outbox(broker_code="UPBIT"),
    )
    preview = svc.preview(outbox_id=1138, order_id=1701)
    assert "order_broker_not_paper" in preview.blockers
    assert "outbox_broker_not_paper" in preview.blockers


# 4. outbox != PENDING 차단
def test_block_outbox_not_pending() -> None:
    svc, _ = _svc(_order(), _outbox(status_code=OutboxStatus.RETRY.value))
    preview = svc.preview(outbox_id=1138, order_id=1701)
    assert "outbox_not_pending" in preview.blockers


# 5. order != FILLED 차단
def test_block_order_not_filled() -> None:
    svc, _ = _svc(
        _order(status_code=OrderStatus.PENDING.value, filled_quantity=Decimal("0")),
        _outbox(),
    )
    preview = svc.preview(outbox_id=1138, order_id=1701)
    assert "order_not_filled" in preview.blockers


# 6. allowlist 밖 대상 차단
def test_block_outside_allowlist() -> None:
    other_order = _order(order_id=9999)
    other_outbox = _outbox(outbox_id=8888, order_id=9999)
    svc, _ = _svc(other_order, other_outbox)
    preview = svc.preview(outbox_id=8888, order_id=9999)
    assert preview.resolvable is False
    assert "outbox_not_allowlisted" in preview.blockers
    assert "order_not_allowlisted" in preview.blockers
    assert "pair_not_allowlisted" in preview.blockers


def test_allowlist_exact_membership() -> None:
    assert ALLOWED_OUTBOX_IDS == frozenset({1138, 1139, 1140})
    assert ALLOWED_ORDER_IDS == frozenset({1701, 1702, 1703})


def test_block_mismatched_pair_within_allowlist() -> None:
    # outbox_id/order_id 둘 다 개별적으로는 allowlist에 있지만 실제 짝이 아님
    svc, _ = _svc(_order(order_id=1702), _outbox(outbox_id=1138, order_id=1702))
    preview = svc.preview(outbox_id=1138, order_id=1702)
    assert "pair_not_allowlisted" in preview.blockers


# 7. approval phrase 없음 차단
def test_resolve_requires_approval_phrase() -> None:
    svc, _ = _svc(_order(), _outbox())
    with pytest.raises(PaperFilledOutboxReconciliationError) as exc:
        svc.resolve(
            outbox_id=1138,
            order_id=1701,
            approval_phrase="",
            fingerprint="x",
            actor="admin",
            reason="test",
        )
    assert exc.value.code == "approval_phrase_mismatch"


# 8. approval phrase 오류 차단
def test_resolve_rejects_wrong_approval_phrase() -> None:
    svc, _ = _svc(_order(), _outbox())
    with pytest.raises(PaperFilledOutboxReconciliationError) as exc:
        svc.resolve(
            outbox_id=1138,
            order_id=1701,
            approval_phrase="WRONG PHRASE",
            fingerprint="x",
            actor="admin",
            reason="test",
        )
    assert exc.value.code == "approval_phrase_mismatch"


def test_resolve_requires_correct_fingerprint() -> None:
    svc, _ = _svc(_order(), _outbox())
    with pytest.raises(PaperFilledOutboxReconciliationError) as exc:
        svc.resolve(
            outbox_id=1138,
            order_id=1701,
            approval_phrase=APPROVAL_PHRASE,
            fingerprint="stale-or-wrong-fingerprint",
            actor="admin",
            reason="test",
        )
    assert exc.value.code == "fingerprint_mismatch"


def _resolve_with_fresh_fingerprint(svc, outbox_id, order_id, **kwargs):
    preview = svc.preview(outbox_id=outbox_id, order_id=order_id)
    assert preview.resolvable is True
    return svc.resolve(
        outbox_id=outbox_id,
        order_id=order_id,
        approval_phrase=APPROVAL_PHRASE,
        fingerprint=preview.fingerprint,
        actor=kwargs.get("actor", "admin"),
        reason=kwargs.get("reason", "MINIPC-PAPER-OUTBOX-RECON-CODE-02 test"),
    )


# 9 & 12. FILLED order 불변 + audit 생성
def test_resolve_success_leaves_order_unchanged_and_emits_audit() -> None:
    order = _order()
    outbox = _outbox()
    svc, session = _svc(order, outbox)

    order_snapshot_status = order.status_code
    order_snapshot_filled_qty = order.filled_quantity

    with patch(
        "stock_platform.order.live_safety_audit.emit_live_safety_audit"
    ) as emit:
        result = _resolve_with_fresh_fingerprint(svc, 1138, 1701)
        emit.assert_called_once()
        assert emit.call_args.kwargs["event_type"] == (
            "ADMIN_PAPER_FILLED_OUTBOX_RESOLVED"
        )
        assert emit.call_args.kwargs["detail"]["broker_api_calls"] == 0
        assert (
            emit.call_args.kwargs["detail"]["order_execution_position_modified"]
            is False
        )

    assert result["ok"] is True
    assert result["outbox_status"] == OutboxStatus.DONE.value
    # order 필드는 서비스가 절대 건드리지 않음 — 스냅샷과 동일해야 함
    assert order.status_code == order_snapshot_status == OrderStatus.FILLED.value
    assert order.filled_quantity == order_snapshot_filled_qty
    assert outbox.status_code == OutboxStatus.DONE.value
    assert outbox.confirmation_status == CONFIRMATION_STATUS
    assert str(outbox.last_error).startswith(OUTBOX_NOTE_PREFIX)
    session.commit.assert_not_called()  # commit은 API 계층 책임 — 서비스는 flush만


# 10. execution 불변 — 서비스가 execution 모델/리포지토리를 아예 import하지 않음을 증명
def test_service_never_imports_execution_model() -> None:
    from stock_platform.order import paper_filled_outbox_reconciliation_service as mod

    module_globals = vars(mod)
    for name, value in module_globals.items():
        if name.startswith("__"):
            continue
        qualname = getattr(value, "__module__", "") or ""
        assert "execution" not in qualname.lower(), (
            f"{name} originates from an execution-related module: {qualname}"
        )
    # position 테이블도 동일하게 미참조
    for name, value in module_globals.items():
        if name.startswith("__"):
            continue
        qualname = getattr(value, "__module__", "") or ""
        assert not qualname.lower().startswith("stock_platform.position"), (
            f"{name} originates from a position-related module: {qualname}"
        )


# 11. broker API 0회 — adapter/dispatcher 생성 시도하면 즉시 실패
def test_resolve_never_creates_broker_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order = _order()
    outbox = _outbox()
    svc, _ = _svc(order, outbox)

    def boom(*_a, **_k):
        raise AssertionError("broker adapter must never be created")

    monkeypatch.setattr(
        "stock_platform.broker.factory.BrokerAdapterFactory.create",
        boom,
        raising=False,
    )

    with patch("stock_platform.order.live_safety_audit.emit_live_safety_audit"):
        result = _resolve_with_fresh_fingerprint(svc, 1138, 1701)
    assert result["broker_api_calls"] == 0


# 13. preview DB mutation 0
def test_preview_causes_no_mutation() -> None:
    order = _order()
    outbox = _outbox()
    svc, session = _svc(order, outbox)

    prev_outbox_status = outbox.status_code
    svc.preview(outbox_id=1138, order_id=1701)

    assert outbox.status_code == prev_outbox_status
    session.flush.assert_not_called()
    session.commit.assert_not_called()


# 14. 이미 terminal(DONE)이면 idempotent 처리
def test_already_resolved_is_idempotent() -> None:
    order = _order()
    outbox = _outbox(
        status_code=OutboxStatus.DONE.value,
        confirmation_status=CONFIRMATION_STATUS,
        last_error=f"{OUTBOX_NOTE_PREFIX}:PAPER_ORDER_ALREADY_FILLED:done",
    )
    svc, session = _svc(order, outbox)

    preview = svc.preview(outbox_id=1138, order_id=1701)
    assert preview.resolvable is True
    assert preview.blockers == []
    assert preview.evidence.get("already_resolved") is True

    result = svc.resolve(
        outbox_id=1138,
        order_id=1701,
        approval_phrase=APPROVAL_PHRASE,
        fingerprint=preview.fingerprint,
        actor="admin",
        reason="second attempt",
    )
    assert result["idempotent"] is True
    assert result["ok"] is True
    session.flush.assert_not_called()


def test_block_broker_order_id_present() -> None:
    svc, _ = _svc(_order(broker_order_id="should-not-exist-for-paper"), _outbox())
    preview = svc.preview(outbox_id=1138, order_id=1701)
    assert "broker_order_id_present" in preview.blockers


def test_block_fill_quantity_mismatch() -> None:
    svc, _ = _svc(
        _order(filled_quantity=Decimal("1.5"), order_quantity=Decimal("2.0")),
        _outbox(),
    )
    preview = svc.preview(outbox_id=1138, order_id=1701)
    assert "fill_quantity_mismatch" in preview.blockers


def test_block_no_fill_evidence() -> None:
    svc, _ = _svc(
        _order(filled_quantity=Decimal("0"), order_quantity=Decimal("2.0")),
        _outbox(),
    )
    preview = svc.preview(outbox_id=1138, order_id=1701)
    assert "no_fill_evidence" in preview.blockers


def test_block_submission_attempt_present() -> None:
    svc, _ = _svc(
        _order(submission_attempt_count=1), _outbox(), attempt_row_found=True
    )
    preview = svc.preview(outbox_id=1138, order_id=1701)
    assert "submission_attempt_not_zero" in preview.blockers
    assert "submission_attempt_row_exists" in preview.blockers


def test_block_broker_submit_audit_present() -> None:
    svc, _ = _svc(_order(), _outbox(), broker_audits=1)
    preview = svc.preview(outbox_id=1138, order_id=1701)
    assert "broker_submit_audit_present" in preview.blockers


def test_block_outbox_claimed() -> None:
    svc, _ = _svc(_order(), _outbox(locked_by="some-worker"))
    preview = svc.preview(outbox_id=1138, order_id=1701)
    assert "outbox_claimed" in preview.blockers


def test_resolve_blocked_raises_with_blockers() -> None:
    svc, _ = _svc(_order(broker_order_id="x"), _outbox())
    with pytest.raises(PaperFilledOutboxReconciliationError) as exc:
        svc.resolve(
            outbox_id=1138,
            order_id=1701,
            approval_phrase=APPROVAL_PHRASE,
            fingerprint="whatever",
            actor="admin",
            reason="test",
        )
    assert "broker_order_id_present" in exc.value.blockers
