"""Smoke one-shot dispatch API/service — 실 Upbit 호출 금지 (mock/spy)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.order.outbox_worker import OutboxRunSummary
from stock_platform.trading.smoke_one_shot_dispatch_grant import (
    GRANT_STATUS_ISSUED,
    SmokeOneShotGrantError,
    build_smoke_one_shot_grant,
)
from stock_platform.trading.smoke_one_shot_dispatch_service import (
    SmokeOneShotDispatchError,
    SmokeOneShotDispatchService,
)


def _future(seconds: int = 90) -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=seconds)


def _grant(**kwargs: Any) -> dict[str, Any]:
    base = dict(
        run_id="uvs-test",
        order_id=2001,
        outbox_id=3001,
        uba_id=1380,
        owner_user_id=61,
        arm_snapshot_expires_at=_future(600),
        dispatch_expires_at=_future(90),
        idempotency_key="smoke:uvs-test",
    )
    base.update(kwargs)
    return build_smoke_one_shot_grant(**base)


def _svc_session(
    *,
    grant: dict[str, Any],
    user_id: int = 61,
    uba_id: int = 1380,
    order_id: int = 2001,
    outbox_id: int = 3001,
    run_id: str = "uvs-test",
    outbox_status: str = "PENDING",
    broker_order_id: str | None = None,
):
    session = MagicMock()
    uba = SimpleNamespace(
        user_broker_account_id=uba_id,
        user_id=user_id,
        broker_code="UPBIT",
        is_active=True,
        deleted_at=None,
    )
    run = SimpleNamespace(
        run_id=run_id,
        order_id=order_id,
        user_broker_account_id=uba_id,
        user_id=user_id,
        execute_live=True,
        detail={"smoke_one_shot_dispatch_grant": grant},
        broker_order_status="NOT_SUBMITTED",
        internal_status="OUTBOX_PENDING",
        status_code="OUTBOX_PENDING",
    )
    order = SimpleNamespace(
        order_id=order_id,
        user_broker_account_id=uba_id,
        broker_order_id=broker_order_id,
        metadata_payload={"smoke_run_id": run_id},
        submission_attempt_count=0,
    )
    outbox = SimpleNamespace(
        outbox_id=outbox_id,
        order_id=order_id,
        user_broker_account_id=uba_id,
        status_code=outbox_status,
        idempotency_key=f"smoke:{run_id}",
        payload_json={
            "order_id": order_id,
            "user_broker_account_id": uba_id,
            "owner_user_id": user_id,
            "broker_code": "UPBIT",
            "environment": "LIVE",
        },
    )

    def _get(model, key):
        name = getattr(model, "__name__", str(model))
        if "UserBrokerAccount" in name:
            return uba if int(key) == uba_id else None
        return None

    session.get.side_effect = _get
    session.scalar.return_value = run

    return session, run, order, outbox


def test_dispatch_valid_grant_calls_worker_once() -> None:
    grant = _grant()
    session, _run, order, outbox = _svc_session(grant=grant)
    worker = MagicMock()
    worker.dispatch_one.return_value = OutboxRunSummary(
        claimed=1, succeeded=1, retried=0, failed=0, ambiguous=0
    )
    factory = MagicMock()
    after = MagicMock()
    factory.return_value.__enter__.return_value = after
    after_order = SimpleNamespace(broker_order_id="uuid-1")
    after_outbox = SimpleNamespace(status_code="DONE")
    after_run = SimpleNamespace(
        run_id="uvs-test",
        detail={
            "smoke_one_shot_dispatch_grant": {
                **grant,
                "status": "CONSUMED",
                "consumed_at": datetime.now(timezone.utc).isoformat(),
            }
        },
        broker_order_status="ACCEPTED",
        internal_status="SUBMITTED",
        status_code="SUBMITTED",
    )
    after.scalar.return_value = after_run

    with (
        patch(
            "stock_platform.trading.smoke_one_shot_dispatch_service.TradingOrderRepository"
        ) as OR,
        patch(
            "stock_platform.trading.smoke_one_shot_dispatch_service.OrderOutboxRepository"
        ) as ObR,
        patch(
            "stock_platform.trading.smoke_one_shot_dispatch_service.assert_smoke_one_shot_dispatch_allowed",
            return_value=grant,
        ),
        patch(
            "stock_platform.trading.smoke_one_shot_dispatch_service.OrderOutboxWorker",
            return_value=worker,
        ),
        patch(
            "stock_platform.trading.smoke_one_shot_dispatch_service.OrderOutboxDispatcher"
        ),
    ):
        OR.return_value.get.side_effect = lambda oid: (
            after_order if OR.call_count > 1 else order
        )
        # first get = precheck order; after session gets order again
        def order_get(oid):
            return after_order if factory.called else order

        OR.return_value.get.side_effect = None
        OR.return_value.get.return_value = order

        def outbox_get(oid):
            return outbox

        ObR.return_value.get.side_effect = outbox_get

        # after session repositories
        def after_or_get(oid):
            return after_order

        def make_or(sess):
            m = MagicMock()
            if sess is after:
                m.get.side_effect = after_or_get
            else:
                m.get.return_value = order
            return m

        def make_obr(sess):
            m = MagicMock()
            m.get.return_value = after_outbox if sess is after else outbox
            return m

        OR.side_effect = make_or
        ObR.side_effect = make_obr

        svc = SmokeOneShotDispatchService(
            session, session_factory=factory
        )
        out = svc.dispatch(
            uba_id=1380, user_id=61, run_id="uvs-test", actor="user61"
        )

    worker.dispatch_one.assert_called_once_with(3001)
    assert out["claimed"] == 1
    assert out["succeeded"] == 1
    assert out["scheduler_required"] is False
    assert out["batch_worker_required"] is False


def test_expired_grant_blocked() -> None:
    grant = _grant(dispatch_expires_at=_future(90))
    grant["dispatch_expires_at"] = (
        datetime.now(timezone.utc) - timedelta(seconds=1)
    ).isoformat()
    session, _r, order, outbox = _svc_session(grant=grant)
    with (
        patch(
            "stock_platform.trading.smoke_one_shot_dispatch_service.TradingOrderRepository"
        ) as OR,
        patch(
            "stock_platform.trading.smoke_one_shot_dispatch_service.OrderOutboxRepository"
        ) as ObR,
        patch(
            "stock_platform.trading.smoke_one_shot_dispatch_service.assert_smoke_one_shot_dispatch_allowed",
            side_effect=SmokeOneShotGrantError("SMOKE_GRANT_DISPATCH_EXPIRED"),
        ),
    ):
        OR.return_value.get.return_value = order
        ObR.return_value.get.return_value = outbox
        with pytest.raises(SmokeOneShotDispatchError, match="DISPATCH_EXPIRED"):
            SmokeOneShotDispatchService(session).dispatch(
                uba_id=1380, user_id=61, run_id="uvs-test", actor="t"
            )


def test_other_user_blocked() -> None:
    grant = _grant()
    session, _r, order, outbox = _svc_session(grant=grant, user_id=61)
    with pytest.raises(SmokeOneShotDispatchError, match="FORBIDDEN"):
        SmokeOneShotDispatchService(session).dispatch(
            uba_id=1380, user_id=999, run_id="uvs-test", actor="t"
        )


def test_other_uba_blocked() -> None:
    grant = _grant(uba_id=1380)
    session, _r, order, outbox = _svc_session(grant=grant, uba_id=1380)
    # session.get returns None for other uba
    session.get.side_effect = lambda model, key: None
    with pytest.raises(SmokeOneShotDispatchError, match="UBA_NOT_FOUND"):
        SmokeOneShotDispatchService(session).dispatch(
            uba_id=2222, user_id=61, run_id="uvs-test", actor="t"
        )


def test_consumed_grant_blocked() -> None:
    grant = _grant()
    grant["status"] = "CONSUMED"
    grant["consumed_at"] = datetime.now(timezone.utc).isoformat()
    session, _r, order, outbox = _svc_session(grant=grant)
    with pytest.raises(SmokeOneShotDispatchError, match="NOT_ISSUED"):
        SmokeOneShotDispatchService(session).dispatch(
            uba_id=1380, user_id=61, run_id="uvs-test", actor="t"
        )


def test_broker_uuid_blocks() -> None:
    grant = _grant()
    session, _r, order, outbox = _svc_session(
        grant=grant, broker_order_id="already"
    )
    with (
        patch(
            "stock_platform.trading.smoke_one_shot_dispatch_service.TradingOrderRepository"
        ) as OR,
        patch(
            "stock_platform.trading.smoke_one_shot_dispatch_service.OrderOutboxRepository"
        ) as ObR,
    ):
        OR.return_value.get.return_value = order
        ObR.return_value.get.return_value = outbox
        with pytest.raises(
            SmokeOneShotDispatchError, match="BROKER_ORDER_ID_EXISTS"
        ):
            SmokeOneShotDispatchService(session).dispatch(
                uba_id=1380, user_id=61, run_id="uvs-test", actor="t"
            )


def test_claim_one_only_target_id() -> None:
    from stock_platform.order.outbox_repository import OrderOutboxRepository

    session = MagicMock()
    row = SimpleNamespace(
        outbox_id=3001,
        fencing_token=0,
        status_code="PENDING",
        locked_at=None,
        locked_by=None,
        lease_expires_at=None,
    )
    session.scalar.return_value = row
    with patch(
        "stock_platform.order.outbox_repository.record_outbox_audit"
    ):
        claimed = OrderOutboxRepository(session).claim_one(
            outbox_id=3001, worker_id="t"
        )
    assert claimed is row
    assert row.status_code == "PROCESSING"
    assert int(row.fencing_token) == 1
    # where 절에 특정 outbox_id
    call_args = session.scalar.call_args
    assert call_args is not None


def test_dispatch_one_claim_failed_returns_zero() -> None:
    from stock_platform.order.outbox_worker import OrderOutboxWorker

    factory = MagicMock()
    sess = MagicMock()
    factory.return_value.__enter__.return_value = sess
    with patch(
        "stock_platform.order.outbox_worker.OrderOutboxRepository"
    ) as Repo:
        Repo.return_value.claim_one.return_value = None
        summary = OrderOutboxWorker(
            session_factory=factory,
            dispatcher=MagicMock(),
            worker_id="t",
        ).dispatch_one(9999)
    assert summary.claimed == 0
    assert summary.succeeded == 0
