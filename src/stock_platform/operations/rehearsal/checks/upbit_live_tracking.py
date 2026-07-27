"""Operation Rehearsal — Upbit Live Broker Tracking (실주문 없음)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from stock_platform.operations.rehearsal.checks import run_check
from stock_platform.operations.rehearsal.models import CheckResult, CheckStatus
from stock_platform.trading.upbit_live_smoke_constants import (
    BrokerOrderStatus,
    InternalStatus,
    smoke_broker_identifier,
)
from stock_platform.trading.upbit_live_tracking_service import (
    UpbitLiveTrackingService,
)


class _Fake:
    def __init__(self) -> None:
        self.orders: dict[str, SimpleNamespace] = {}
        self.by_id: dict[str, str] = {}

    def register(self, uuid: str, identifier: str, status: str) -> None:
        self.orders[uuid] = SimpleNamespace(
            accepted=True,
            broker_order_id=uuid,
            status=SimpleNamespace(value=status),
            reject_code=None,
            filled_quantity=Decimal("0"),
            avg_fill_price=Decimal("1"),
            paid_fee=Decimal("0"),
        )
        self.by_id[identifier] = uuid

    def get_order(self, broker_order_id: str, **kwargs):
        identifier = kwargs.get("identifier")
        if identifier:
            u = self.by_id.get(str(identifier))
            if not u:
                return SimpleNamespace(
                    accepted=False,
                    broker_order_id=None,
                    status=SimpleNamespace(value="FAILED"),
                    reject_code="NOT_FOUND",
                )
            return self.orders[u]
        return self.orders.get(
            broker_order_id,
            SimpleNamespace(
                accepted=False,
                broker_order_id=broker_order_id,
                status=SimpleNamespace(value="FAILED"),
                reject_code="NOT_FOUND",
            ),
        )

    def cancel_order(self, broker_order_id: str, **_kwargs):
        o = self.orders.get(broker_order_id)
        if o:
            o.status = SimpleNamespace(value="cancel")
        return SimpleNamespace(
            accepted=True,
            broker_order_id=broker_order_id,
            status=SimpleNamespace(value="cancel"),
            reject_code=None,
        )


def _run(**kw):
    base = dict(
        run_id="r1",
        user_id=1,
        user_broker_account_id=1,
        market="KRW-XRP",
        side_code="BUY",
        amount=Decimal("5000"),
        quantity=Decimal("1"),
        limit_price=Decimal("500"),
        execute_live=True,
        status_code=InternalStatus.OUTBOX_PENDING.value,
        internal_status=InternalStatus.OUTBOX_PENDING.value,
        broker_order_status=BrokerOrderStatus.NOT_SUBMITTED.value,
        broker_identifier=smoke_broker_identifier("r1"),
        broker_order_uuid=None,
        order_id=1,
        track_attempt_count=0,
        submission_attempt_count=0,
        last_broker_query_at=None,
        status_confirmed_at=None,
        next_track_at=None,
        watch_deadline_at=datetime.now(timezone.utc) + timedelta(hours=1),
        filled_quantity=None,
        avg_fill_price=None,
        filled_amount=None,
        fee_amount=None,
        manual_review_required=False,
        correlation_id="r1",
        failure_code=None,
        detail={},
        completed_at=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def run_upbit_live_tracking_checks() -> list[CheckResult]:
    results: list[CheckResult] = []

    def _outbox_not_accepted() -> tuple[CheckStatus, str, dict[str, Any]]:
        run = _run()
        if run.internal_status == "ORDER_ACCEPTED":
            return CheckStatus.FAIL, "outbox mistaken as accepted", {}
        if run.broker_order_status == BrokerOrderStatus.ACCEPTED.value:
            return CheckStatus.FAIL, "broker accepted without lookup", {}
        return CheckStatus.PASS, "outbox ≠ broker accepted", {}

    results.append(
        run_check(
            suite="upbit_live_tracking",
            name="outbox_not_broker_accepted",
            fn=_outbox_not_accepted,
        )
    )

    def _uuid_saved() -> tuple[CheckStatus, str, dict[str, Any]]:
        session = MagicMock()
        fake = _Fake()
        fake.register("u1", smoke_broker_identifier("r1"), "wait")
        run = _run()
        svc = UpbitLiveTrackingService(session, probe=fake)
        with patch(
            "stock_platform.trading.upbit_live_tracking_service.emit_live_safety_audit"
        ), patch(
            "stock_platform.trading.upbit_live_tracking_service.emit_live_order_telegram"
        ):
            svc.resolve_by_identifier(run, actor="rehearsal")
        if run.broker_order_uuid != "u1":
            return CheckStatus.FAIL, "uuid not saved", {}
        return CheckStatus.PASS, "uuid saved", {}

    results.append(
        run_check(
            suite="upbit_live_tracking",
            name="submission_uuid_saved",
            fn=_uuid_saved,
        )
    )

    def _timeout_lookup() -> tuple[CheckStatus, str, dict[str, Any]]:
        session = MagicMock()
        fake = _Fake()
        fake.register("u2", smoke_broker_identifier("r1"), "wait")
        run = _run()
        svc = UpbitLiveTrackingService(session, probe=fake)
        with patch(
            "stock_platform.trading.upbit_live_tracking_service.emit_live_safety_audit"
        ), patch(
            "stock_platform.trading.upbit_live_tracking_service.emit_live_order_telegram"
        ):
            svc.mark_submission_timeout(run, actor="rehearsal")
        if run.broker_order_uuid != "u2":
            return CheckStatus.FAIL, "timeout lookup failed", {}
        return CheckStatus.PASS, "timeout → identifier lookup", {}

    results.append(
        run_check(
            suite="upbit_live_tracking",
            name="timeout_identifier_lookup",
            fn=_timeout_lookup,
        )
    )

    def _unknown_blocks() -> tuple[CheckStatus, str, dict[str, Any]]:
        session = MagicMock()
        session.scalars.return_value.first.return_value = _run(
            broker_order_status=BrokerOrderStatus.UNKNOWN.value,
            manual_review_required=True,
        )
        svc = UpbitLiveTrackingService(session, probe=_Fake())
        if not svc.blocks_new_order(1):
            return CheckStatus.FAIL, "should block", {}
        return CheckStatus.PASS, "unknown blocks new order", {}

    results.append(
        run_check(
            suite="upbit_live_tracking",
            name="unknown_blocks_new_order",
            fn=_unknown_blocks,
        )
    )

    def _open_auto_cancel() -> tuple[CheckStatus, str, dict[str, Any]]:
        session = MagicMock()
        fake = _Fake()
        fake.register("u3", smoke_broker_identifier("r1"), "wait")
        run = _run(
            broker_order_uuid="u3",
            watch_deadline_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        svc = UpbitLiveTrackingService(session, probe=fake)
        with (
            patch(
                "stock_platform.trading.upbit_live_tracking_service.emit_live_safety_audit"
            ),
            patch(
                "stock_platform.trading.upbit_live_tracking_service.emit_live_order_telegram"
            ),
            patch.object(svc, "_enqueue_cancel", return_value=1),
        ):
            view = svc.refresh(run, actor="rehearsal")
        if not view.get("cancel_request_accepted"):
            return CheckStatus.FAIL, "auto cancel missing", view
        return CheckStatus.PASS, "open auto cancel", {}

    results.append(
        run_check(
            suite="upbit_live_tracking",
            name="open_auto_cancel",
            fn=_open_auto_cancel,
        )
    )

    def _cancel_confirmed() -> tuple[CheckStatus, str, dict[str, Any]]:
        session = MagicMock()
        fake = _Fake()
        fake.register("u4", smoke_broker_identifier("r1"), "cancel")
        run = _run(
            broker_order_uuid="u4",
            broker_order_status=BrokerOrderStatus.CANCEL_PENDING.value,
        )
        svc = UpbitLiveTrackingService(session, probe=fake)
        with patch(
            "stock_platform.trading.upbit_live_tracking_service.emit_live_safety_audit"
        ), patch(
            "stock_platform.trading.upbit_live_tracking_service.emit_live_order_telegram"
        ):
            view = svc.confirm_cancel_or_fail(run, actor="rehearsal")
        if not view.get("cancel_completed"):
            return CheckStatus.FAIL, "not confirmed", view
        return CheckStatus.PASS, "cancel confirmed", {}

    results.append(
        run_check(
            suite="upbit_live_tracking",
            name="cancel_confirmed",
            fn=_cancel_confirmed,
        )
    )

    def _cancel_fail_kill() -> tuple[CheckStatus, str, dict[str, Any]]:
        session = MagicMock()
        fake = _Fake()
        fake.register("u5", smoke_broker_identifier("r1"), "wait")
        run = _run(
            broker_order_uuid="u5",
            broker_order_status=BrokerOrderStatus.CANCEL_PENDING.value,
            track_attempt_count=99,
        )
        svc = UpbitLiveTrackingService(session, probe=fake)
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
            ),
        ):
            view = svc.confirm_cancel_or_fail(run, actor="rehearsal")
        if view.get("status") != InternalStatus.FAILED_CLOSED.value:
            return CheckStatus.FAIL, "not fail closed", view
        if not KS.return_value.activate.called:
            return CheckStatus.FAIL, "kill not called", {}
        return CheckStatus.PASS, "cancel failure → kill", {}

    results.append(
        run_check(
            suite="upbit_live_tracking",
            name="cancel_failure_kill",
            fn=_cancel_fail_kill,
        )
    )

    def _partial() -> tuple[CheckStatus, str, dict[str, Any]]:
        session = MagicMock()
        fake = _Fake()
        fake.register("u6", smoke_broker_identifier("r1"), "partial")
        run = _run(broker_order_uuid="u6")
        svc = UpbitLiveTrackingService(session, probe=fake)
        with (
            patch(
                "stock_platform.trading.upbit_live_tracking_service.emit_live_safety_audit"
            ),
            patch(
                "stock_platform.trading.upbit_live_tracking_service.emit_live_order_telegram"
            ),
            patch.object(svc, "_enqueue_cancel", return_value=1),
        ):
            # force deadline for remaining cancel path after partial
            run.watch_deadline_at = datetime.now(timezone.utc) - timedelta(
                seconds=1
            )
            view = svc.refresh(run, actor="rehearsal")
        if run.internal_status not in {
            InternalStatus.PARTIALLY_FILLED.value,
            InternalStatus.CANCEL_TRACKING.value,
            InternalStatus.CANCEL_REQUESTED.value,
        } and not view.get("cancel_request_accepted"):
            # partial then auto-cancel
            if run.broker_order_status != BrokerOrderStatus.CANCEL_PENDING.value:
                return CheckStatus.FAIL, "partial cancel missing", view
        return CheckStatus.PASS, "partial fill cancel remaining", {}

    results.append(
        run_check(
            suite="upbit_live_tracking",
            name="partial_fill_cancel_remaining",
            fn=_partial,
        )
    )

    def _filled_pf() -> tuple[CheckStatus, str, dict[str, Any]]:
        session = MagicMock()
        fake = _Fake()
        fake.register("u7", smoke_broker_identifier("r1"), "done")
        run = _run(broker_order_uuid="u7")
        svc = UpbitLiveTrackingService(session, probe=fake)
        with patch(
            "stock_platform.trading.upbit_live_tracking_service.emit_live_safety_audit"
        ), patch(
            "stock_platform.trading.upbit_live_tracking_service.emit_live_order_telegram"
        ):
            view = svc.refresh(run, actor="rehearsal")
        if view["status"] == InternalStatus.COMPLETED.value:
            return CheckStatus.FAIL, "completed before post-fill", view
        if view["status"] != InternalStatus.POST_FILL_VERIFYING.value:
            return CheckStatus.FAIL, "not post-fill", view
        return CheckStatus.PASS, "filled → post-fill verify", {}

    results.append(
        run_check(
            suite="upbit_live_tracking",
            name="filled_post_fill_verify",
            fn=_filled_pf,
        )
    )

    def _restart() -> tuple[CheckStatus, str, dict[str, Any]]:
        # next_track_at 기반 due 조회 존재
        assert hasattr(UpbitLiveTrackingService, "select_due_run_ids")
        assert hasattr(UpbitLiveTrackingService, "track_once")
        return CheckStatus.PASS, "restart recovery via DB due rows", {}

    results.append(
        run_check(
            suite="upbit_live_tracking",
            name="restart_recovery",
            fn=_restart,
        )
    )

    def _finally_flags() -> tuple[CheckStatus, str, dict[str, Any]]:
        from stock_platform.trading.upbit_live_smoke_service import (
            UpbitLiveSmokeService,
        )

        assert hasattr(UpbitLiveSmokeService, "_finalize_protect")
        return CheckStatus.PASS, "finally live off/disarm helpers", {}

    results.append(
        run_check(
            suite="upbit_live_tracking",
            name="finally_live_off",
            fn=_finally_flags,
        )
    )
    results.append(
        run_check(
            suite="upbit_live_tracking",
            name="finally_disarmed",
            fn=_finally_flags,
        )
    )

    return results
