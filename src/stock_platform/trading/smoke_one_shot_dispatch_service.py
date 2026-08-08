"""Smoke Confirm 후 단건 Outbox one-shot dispatch (batch Worker/Scheduler 아님)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from stock_platform.order.outbox_dispatcher import OrderOutboxDispatcher
from stock_platform.order.outbox_models import OutboxStatus
from stock_platform.order.outbox_repository import OrderOutboxRepository
from stock_platform.order.outbox_worker import OrderOutboxWorker
from stock_platform.order.repository import TradingOrderRepository
from stock_platform.trading.account_models import UserBrokerAccount
from stock_platform.trading.live_validation_entities import (
    LiveValidationRunEntity,
)
from stock_platform.trading.smoke_one_shot_dispatch_grant import (
    GRANT_STATUS_ISSUED,
    GRANT_VERSION,
    SmokeOneShotGrantError,
    assert_smoke_one_shot_dispatch_allowed,
    read_grant_from_run_detail,
)
from stock_platform.trading.upbit_live_smoke_constants import (
    mask_broker_uuid,
)


class SmokeOneShotDispatchError(PermissionError):
    """전용 one-shot dispatch 거절 — Fail Closed."""

    def __init__(
        self,
        code: str,
        *,
        message: str | None = None,
        http_status: int = 400,
    ) -> None:
        self.code = str(code)
        self.message = message or self.code
        self.http_status = int(http_status)
        super().__init__(self.code)


def grant_public_view(grant: dict[str, Any] | None) -> dict[str, Any] | None:
    """FE용 grant 요약 — 시크릿 없음."""

    if not isinstance(grant, dict):
        return None
    return {
        "version": grant.get("version"),
        "status": grant.get("status"),
        "run_id": grant.get("run_id"),
        "order_id": grant.get("order_id"),
        "outbox_id": grant.get("outbox_id"),
        "uba_id": grant.get("uba_id"),
        "dispatch_expires_at": grant.get("dispatch_expires_at"),
        "issued_at": grant.get("issued_at"),
        "consumed_at": grant.get("consumed_at"),
    }


class SmokeOneShotDispatchService:
    """유효 grant v2 단건만 Worker 안전 경로로 dispatch."""

    def __init__(
        self,
        session: Session,
        *,
        session_factory: sessionmaker[Session] | None = None,
        dispatcher: OrderOutboxDispatcher | None = None,
    ) -> None:
        self._session = session
        self._session_factory = session_factory
        self._dispatcher = dispatcher

    def dispatch(
        self,
        *,
        uba_id: int,
        user_id: int,
        run_id: str,
        actor: str,
    ) -> dict[str, Any]:
        uba = self._session.get(UserBrokerAccount, int(uba_id))
        if uba is None or not bool(uba.is_active):
            raise SmokeOneShotDispatchError(
                "UBA_NOT_FOUND", http_status=404
            )
        if int(uba.user_id) != int(user_id):
            raise SmokeOneShotDispatchError("FORBIDDEN", http_status=403)
        if str(uba.broker_code).upper() != "UPBIT":
            raise SmokeOneShotDispatchError("BROKER_NOT_UPBIT")

        run = self._session.scalar(
            select(LiveValidationRunEntity).where(
                LiveValidationRunEntity.run_id == str(run_id),
                LiveValidationRunEntity.execute_live.is_(True),
            )
        )
        if run is None:
            raise SmokeOneShotDispatchError(
                "SMOKE_RUN_NOT_FOUND", http_status=404
            )
        if int(run.user_broker_account_id or 0) != int(uba_id):
            raise SmokeOneShotDispatchError("FORBIDDEN", http_status=403)
        if int(run.user_id or 0) != int(user_id):
            raise SmokeOneShotDispatchError("FORBIDDEN", http_status=403)

        grant = read_grant_from_run_detail(getattr(run, "detail", None))
        if grant is None:
            raise SmokeOneShotDispatchError("SMOKE_GRANT_MISSING")
        if int(grant.get("version") or 0) != GRANT_VERSION:
            raise SmokeOneShotDispatchError("SMOKE_GRANT_VERSION_MISMATCH")
        if str(grant.get("status") or "") != GRANT_STATUS_ISSUED:
            raise SmokeOneShotDispatchError("SMOKE_GRANT_NOT_ISSUED")
        if grant.get("consumed_at") is not None:
            raise SmokeOneShotDispatchError("SMOKE_GRANT_ALREADY_CONSUMED")

        order_id = int(grant.get("order_id") or 0)
        outbox_id = int(grant.get("outbox_id") or 0)
        if order_id <= 0 or outbox_id <= 0:
            raise SmokeOneShotDispatchError("SMOKE_GRANT_BINDING_INCOMPLETE")
        if int(run.order_id or 0) != order_id:
            raise SmokeOneShotDispatchError("SMOKE_GRANT_ORDER_MISMATCH")
        if str(grant.get("run_id") or "") != str(run.run_id):
            raise SmokeOneShotDispatchError("SMOKE_GRANT_RUN_MISMATCH")
        if int(grant.get("uba_id") or 0) != int(uba_id):
            raise SmokeOneShotDispatchError("SMOKE_GRANT_UBA_MISMATCH")

        order = TradingOrderRepository(self._session).get(order_id)
        if order is None:
            raise SmokeOneShotDispatchError("ORDER_NOT_FOUND", http_status=404)
        if int(order.user_broker_account_id or 0) != int(uba_id):
            raise SmokeOneShotDispatchError("ORDER_UBA_MISMATCH")
        if order.broker_order_id:
            raise SmokeOneShotDispatchError("BROKER_ORDER_ID_EXISTS")

        outbox = OrderOutboxRepository(self._session).get(outbox_id)
        if outbox is None:
            raise SmokeOneShotDispatchError(
                "OUTBOX_NOT_FOUND", http_status=404
            )
        if int(outbox.order_id) != order_id:
            raise SmokeOneShotDispatchError("OUTBOX_ORDER_MISMATCH")
        if int(outbox.user_broker_account_id or 0) != int(uba_id):
            raise SmokeOneShotDispatchError("OUTBOX_UBA_MISMATCH")
        if str(outbox.status_code).upper() not in {
            OutboxStatus.PENDING.value,
            OutboxStatus.RETRY.value,
        }:
            # AMBIGUOUS/DONE 등 — 재전송 금지
            raise SmokeOneShotDispatchError(
                f"OUTBOX_NOT_DISPATCHABLE:{outbox.status_code}"
            )

        payload = dict(outbox.payload_json or {})
        payload.setdefault("order_id", order_id)
        payload.setdefault("user_broker_account_id", int(uba_id))
        payload.setdefault("owner_user_id", int(user_id))
        payload.setdefault("broker_code", "UPBIT")
        payload.setdefault("environment", "LIVE")

        # Worker와 동일 grant assert (TTL/binding) — Fail Closed
        try:
            assert_smoke_one_shot_dispatch_allowed(
                self._session,
                payload,
                outbox_id=outbox_id,
                outbox_idempotency_key=str(outbox.idempotency_key or ""),
            )
        except SmokeOneShotGrantError as exc:
            code = str(exc)
            http = 409 if "EXPIRED" in code else 400
            raise SmokeOneShotDispatchError(code, http_status=http) from exc

        factory = self._session_factory
        if factory is None:
            from stock_platform.database.session import get_session_factory

            factory = get_session_factory()

        worker_id = f"smoke-one-shot:{actor}:{run_id}"[:80]
        worker = OrderOutboxWorker(
            session_factory=factory,
            dispatcher=self._dispatcher or OrderOutboxDispatcher(),
            worker_id=worker_id,
            batch_size=1,
            paper_only=False,
        )
        summary = worker.dispatch_one(int(outbox_id))

        # 결과 스냅샷 (별도 세션 — worker가 commit함)
        with factory() as after:
            order2 = TradingOrderRepository(after).get(order_id)
            outbox2 = OrderOutboxRepository(after).get(outbox_id)
            run2 = after.scalar(
                select(LiveValidationRunEntity).where(
                    LiveValidationRunEntity.run_id == str(run_id)
                )
            )
            grant2 = read_grant_from_run_detail(
                getattr(run2, "detail", None) if run2 else None
            )
            broker_id = (
                getattr(order2, "broker_order_id", None) if order2 else None
            )
            outbox_status = (
                getattr(outbox2, "status_code", None) if outbox2 else None
            )
            run_broker_status = (
                getattr(run2, "broker_order_status", None) if run2 else None
            )
            run_internal = (
                (
                    getattr(run2, "internal_status", None)
                    or getattr(run2, "status_code", None)
                )
                if run2
                else None
            )

        outcome = "UNKNOWN"
        if summary.ambiguous:
            outcome = "AMBIGUOUS"
        elif summary.failed:
            outcome = "FAILED"
        elif summary.succeeded:
            outcome = "SUBMITTED" if broker_id else "PROCESSED"
        elif summary.claimed == 0:
            outcome = "CLAIM_FAILED"
        elif summary.retried:
            outcome = "RETRY"

        return {
            "run_id": str(run_id),
            "order_id": order_id,
            "outbox_id": outbox_id,
            "uba_id": int(uba_id),
            "outcome": outcome,
            "claimed": int(summary.claimed),
            "succeeded": int(summary.succeeded),
            "failed": int(summary.failed),
            "ambiguous": int(summary.ambiguous),
            "retried": int(summary.retried),
            "outbox_status": outbox_status,
            "broker_order_status": run_broker_status
            or ("BROKER_SUBMITTED" if broker_id else "NOT_SUBMITTED"),
            "internal_status": run_internal,
            "broker_uuid_masked": mask_broker_uuid(broker_id),
            "one_shot_grant": grant_public_view(grant2),
            "scheduler_required": False,
            "batch_worker_required": False,
        }
