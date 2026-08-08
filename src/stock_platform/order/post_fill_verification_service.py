"""STEP 8-8A — Post-Fill Verification 서비스 (enqueue / claim / retry)."""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from stock_platform.common.settings import get_settings
from stock_platform.order.live_safety_audit import (
    emit_live_order_telegram,
    emit_live_safety_audit,
)
from stock_platform.order.post_fill_broker_sync import (
    PostFillBrokerSyncError,
    sync_broker_snapshot_for_uba,
    sync_broker_snapshot_for_uba_async,
)
from stock_platform.order.post_fill_runner import PostFillVerifyRunner
from stock_platform.order.post_fill_verification_constants import (
    ACTIVE_STATUSES,
    POST_FILL_BROKER_DOWN_DELAY,
    POST_FILL_MISMATCH,
    POST_FILL_RETRY_SCHEDULED,
    POST_FILL_SNAPSHOT_STALE,
    POST_FILL_VERIFIED,
    POST_FILL_VERIFY_EXPIRED,
    POST_FILL_VERIFY_FAILED,
    POST_FILL_VERIFY_PENDING,
    PostFillVerifyStatus,
)
from stock_platform.order.post_fill_verification_entities import (
    PostFillVerificationEntity,
)


def parse_retry_delays(raw: str | None) -> list[int]:
    """예: '2,5,10,20' → [2,5,10,20]. 비정상이면 기본값."""

    default = [2, 5, 10, 20]
    if not raw or not str(raw).strip():
        return default
    out: list[int] = []
    for part in str(raw).split(","):
        part = part.strip()
        if not part:
            continue
        try:
            val = int(part)
        except ValueError:
            continue
        if val >= 0:
            out.append(val)
    return out or default


def make_idempotency_key(
    *,
    order_id: int,
    execution_id: int | None,
) -> str:
    exec_part = int(execution_id) if execution_id is not None else 0
    return f"order:{int(order_id)}:exec:{exec_part}"


