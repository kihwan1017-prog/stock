"""Smoke QUEUED 후 LIVE OFF/DISARM 이어도 단건 Outbox만 Worker 전송 허용.

설계 B — LIVE/ARM 재활성 없이 run/order/outbox/UBA가 일치하는
one-shot grant 1건만 통과. 넓은 PENDING 예외 금지.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

GRANT_DETAIL_KEY = "smoke_one_shot_dispatch_grant"
GRANT_STATUS_ISSUED = "ISSUED"
GRANT_STATUS_CONSUMED = "CONSUMED"
GRANT_VERSION = 1


class SmokeOneShotGrantError(PermissionError):
    """one-shot grant 검증 실패 — Fail Closed."""


def _parse_aware(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        raw = str(value).strip()
        if not raw:
            return None
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def build_smoke_one_shot_grant(
    *,
    run_id: str,
    order_id: int,
    outbox_id: int,
    uba_id: int,
    owner_user_id: int,
    arm_deadline_at: datetime,
    idempotency_key: str,
) -> dict[str, Any]:
    """발급 시점 스냅샷 — ARM TTL을 grant에 고정."""

    deadline = _parse_aware(arm_deadline_at)
    if deadline is None:
        raise ValueError("arm_deadline_at_required")
    now = datetime.now(timezone.utc)
    return {
        "version": GRANT_VERSION,
        "status": GRANT_STATUS_ISSUED,
        "run_id": str(run_id),
        "order_id": int(order_id),
        "outbox_id": int(outbox_id),
        "uba_id": int(uba_id),
        "owner_user_id": int(owner_user_id),
        "idempotency_key": str(idempotency_key),
        "arm_deadline_at": deadline.isoformat(),
        "issued_at": now.isoformat(),
        "consumed_at": None,
    }


def read_grant_from_run_detail(detail: dict[str, Any] | None) -> dict[str, Any] | None:
    raw = (detail or {}).get(GRANT_DETAIL_KEY)
    if not isinstance(raw, dict):
        return None
    return dict(raw)


def issue_grant_on_run(
    run: Any,
    *,
    order_id: int,
    outbox_id: int,
    uba_id: int,
    owner_user_id: int,
    arm_deadline_at: datetime,
    idempotency_key: str,
) -> dict[str, Any]:
    """LiveValidationRun.detail 에 grant 기록 (flush는 호출자)."""

    grant = build_smoke_one_shot_grant(
        run_id=str(run.run_id),
        order_id=int(order_id),
        outbox_id=int(outbox_id),
        uba_id=int(uba_id),
        owner_user_id=int(owner_user_id),
        arm_deadline_at=arm_deadline_at,
        idempotency_key=idempotency_key,
    )
    detail = dict(run.detail or {})
    detail[GRANT_DETAIL_KEY] = grant
    run.detail = detail
    return grant


def consume_grant_on_run(run: Any, *, outcome: str) -> dict[str, Any] | None:
    """terminal dispatch 후 grant 소비 (멱등)."""

    grant = read_grant_from_run_detail(getattr(run, "detail", None))
    if grant is None:
        return None
    if str(grant.get("status") or "") == GRANT_STATUS_CONSUMED:
        return grant
    now = datetime.now(timezone.utc)
    grant["status"] = GRANT_STATUS_CONSUMED
    grant["consumed_at"] = now.isoformat()
    grant["consume_outcome"] = str(outcome)[:64]
    detail = dict(run.detail or {})
    detail[GRANT_DETAIL_KEY] = grant
    run.detail = detail
    return grant


def _load_smoke_run_for_order(
    session: Session, *, order_id: int, run_id: str
) -> Any | None:
    from stock_platform.trading.live_validation_entities import (
        LiveValidationRunEntity,
    )

    return session.scalar(
        select(LiveValidationRunEntity).where(
            LiveValidationRunEntity.run_id == str(run_id),
            LiveValidationRunEntity.order_id == int(order_id),
            LiveValidationRunEntity.execute_live.is_(True),
        )
    )


def assert_smoke_one_shot_dispatch_allowed(
    session: Session,
    payload: dict[str, Any],
    *,
    outbox_id: int,
) -> dict[str, Any]:
    """LIVE OFF/DISARM 대체 경로 — 단건 grant 엄격 검증.

    통과 시 grant dict 반환. 실패 시 SmokeOneShotGrantError.
    """

    from stock_platform.broker.credential_vault_service import (
        BrokerCredentialVaultError,
        BrokerCredentialVaultService,
    )
    from stock_platform.risk_engine.kill_switch_service import (
        KillSwitchService,
    )
    from stock_platform.order.repository import TradingOrderRepository
    from stock_platform.trading.account_identity import uba_kill_switch_scope
    from stock_platform.trading.account_models import UserBrokerAccount

    order_id_raw = payload.get("order_id")
    if order_id_raw in (None, ""):
        raise SmokeOneShotGrantError("SMOKE_GRANT_ORDER_ID_REQUIRED")
    order_id = int(order_id_raw)

    order = TradingOrderRepository(session).get(order_id)
    if order is None:
        raise SmokeOneShotGrantError("SMOKE_GRANT_ORDER_NOT_FOUND")
    if order.broker_order_id:
        # UUID 존재 시 재전송 절대 금지 (attempt>0 재시도는 동일 outbox만 허용)
        raise SmokeOneShotGrantError("SMOKE_GRANT_BROKER_UUID_EXISTS")

    meta = dict(order.metadata_payload or {})
    smoke_run_id = str(meta.get("smoke_run_id") or "").strip()
    if not smoke_run_id:
        raise SmokeOneShotGrantError("SMOKE_GRANT_NOT_SMOKE_ORDER")

    run = _load_smoke_run_for_order(
        session, order_id=order_id, run_id=smoke_run_id
    )
    if run is None:
        raise SmokeOneShotGrantError("SMOKE_GRANT_RUN_NOT_FOUND")

    grant = read_grant_from_run_detail(getattr(run, "detail", None))
    if grant is None:
        raise SmokeOneShotGrantError("SMOKE_GRANT_MISSING")
    if int(grant.get("version") or 0) != GRANT_VERSION:
        raise SmokeOneShotGrantError("SMOKE_GRANT_VERSION_MISMATCH")
    if str(grant.get("status") or "") != GRANT_STATUS_ISSUED:
        raise SmokeOneShotGrantError("SMOKE_GRANT_NOT_ISSUED")

    if str(grant.get("run_id") or "") != str(run.run_id):
        raise SmokeOneShotGrantError("SMOKE_GRANT_RUN_MISMATCH")
    if int(grant.get("order_id") or 0) != int(order_id):
        raise SmokeOneShotGrantError("SMOKE_GRANT_ORDER_MISMATCH")
    if int(grant.get("outbox_id") or 0) != int(outbox_id):
        raise SmokeOneShotGrantError("SMOKE_GRANT_OUTBOX_MISMATCH")

    uba_raw = payload.get("user_broker_account_id")
    if uba_raw in (None, ""):
        raise SmokeOneShotGrantError("SMOKE_GRANT_UBA_REQUIRED")
    uba_id = int(uba_raw)
    if int(grant.get("uba_id") or 0) != uba_id:
        raise SmokeOneShotGrantError("SMOKE_GRANT_UBA_MISMATCH")
    if int(order.user_broker_account_id or 0) != uba_id:
        raise SmokeOneShotGrantError("SMOKE_GRANT_ORDER_UBA_MISMATCH")
    if int(run.user_broker_account_id or 0) != uba_id:
        raise SmokeOneShotGrantError("SMOKE_GRANT_RUN_UBA_MISMATCH")

    owner_raw = payload.get("owner_user_id")
    if owner_raw not in (None, ""):
        if int(grant.get("owner_user_id") or 0) != int(owner_raw):
            raise SmokeOneShotGrantError("SMOKE_GRANT_OWNER_MISMATCH")

    expected_idem = str(grant.get("idempotency_key") or "")
    # Outbox idempotency_key 는 entity에서 검사 — payload에 없을 수 있음
    meta_idem = str(meta.get("idempotency_key") or "")
    if meta_idem and meta_idem != expected_idem:
        raise SmokeOneShotGrantError("SMOKE_GRANT_IDEMPOTENCY_MISMATCH")
    if expected_idem != f"smoke:{smoke_run_id}":
        raise SmokeOneShotGrantError("SMOKE_GRANT_IDEMPOTENCY_SHAPE")

    deadline = _parse_aware(grant.get("arm_deadline_at"))
    if deadline is None:
        raise SmokeOneShotGrantError("SMOKE_GRANT_ARM_DEADLINE_MISSING")
    now = datetime.now(timezone.utc)
    if now >= deadline:
        raise SmokeOneShotGrantError("SMOKE_GRANT_ARM_DEADLINE_EXPIRED")

    uba = session.get(UserBrokerAccount, uba_id)
    if uba is None or not bool(uba.is_active):
        raise SmokeOneShotGrantError("SMOKE_GRANT_ACCOUNT_INACTIVE")
    if getattr(uba, "deleted_at", None) is not None:
        raise SmokeOneShotGrantError("SMOKE_GRANT_ACCOUNT_DELETED")
    expected_broker = str(payload.get("broker_code") or "").upper()
    if expected_broker and str(uba.broker_code).upper() != expected_broker:
        raise SmokeOneShotGrantError("SMOKE_GRANT_BROKER_MISMATCH")
    if int(uba.user_id) != int(grant.get("owner_user_id") or 0):
        raise SmokeOneShotGrantError("SMOKE_GRANT_UBA_OWNERSHIP")

    # Kill Switch
    try:
        ks = KillSwitchService(session)
        scopes = [
            KillSwitchService.GLOBAL_SCOPE,
            uba_kill_switch_scope(uba_id),
            f"USER:{int(uba.user_id)}",
        ]
        if ks.is_active_for_scopes(scopes):
            raise SmokeOneShotGrantError("SMOKE_GRANT_KILL_SWITCH")
    except SmokeOneShotGrantError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise SmokeOneShotGrantError("SMOKE_GRANT_KILL_SWITCH_UNAVAILABLE") from exc

    # Credential
    try:
        BrokerCredentialVaultService(session).assert_live_order_allowed(
            uba_id, broker_code=str(uba.broker_code).upper()
        )
    except BrokerCredentialVaultError as exc:
        raise SmokeOneShotGrantError(
            f"SMOKE_GRANT_CREDENTIAL:{exc.code}"
        ) from exc

    return grant


def dry_run_order_reusable_with_grant(
    *,
    has_grant_issued: bool,
    broker_order_id: str | None,
    submission_attempt_count: int,
    arm_deadline_at: str | datetime | None,
) -> str:
    """기존 queued 주문 재사용 판정 — 상태 변경 없음."""

    if broker_order_id:
        return "MUST_RETIRE"
    if int(submission_attempt_count or 0) != 0:
        return "MUST_RETIRE"
    if not has_grant_issued:
        return "MUST_RETIRE"
    deadline = _parse_aware(arm_deadline_at)
    if deadline is None or datetime.now(timezone.utc) >= deadline:
        return "MUST_RETIRE"
    return "REUSABLE"