class PostFillVerificationService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def enqueue_from_order(
        self,
        *,
        order: Any,
        execution_id: int | None = None,
        expected_positions: list[dict[str, Any]] | None = None,
        expected_cash_delta: Decimal | None = None,
        correlation_id: str | None = None,
        run_id: str | None = None,
        actor: str = "POST_FILL_ENQUEUE",
    ) -> PostFillVerificationEntity | None:
        """동일 fill에 대해 1건만 생성 (ON CONFLICT DO NOTHING)."""

        settings = get_settings()
        if not bool(getattr(settings, "post_fill_verify_enabled", True)):
            return None

        uba_id = getattr(order, "user_broker_account_id", None)
        if uba_id is None:
            return None
        order_id = int(order.order_id)
        key = make_idempotency_key(
            order_id=order_id, execution_id=execution_id
        )
        now = datetime.now(timezone.utc)
        delays = parse_retry_delays(
            getattr(settings, "post_fill_verify_retry_delays_seconds", None)
        )
        ttl = int(getattr(settings, "post_fill_verify_ttl_seconds", 60))
        max_attempts = int(
            getattr(settings, "post_fill_verify_max_attempts", 5)
        )
        symbol = str(getattr(order, "symbol", "") or "").upper()
        if expected_positions is None:
            expected_positions = PostFillVerifyRunner(
                self._session
            ).build_expected_positions_from_orders(
                user_broker_account_id=int(uba_id),
                symbol=symbol or None,
            )
        corr = correlation_id or uuid.uuid4().hex[:16]
        rid = run_id or f"pfv-{uuid.uuid4().hex[:12]}"

        stmt = (
            insert(PostFillVerificationEntity)
            .values(
                idempotency_key=key,
                order_id=order_id,
                execution_id=(
                    int(execution_id) if execution_id is not None else None
                ),
                user_id=getattr(order, "user_id", None),
                user_broker_account_id=int(uba_id),
                broker_code=str(
                    getattr(order, "broker_code", "") or "UNKNOWN"
                ).upper(),
                symbol=symbol or "UNKNOWN",
                expected_position=expected_positions,
                expected_cash_delta=expected_cash_delta,
                status_code=PostFillVerifyStatus.PENDING.value,
                retry_count=0,
                max_attempts=max_attempts,
                next_retry_at=now + timedelta(seconds=delays[0]),
                expires_at=now + timedelta(seconds=ttl),
                run_id=rid,
                correlation_id=corr,
                detail={},
            )
            .on_conflict_do_nothing(
                constraint="uq_post_fill_verification_idempotency"
            )
            .returning(PostFillVerificationEntity.verification_id)
        )
        inserted_id = self._session.execute(stmt).scalar_one_or_none()
        self._session.flush()
        row = self._session.scalar(
            select(PostFillVerificationEntity).where(
                PostFillVerificationEntity.idempotency_key == key
            )
        )
        if row is None:
            return None
        if inserted_id is not None:
            self._audit(
                event_type=POST_FILL_VERIFY_PENDING,
                row=row,
                actor=actor,
                detail={"status": row.status_code},
            )
        return row

    def handle_immediate_result(
        self,
        *,
        row: PostFillVerificationEntity,
        reason_code: str,
        detail: dict[str, Any] | None = None,
        actor: str = "POST_FILL_IMMEDIATE",
        request_sync: bool = True,
    ) -> PostFillVerificationEntity:
        """즉시 검증 결과를 상태에 반영. STALE은 성공이 아님."""

        now = datetime.now(timezone.utc)
        payload = dict(detail or {})
        if reason_code in {
            "SNAPSHOT_STALE_SKIP",
            "SNAPSHOT_MISSING_SKIP",
            "SNAPSHOT_STALE",
            "SNAPSHOT_MISSING",
        }:
            row.status_code = PostFillVerifyStatus.WAITING_SNAPSHOT.value
            row.last_error_code = "SNAPSHOT_STALE"
            row.last_error_summary = reason_code[:200]
            row.detail = {**(row.detail or {}), **payload, "stale": True}
            row.next_retry_at = self._next_retry_at(row.retry_count)
            row.updated_at = now
            self._session.flush()
            self._audit(
                event_type=POST_FILL_SNAPSHOT_STALE,
                row=row,
                actor=actor,
                detail={"reason_code": reason_code, **payload},
            )
            self._audit(
                event_type=POST_FILL_RETRY_SCHEDULED,
                row=row,
                actor=actor,
                detail={
                    "next_retry_at": (
                        row.next_retry_at.isoformat()
                        if row.next_retry_at
                        else None
                    ),
                    "retry_count": row.retry_count,
                },
            )
            if request_sync:
                self._try_sync_best_effort(row, actor=actor)
            return row

        if reason_code in {"VERIFY_OK", "OK"} or reason_code.endswith("_OK"):
            return self._mark_verified(row, actor=actor, detail=payload)

        if reason_code in {"POSITION_MISMATCH", "CASH_MISMATCH"}:
            return self._mark_mismatch(
                row, actor=actor, reason=reason_code, detail=payload
            )

        # LIVE_OFF / NO_UBA 등은 검증 대상 아님 → VERIFIED(해당 없음) 대신 종료
        if reason_code in {
            "LIVE_OFF_SKIP",
            "NO_UBA_SKIP",
            "UBA_NOT_FOUND_SKIP",
        }:
            row.status_code = PostFillVerifyStatus.VERIFIED.value
            row.verified_at = now
            row.last_error_code = reason_code
            row.detail = {
                **(row.detail or {}),
                **payload,
                "skipped": True,
            }
            row.updated_at = now
            self._session.flush()
            return row

        row.last_error_code = reason_code[:80]
        row.last_error_summary = str(payload)[:200]
        row.detail = {**(row.detail or {}), **payload}
        row.updated_at = now
        self._session.flush()
        return row

    def run_once(
        self,
        *,
        worker_id: str | None = None,
        batch_size: int | None = None,
        use_async_sync: bool = False,
    ) -> dict[str, Any]:
        """Due 작업 claim 후 sync→재검증. 스케줄러 진입점."""

        settings = get_settings()
        if not bool(getattr(settings, "post_fill_verify_enabled", True)):
            return {"status": "DISABLED", "processed": 0}

        wid = worker_id or f"pfv-{secrets.token_hex(4)}"
        limit = int(
            batch_size
            or getattr(settings, "post_fill_verify_batch_size", 20)
        )
        due_ids = self.select_due_ids(limit=limit)
        processed = 0
        results: list[dict[str, Any]] = []
        for vid in due_ids:
            claimed = self.try_claim(vid, worker_id=wid)
            if claimed is None:
                continue
            outcome = self.process_claimed(
                claimed, use_async_sync=use_async_sync
            )
            results.append(outcome)
            processed += 1
        self._session.commit()
        return {
            "status": "OK" if processed else "NO_DUE",
            "processed": processed,
            "results": results,
        }

    async def run_once_async(
        self,
        *,
        worker_id: str | None = None,
        batch_size: int | None = None,
    ) -> dict[str, Any]:
        settings = get_settings()
        if not bool(getattr(settings, "post_fill_verify_enabled", True)):
            return {"status": "DISABLED", "processed": 0}

        wid = worker_id or f"pfv-{secrets.token_hex(4)}"
        limit = int(
            batch_size
            or getattr(settings, "post_fill_verify_batch_size", 20)
        )
        due_ids = self.select_due_ids(limit=limit)
        processed = 0
        results: list[dict[str, Any]] = []
        for vid in due_ids:
            claimed = self.try_claim(vid, worker_id=wid)
            if claimed is None:
                continue
            outcome = await self.process_claimed_async(claimed)
            results.append(outcome)
            processed += 1
        self._session.commit()
        return {
            "status": "OK" if processed else "NO_DUE",
            "processed": processed,
            "results": results,
        }

    def select_due_ids(self, *, limit: int = 20) -> list[int]:
        now = datetime.now(timezone.utc)
        rows = list(
            self._session.scalars(
                select(PostFillVerificationEntity.verification_id)
                .where(
                    PostFillVerificationEntity.status_code.in_(
                        tuple(ACTIVE_STATUSES)
                    ),
                    or_(
                        PostFillVerificationEntity.next_retry_at.is_(None),
                        PostFillVerificationEntity.next_retry_at <= now,
                    ),
                    or_(
                        PostFillVerificationEntity.claim_expires_at.is_(None),
                        PostFillVerificationEntity.claim_expires_at < now,
                    ),
                )
                .order_by(
                    PostFillVerificationEntity.next_retry_at.asc().nullsfirst()
                )
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        return [int(x) for x in rows]

    def try_claim(
        self,
        verification_id: int,
        *,
        worker_id: str,
    ) -> PostFillVerificationEntity | None:
        settings = get_settings()
        claim_seconds = int(
            getattr(settings, "post_fill_verify_claim_seconds", 30)
        )
        now = datetime.now(timezone.utc)
        expires = now + timedelta(seconds=claim_seconds)
        result = self._session.execute(
            update(PostFillVerificationEntity)
            .where(
                PostFillVerificationEntity.verification_id
                == int(verification_id),
                PostFillVerificationEntity.status_code.in_(
                    tuple(ACTIVE_STATUSES)
                ),
                or_(
                    PostFillVerificationEntity.claim_expires_at.is_(None),
                    PostFillVerificationEntity.claim_expires_at < now,
                ),
            )
            .values(
                status_code=PostFillVerifyStatus.VERIFYING.value,
                claimed_by=worker_id,
                claimed_at=now,
                claim_expires_at=expires,
                updated_at=now,
            )
            .returning(PostFillVerificationEntity.verification_id)
        )
        vid = result.scalar_one_or_none()
        if vid is None:
            return None
        self._session.flush()
        return self._session.get(
            PostFillVerificationEntity, int(verification_id)
        )

    def process_claimed(
        self,
        row: PostFillVerificationEntity,
        *,
        use_async_sync: bool = False,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        if row.expires_at <= now:
            self._mark_expired(row, actor="POST_FILL_WORKER")
            return {
                "verification_id": row.verification_id,
                "status": PostFillVerifyStatus.EXPIRED.value,
            }

        if row.retry_count >= int(row.max_attempts):
            self._mark_expired(
                row,
                actor="POST_FILL_WORKER",
                reason="MAX_ATTEMPTS",
            )
            return {
                "verification_id": row.verification_id,
                "status": PostFillVerifyStatus.EXPIRED.value,
            }

        # Sync
        try:
            if not use_async_sync:
                sync_broker_snapshot_for_uba(
                    self._session,
                    user_broker_account_id=int(row.user_broker_account_id),
                    broker_code=row.broker_code,
                )
                emit_live_safety_audit(
                    self._session,
                    event_type="BALANCE_SNAPSHOT_REFRESHED",
                    actor="POST_FILL_WORKER",
                    run_id=None,
                    user_id=int(row.user_id) if row.user_id else None,
                    account_id=int(row.user_broker_account_id),
                    strategy_id=None,
                    detail={
                        "verification_id": row.verification_id,
                        "order_id": row.order_id,
                        "broker_code": row.broker_code,
                    },
                    commit=False,
                )
                emit_live_safety_audit(
                    self._session,
                    event_type="POSITION_SNAPSHOT_REFRESHED",
                    actor="POST_FILL_WORKER",
                    run_id=None,
                    user_id=int(row.user_id) if row.user_id else None,
                    account_id=int(row.user_broker_account_id),
                    strategy_id=None,
                    detail={
                        "verification_id": row.verification_id,
                        "order_id": row.order_id,
                    },
                    commit=False,
                )
        except PostFillBrokerSyncError as exc:
            return self._on_sync_error(row, exc)

        return self._reverify(row)

    async def process_claimed_async(
        self,
        row: PostFillVerificationEntity,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        if row.expires_at <= now:
            self._mark_expired(row, actor="POST_FILL_WORKER")
            return {
                "verification_id": row.verification_id,
                "status": PostFillVerifyStatus.EXPIRED.value,
            }
        if row.retry_count >= int(row.max_attempts):
            self._mark_expired(
                row,
                actor="POST_FILL_WORKER",
                reason="MAX_ATTEMPTS",
            )
            return {
                "verification_id": row.verification_id,
                "status": PostFillVerifyStatus.EXPIRED.value,
            }
        try:
            await sync_broker_snapshot_for_uba_async(
                self._session,
                user_broker_account_id=int(row.user_broker_account_id),
                broker_code=row.broker_code,
            )
        except PostFillBrokerSyncError as exc:
            return self._on_sync_error(row, exc)
        return self._reverify(row)

    def dashboard_counts(
        self,
        *,
        user_broker_account_ids: list[int] | None = None,
    ) -> dict[str, Any]:
        """Dashboard 집계."""

        def _count(status: str) -> int:
            q = select(func.count()).select_from(PostFillVerificationEntity)
            if user_broker_account_ids is not None:
                q = q.where(
                    PostFillVerificationEntity.user_broker_account_id.in_(
                        [int(x) for x in user_broker_account_ids]
                    )
                )
            q = q.where(PostFillVerificationEntity.status_code == status)
            return int(self._session.scalar(q) or 0)

        pending = _count(PostFillVerifyStatus.PENDING.value)
        waiting = _count(PostFillVerifyStatus.WAITING_SNAPSHOT.value)
        verifying = _count(PostFillVerifyStatus.VERIFYING.value)
        mismatch = _count(PostFillVerifyStatus.MISMATCH.value)
        expired = _count(PostFillVerifyStatus.EXPIRED.value)
        failed = _count(PostFillVerifyStatus.FAILED.value)

        oldest_q = select(
            func.min(PostFillVerificationEntity.created_at)
        ).where(
            PostFillVerificationEntity.status_code.in_(
                tuple(ACTIVE_STATUSES)
            )
        )
        if user_broker_account_ids is not None:
            oldest_q = oldest_q.where(
                PostFillVerificationEntity.user_broker_account_id.in_(
                    [int(x) for x in user_broker_account_ids]
                )
            )
        oldest = self._session.scalar(oldest_q)
        oldest_wait_seconds = None
        if oldest is not None:
            if oldest.tzinfo is None:
                oldest = oldest.replace(tzinfo=timezone.utc)
            oldest_wait_seconds = int(
                (datetime.now(timezone.utc) - oldest).total_seconds()
            )

        last_ok_q = select(
            func.max(PostFillVerificationEntity.verified_at)
        ).where(
            PostFillVerificationEntity.status_code
            == PostFillVerifyStatus.VERIFIED.value
        )
        if user_broker_account_ids is not None:
            last_ok_q = last_ok_q.where(
                PostFillVerificationEntity.user_broker_account_id.in_(
                    [int(x) for x in user_broker_account_ids]
                )
            )
        last_ok = self._session.scalar(last_ok_q)

        return {
            "pending": pending,
            "waiting_snapshot": waiting,
            "verifying": verifying,
            "mismatch": mismatch,
            "expired": expired,
            "failed": failed,
            "active": pending + waiting + verifying,
            "oldest_wait_seconds": oldest_wait_seconds,
            "last_verified_at": (
                last_ok.isoformat() if last_ok is not None else None
            ),
        }

    # --- internal ---

    def _reverify(self, row: PostFillVerificationEntity) -> dict[str, Any]:
        runner = PostFillVerifyRunner(self._session)
        allow_live_off = False
        if row.order_id is not None:
            try:
                from stock_platform.order.entities import TradingOrderEntity

                linked = self._session.get(
                    TradingOrderEntity, int(row.order_id)
                )
                if linked is not None and str(
                    getattr(linked, "broker_order_id", "") or ""
                ).strip():
                    allow_live_off = True
            except Exception:  # noqa: BLE001
                allow_live_off = False
        result = runner.verify_uba_against_expected(
            user_broker_account_id=int(row.user_broker_account_id),
            user_id=row.user_id,
            broker_code=row.broker_code,
            expected_positions=list(row.expected_position or []),
            expected_cash=(
                Decimal(str(row.expected_cash_delta))
                if row.expected_cash_delta is not None
                else None
            ),
            actor="POST_FILL_WORKER",
            allow_live_off_for_submitted=allow_live_off,
            # Kill은 서비스가 상태 전환 후 verifier를 통해 처리
            # verify_uba 내부 verifier는 activate_kill_on_mismatch=True
        )
        # 위 호출이 mismatch면 이미 kill됨 — 상태만 맞춤
        if result.reason_code in {
            "SNAPSHOT_STALE_SKIP",
            "SNAPSHOT_MISSING_SKIP",
            "SNAPSHOT_STALE",
        }:
            row.retry_count = int(row.retry_count) + 1
            row.status_code = PostFillVerifyStatus.WAITING_SNAPSHOT.value
            row.last_error_code = "SNAPSHOT_STALE"
            row.next_retry_at = self._next_retry_at(row.retry_count)
            row.claimed_by = None
            row.claim_expires_at = None
            row.updated_at = datetime.now(timezone.utc)
            self._session.flush()
            self._audit(
                event_type=POST_FILL_RETRY_SCHEDULED,
                row=row,
                actor="POST_FILL_WORKER",
                detail={"retry_count": row.retry_count},
            )
            # 만료/최대시도는 다음 due에서 처리
            if row.retry_count >= int(row.max_attempts):
                self._mark_expired(
                    row, actor="POST_FILL_WORKER", reason="MAX_ATTEMPTS"
                )
                return {
                    "verification_id": row.verification_id,
                    "status": PostFillVerifyStatus.EXPIRED.value,
                }
            return {
                "verification_id": row.verification_id,
                "status": PostFillVerifyStatus.WAITING_SNAPSHOT.value,
            }

        if result.ok and result.reason_code in {
            "VERIFY_OK",
            "LIVE_OFF_SKIP",
            "NO_UBA_SKIP",
            "UBA_NOT_FOUND_SKIP",
        }:
            self._mark_verified(
                row, actor="POST_FILL_WORKER", detail=result.detail
            )
            return {
                "verification_id": row.verification_id,
                "status": PostFillVerifyStatus.VERIFIED.value,
            }

        if result.reason_code in {"POSITION_MISMATCH", "CASH_MISMATCH"}:
            self._mark_mismatch(
                row,
                actor="POST_FILL_WORKER",
                reason=result.reason_code,
                detail=result.detail,
                already_killed=True,
            )
            return {
                "verification_id": row.verification_id,
                "status": PostFillVerifyStatus.MISMATCH.value,
            }

        row.retry_count = int(row.retry_count) + 1
        row.last_error_code = result.reason_code[:80]
        row.status_code = PostFillVerifyStatus.WAITING_SNAPSHOT.value
        row.next_retry_at = self._next_retry_at(row.retry_count)
        row.claimed_by = None
        row.claim_expires_at = None
        row.updated_at = datetime.now(timezone.utc)
        self._session.flush()
        return {
            "verification_id": row.verification_id,
            "status": row.status_code,
            "reason": result.reason_code,
        }

    def _on_sync_error(
        self,
        row: PostFillVerificationEntity,
        exc: PostFillBrokerSyncError,
    ) -> dict[str, Any]:
        if exc.code == "BROKER_DOWN":
            try:
                from stock_platform.trading.broker_disconnect_protector import (
                    BrokerDisconnectProtector,
                )

                BrokerDisconnectProtector(self._session).on_broker_down(
                    broker_code=row.broker_code,
                    actor="POST_FILL_VERIFY",
                    detail={
                        "verification_id": row.verification_id,
                        "source": "post_fill_sync",
                    },
                )
            except Exception:  # noqa: BLE001
                pass
            if not bool(row.broker_down_notified):
                row.broker_down_notified = True
                self._audit(
                    event_type=POST_FILL_BROKER_DOWN_DELAY,
                    row=row,
                    actor="POST_FILL_WORKER",
                    detail={"error": exc.message[:200]},
                )
                emit_live_order_telegram(
                    event_type=POST_FILL_BROKER_DOWN_DELAY,
                    title="Post-Fill delayed (Broker Down)",
                    message=(
                        f"Verification {row.verification_id} delayed — "
                        f"broker {row.broker_code} down"
                    ),
                    detail=self._audit_detail(row),
                )
            row.retry_count = int(row.retry_count) + 1
            row.status_code = PostFillVerifyStatus.WAITING_SNAPSHOT.value
            row.last_error_code = "BROKER_DOWN"
            row.last_error_summary = exc.message[:200]
            row.next_retry_at = self._next_retry_at(row.retry_count)
            row.claimed_by = None
            row.claim_expires_at = None
            row.updated_at = datetime.now(timezone.utc)
            self._session.flush()
            return {
                "verification_id": row.verification_id,
                "status": "WAITING_SNAPSHOT",
                "broker_down": True,
            }

        row.retry_count = int(row.retry_count) + 1
        row.last_error_code = exc.code[:80]
        row.last_error_summary = exc.message[:200]
        if row.retry_count >= int(row.max_attempts):
            self._mark_failed(row, actor="POST_FILL_WORKER", reason=exc.code)
            return {
                "verification_id": row.verification_id,
                "status": PostFillVerifyStatus.FAILED.value,
            }
        row.status_code = PostFillVerifyStatus.WAITING_SNAPSHOT.value
        row.next_retry_at = self._next_retry_at(row.retry_count)
        row.claimed_by = None
        row.claim_expires_at = None
        row.updated_at = datetime.now(timezone.utc)
        self._session.flush()
        return {
            "verification_id": row.verification_id,
            "status": row.status_code,
            "error": exc.code,
        }

    def _mark_verified(
        self,
        row: PostFillVerificationEntity,
        *,
        actor: str,
        detail: dict[str, Any] | None = None,
    ) -> PostFillVerificationEntity:
        now = datetime.now(timezone.utc)
        row.status_code = PostFillVerifyStatus.VERIFIED.value
        row.verified_at = now
        row.claimed_by = None
        row.claim_expires_at = None
        row.detail = {**(row.detail or {}), **(detail or {})}
        row.updated_at = now
        self._session.flush()
        self._audit(
            event_type=POST_FILL_VERIFIED,
            row=row,
            actor=actor,
            detail=detail or {},
        )
        # STEP 10-1 운영 Audit 별칭 (기존 POST_FILL_VERIFIED 유지)
        emit_live_safety_audit(
            self._session,
            event_type="POST_FILL_SUCCEEDED",
            actor=actor,
            run_id=None,
            user_id=int(row.user_id) if row.user_id else None,
            account_id=int(row.user_broker_account_id),
            strategy_id=None,
            detail={
                "verification_id": row.verification_id,
                "order_id": row.order_id,
                **(detail or {}),
            },
            commit=False,
        )
        emit_live_safety_audit(
            self._session,
            event_type="RECONCILIATION_MATCHED",
            actor=actor,
            run_id=None,
            user_id=int(row.user_id) if row.user_id else None,
            account_id=int(row.user_broker_account_id),
            strategy_id=None,
            detail={
                "verification_id": row.verification_id,
                "order_id": row.order_id,
            },
            commit=False,
        )
        # 정보성 Telegram — 설정에 따라
        settings = get_settings()
        if bool(
            getattr(settings, "post_fill_verify_telegram_on_verified", False)
        ):
            emit_live_order_telegram(
                event_type=POST_FILL_VERIFIED,
                title="Post-Fill VERIFIED",
                message=f"Verification {row.verification_id} ok",
                detail=self._audit_detail(row),
            )
        return row

    def _mark_mismatch(
        self,
        row: PostFillVerificationEntity,
        *,
        actor: str,
        reason: str,
        detail: dict[str, Any] | None = None,
        already_killed: bool = False,
    ) -> PostFillVerificationEntity:
        now = datetime.now(timezone.utc)
        row.status_code = PostFillVerifyStatus.MISMATCH.value
        row.last_error_code = reason[:80]
        row.claimed_by = None
        row.claim_expires_at = None
        row.detail = {**(row.detail or {}), **(detail or {})}
        row.updated_at = now
        self._session.flush()
        self._audit(
            event_type=POST_FILL_MISMATCH,
            row=row,
            actor=actor,
            detail={"reason": reason, **(detail or {})},
        )
        emit_live_safety_audit(
            self._session,
            event_type="RECONCILIATION_MISMATCH",
            actor=actor,
            run_id=None,
            user_id=int(row.user_id) if row.user_id else None,
            account_id=int(row.user_broker_account_id),
            strategy_id=None,
            detail={
                "verification_id": row.verification_id,
                "order_id": row.order_id,
                "reason": reason,
            },
            commit=False,
        )
        emit_live_order_telegram(
            event_type=POST_FILL_MISMATCH,
            title="Post-Fill MISMATCH",
            message=f"Mismatch {reason} verification={row.verification_id}",
            detail=self._audit_detail(row),
        )
        if not already_killed:
            self._fail_closed_kill(row, actor=actor, reason=reason)
        return row

    def _mark_expired(
        self,
        row: PostFillVerificationEntity,
        *,
        actor: str,
        reason: str = "TTL_EXPIRED",
    ) -> PostFillVerificationEntity:
        now = datetime.now(timezone.utc)
        row.status_code = PostFillVerifyStatus.EXPIRED.value
        row.last_error_code = reason[:80]
        row.claimed_by = None
        row.claim_expires_at = None
        row.updated_at = now
        self._session.flush()
        self._audit(
            event_type=POST_FILL_VERIFY_EXPIRED,
            row=row,
            actor=actor,
            detail={"reason": reason},
        )
        emit_live_order_telegram(
            event_type=POST_FILL_VERIFY_EXPIRED,
            title="Post-Fill VERIFY EXPIRED",
            message=(
                f"Verification {row.verification_id} expired ({reason})"
            ),
            detail=self._audit_detail(row),
        )
        self._fail_closed_kill(row, actor=actor, reason=reason)
        return row

    def _mark_failed(
        self,
        row: PostFillVerificationEntity,
        *,
        actor: str,
        reason: str,
    ) -> PostFillVerificationEntity:
        now = datetime.now(timezone.utc)
        row.status_code = PostFillVerifyStatus.FAILED.value
        row.last_error_code = reason[:80]
        row.claimed_by = None
        row.claim_expires_at = None
        row.updated_at = now
        self._session.flush()
        self._audit(
            event_type=POST_FILL_VERIFY_FAILED,
            row=row,
            actor=actor,
            detail={"reason": reason},
        )
        emit_live_safety_audit(
            self._session,
            event_type="RECONCILIATION_FAILED",
            actor=actor,
            run_id=None,
            user_id=int(row.user_id) if row.user_id else None,
            account_id=int(row.user_broker_account_id),
            strategy_id=None,
            detail={
                "verification_id": row.verification_id,
                "order_id": row.order_id,
                "reason": reason,
            },
            commit=False,
        )
        emit_live_order_telegram(
            event_type=POST_FILL_VERIFY_FAILED,
            title="Post-Fill VERIFY FAILED",
            message=f"Verification {row.verification_id} failed ({reason})",
            detail=self._audit_detail(row),
        )
        self._fail_closed_kill(row, actor=actor, reason=reason)
        return row

    def _fail_closed_kill(
        self,
        row: PostFillVerificationEntity,
        *,
        actor: str,
        reason: str,
    ) -> None:
        try:
            from stock_platform.risk_engine.kill_switch_service import (
                KillSwitchService,
            )

            KillSwitchService(self._session).activate(
                actor=actor,
                reason=f"POST_FILL_{reason}",
            )
        except Exception:  # noqa: BLE001
            pass
        try:
            from stock_platform.trading.live_arm_service import LiveArmService

            LiveArmService(self._session).disarm(
                int(row.user_broker_account_id),
                actor=actor,
                reason=f"POST_FILL_{reason}",
                turn_live_off=True,
            )
        except Exception:  # noqa: BLE001
            pass
        try:
            import asyncio

            from stock_platform.strategy_deployment.runtime_manager import (
                dynamic_strategy_runtime_manager,
            )

            coro = dynamic_strategy_runtime_manager.pause_all(
                reason=f"post_fill_{reason.lower()}"
            )
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(coro)
            except RuntimeError:
                asyncio.run(coro)
        except Exception:  # noqa: BLE001
            pass

    def _next_retry_at(self, retry_count: int) -> datetime:
        settings = get_settings()
        delays = parse_retry_delays(
            getattr(settings, "post_fill_verify_retry_delays_seconds", None)
        )
        idx = min(max(int(retry_count), 0), len(delays) - 1)
        return datetime.now(timezone.utc) + timedelta(seconds=delays[idx])

    def _try_sync_best_effort(
        self,
        row: PostFillVerificationEntity,
        *,
        actor: str,
    ) -> None:
        try:
            sync_broker_snapshot_for_uba(
                self._session,
                user_broker_account_id=int(row.user_broker_account_id),
                broker_code=row.broker_code,
            )
        except PostFillBrokerSyncError as exc:
            if exc.code == "BROKER_DOWN":
                try:
                    from stock_platform.trading.broker_disconnect_protector import (
                        BrokerDisconnectProtector,
                    )

                    BrokerDisconnectProtector(self._session).on_broker_down(
                        broker_code=row.broker_code,
                        actor=actor,
                        detail={"verification_id": row.verification_id},
                    )
                except Exception:  # noqa: BLE001
                    pass
            elif exc.code == "ASYNC_CONTEXT":
                # 스케줄러가 async sync 수행
                pass
        except Exception:  # noqa: BLE001
            pass

    def _audit_detail(
        self, row: PostFillVerificationEntity
    ) -> dict[str, Any]:
        return {
            "verification_id": int(row.verification_id),
            "order_id": int(row.order_id),
            "execution_id": row.execution_id,
            "account_id": int(row.user_broker_account_id),
            "user_id": row.user_id,
            "symbol": row.symbol,
            "retry_count": int(row.retry_count),
            "run_id": row.run_id,
            "correlation_id": row.correlation_id,
            "status": row.status_code,
            # 토큰·계좌번호 원문 금지
        }

    def _audit(
        self,
        *,
        event_type: str,
        row: PostFillVerificationEntity,
        actor: str,
        detail: dict[str, Any],
    ) -> None:
        emit_live_safety_audit(
            self._session,
            event_type=event_type,
            actor=actor,
            run_id=row.run_id,
            user_id=row.user_id,
            account_id=int(row.user_broker_account_id),
            strategy_id=None,
            symbol=row.symbol,
            order_id=int(row.order_id),
            detail={**self._audit_detail(row), **detail},
            commit=False,
        )
