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
    POST_FILL_POSITION_SYNC_PENDING,
    POST_FILL_SNAPSHOT_STALE,
    POST_FILL_SYNC_PENDING_REASONS,
    CASH_SYNC_PENDING,
    POSITION_SYNC_PENDING,
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
        if reason_code in POST_FILL_SYNC_PENDING_REASONS:
            pending = reason_code in {
                POSITION_SYNC_PENDING,
                CASH_SYNC_PENDING,
            }
            row.status_code = PostFillVerifyStatus.WAITING_SNAPSHOT.value
            row.last_error_code = (
                POSITION_SYNC_PENDING if pending else "SNAPSHOT_STALE"
            )[:80]
            if reason_code == CASH_SYNC_PENDING:
                row.last_error_code = CASH_SYNC_PENDING
            row.last_error_summary = reason_code[:200]
            row.detail = {
                **(row.detail or {}),
                **payload,
                "stale": not pending,
                "sync_pending": pending,
            }
            row.next_retry_at = self._next_retry_at(row.retry_count)
            row.updated_at = now
            self._session.flush()
            self._audit(
                event_type=(
                    POST_FILL_POSITION_SYNC_PENDING
                    if pending
                    else POST_FILL_SNAPSHOT_STALE
                ),
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

        # 즉시 경로에서 남은 진짜 mismatch (kill 이미 다른 경로에서)
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
            if self._try_defer_waiting_snapshot_ttl(
                row, actor="POST_FILL_WORKER"
            ):
                # TTL defer 후 계속 sync→reverify (즉시 kill 금지)
                pass
            else:
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
            if self._try_defer_waiting_snapshot_ttl(
                row, actor="POST_FILL_WORKER"
            ):
                pass
            else:
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

    def resolve_stale_mismatch(
        self,
        verification_id: int,
        *,
        actor: str,
        confirmation_text: str,
    ) -> dict[str, Any]:
        """MISMATCH 행을 현재 스냅샷 기준으로 재검증 후 VERIFIED로 해소.

        - 실주문/LIVE/ARM 변경 없음
        - evidence 행 삭제 없음 (상태만 VERIFIED + detail)
        - 현재도 불일치면 GENUINE_CURRENT_MISMATCH 로 거부
        """

        from stock_platform.broker.account_repository import (
            BrokerAccountSnapshotRepository,
        )
        from stock_platform.order.post_fill_runner import PostFillVerifyRunner
        from stock_platform.order.post_fill_verification_constants import (
            CONFIRM_RESOLVE_STALE_POST_FILL_MISMATCH,
        )

        if str(confirmation_text or "").strip() != (
            CONFIRM_RESOLVE_STALE_POST_FILL_MISMATCH
        ):
            return {
                "ok": False,
                "code": "CONFIRMATION_REQUIRED",
                "verification_id": int(verification_id),
            }

        row = self._session.get(
            PostFillVerificationEntity, int(verification_id)
        )
        if row is None:
            return {
                "ok": False,
                "code": "NOT_FOUND",
                "verification_id": int(verification_id),
            }
        # MISMATCH 또는 EXPIRED(stale TTL) — 현재 snapshot 일치 시 VERIFIED 해소
        resolvable = {
            PostFillVerifyStatus.MISMATCH.value,
            PostFillVerifyStatus.EXPIRED.value,
        }
        if str(row.status_code) not in resolvable:
            return {
                "ok": False,
                "code": "NOT_RESOLVABLE_STATUS",
                "verification_id": int(verification_id),
                "status_code": row.status_code,
            }

        uba_id = int(row.user_broker_account_id)
        symbol = str(row.symbol or "").upper()
        runner = PostFillVerifyRunner(self._session)
        expected = runner.build_expected_positions_from_orders(
            user_broker_account_id=uba_id,
            symbol=symbol or None,
        )
        _account, positions = BrokerAccountSnapshotRepository(
            self._session
        ).get_active_by_uba(uba_id)
        broker_positions = [
            {"symbol": str(p.symbol), "quantity": str(p.quantity)}
            for p in positions
            if not symbol or str(p.symbol).upper() == symbol
        ]
        result = runner.verify_uba_against_expected(
            user_broker_account_id=uba_id,
            user_id=row.user_id,
            broker_code=str(row.broker_code or "UPBIT"),
            expected_positions=expected,
            expected_cash=None,
            broker_positions=broker_positions,
            actor=actor,
            activate_kill_on_mismatch=False,
            allow_live_off_for_submitted=True,
        )
        if not result.ok or result.reason_code not in {
            "VERIFY_OK",
            "OK",
            "LIVE_OFF_SKIP",
            "NO_UBA_SKIP",
            "UBA_NOT_FOUND_SKIP",
        }:
            return {
                "ok": False,
                "code": "GENUINE_CURRENT_MISMATCH",
                "verification_id": int(verification_id),
                "reason_code": result.reason_code,
                "detail": result.detail,
            }

        prior_status = str(row.status_code)
        prior = {
            "prior_status": prior_status,
            "prior_error": row.last_error_code,
            "prior_detail": dict(row.detail or {}),
            "resolution": (
                "EXPIRED_RESOLVED_AFTER_RECONCILE"
                if prior_status == PostFillVerifyStatus.EXPIRED.value
                else "STALE_RESOLVED_AFTER_RECONCILE"
            ),
            "resolution_reason_code": result.reason_code,
            "expected_positions_now": expected,
            "broker_positions_symbol_now": broker_positions,
        }
        self._mark_verified(row, actor=actor, detail=prior)
        return {
            "ok": True,
            "code": "RESOLVED",
            "verification_id": int(row.verification_id),
            "order_id": int(row.order_id) if row.order_id else None,
            "status_code": row.status_code,
            "detail": prior,
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
        next_retry = int(row.retry_count) + 1
        # 마지막 시도에서만 Kill. 그 전은 sync-pending 재시도.
        final_attempt = next_retry >= int(row.max_attempts)
        expected_positions = list(row.expected_position or [])
        # reverify도 즉시경로와 동일: expected symbols로 broker snapshot 필터
        expected_syms = {
            str(p.get("symbol") or "").upper()
            for p in expected_positions
            if str(p.get("symbol") or "").strip()
        }
        broker_positions = None
        if expected_syms:
            try:
                from stock_platform.broker.account_repository import (
                    BrokerAccountSnapshotRepository,
                )

                _acct, positions = BrokerAccountSnapshotRepository(
                    self._session
                ).get_active_by_uba(int(row.user_broker_account_id))
                broker_positions = [
                    {
                        "symbol": str(p.symbol),
                        "quantity": str(p.quantity),
                    }
                    for p in positions
                    if str(p.symbol).upper() in expected_syms
                ]
            except Exception:  # noqa: BLE001
                broker_positions = None
        result = runner.verify_uba_against_expected(
            user_broker_account_id=int(row.user_broker_account_id),
            user_id=row.user_id,
            broker_code=row.broker_code,
            expected_positions=expected_positions,
            expected_cash=(
                Decimal(str(row.expected_cash_delta))
                if row.expected_cash_delta is not None
                else None
            ),
            broker_positions=broker_positions,
            actor="POST_FILL_WORKER",
            allow_live_off_for_submitted=allow_live_off,
            activate_kill_on_mismatch=final_attempt,
        )
        if result.reason_code in POST_FILL_SYNC_PENDING_REASONS or (
            result.reason_code
            in {"POSITION_MISMATCH", "CASH_MISMATCH"}
            and not final_attempt
        ):
            row.retry_count = next_retry
            row.status_code = PostFillVerifyStatus.WAITING_SNAPSHOT.value
            if result.reason_code in {
                "POSITION_MISMATCH",
                POSITION_SYNC_PENDING,
            }:
                row.last_error_code = POSITION_SYNC_PENDING
            elif result.reason_code in {"CASH_MISMATCH", CASH_SYNC_PENDING}:
                row.last_error_code = CASH_SYNC_PENDING
            else:
                row.last_error_code = "SNAPSHOT_STALE"
            row.detail = {
                **(row.detail or {}),
                **(result.detail or {}),
                "sync_pending": True,
                "deferred_kill": True,
            }
            row.next_retry_at = self._next_retry_at(row.retry_count)
            row.claimed_by = None
            row.claim_expires_at = None
            row.updated_at = datetime.now(timezone.utc)
            self._session.flush()
            self._audit(
                event_type=POST_FILL_RETRY_SCHEDULED,
                row=row,
                actor="POST_FILL_WORKER",
                detail={
                    "retry_count": row.retry_count,
                    "reason_code": result.reason_code,
                },
            )
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
                already_killed=final_attempt,
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
        """Post-fill fail-closed — UBA scoped kill (GLOBAL escalation 금지).

        단일 UBA verification failure는 해당 UBA만 차단한다.
        """

        uba_id = int(row.user_broker_account_id)
        kill_reason = f"POST_FILL_{reason}"
        try:
            from stock_platform.risk_engine.kill_switch_service import (
                KillSwitchService,
            )
            from stock_platform.trading.account_identity import (
                uba_kill_switch_scope,
            )

            KillSwitchService(self._session).activate_scope(
                scope_code=uba_kill_switch_scope(uba_id),
                actor=actor,
                reason=kill_reason,
            )
        except Exception:  # noqa: BLE001
            pass
        try:
            from stock_platform.trading.live_arm_service import LiveArmService

            LiveArmService(self._session).disarm(
                uba_id,
                actor=actor,
                reason=kill_reason,
                turn_live_off=True,
            )
        except Exception:  # noqa: BLE001
            pass
        try:
            import asyncio

            from stock_platform.strategy_deployment.runtime_manager import (
                dynamic_strategy_runtime_manager,
            )

            # 해당 UBA runtime만 pause — 타 브로커/UBA 영향 금지
            coro = dynamic_strategy_runtime_manager.pause_account_runtimes(
                user_broker_account_id=uba_id,
                reason=f"post_fill_{reason.lower()}",
            )
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(coro)
            except RuntimeError:
                asyncio.run(coro)
        except Exception:  # noqa: BLE001
            pass

    def _try_defer_waiting_snapshot_ttl(
        self,
        row: PostFillVerificationEntity,
        *,
        actor: str,
    ) -> bool:
        """WAITING_SNAPSHOT + fill canonical + no contradiction → TTL 연장.

        즉시 kill 금지. bounded defer만 허용.
        """

        settings = get_settings()
        max_defers = int(
            getattr(settings, "post_fill_verify_max_snapshot_defers", 3)
        )
        defer_seconds = int(
            getattr(settings, "post_fill_verify_snapshot_defer_seconds", 120)
        )
        detail = dict(row.detail or {})
        defer_count = int(detail.get("snapshot_defer_count") or 0)
        if defer_count >= max_defers:
            return False

        sync_errors = {
            POSITION_SYNC_PENDING,
            CASH_SYNC_PENDING,
            "SNAPSHOT_STALE",
            "POSITION_MISMATCH",
            "CASH_MISMATCH",
        }
        last_err = str(row.last_error_code or "").upper()
        deferred_flag = bool(detail.get("deferred_kill") or detail.get("sync_pending"))
        if not deferred_flag and last_err not in sync_errors:
            return False

        # 모순 수량: broker_qty가 기대와 다르면서 0이 아닌 확정 mismatch면 defer 금지
        # (0은 snapshot lag 전형 — defer 허용)
        if self._has_contradictory_position_evidence(detail):
            return False

        if not self._order_fill_canonical_for_defer(row):
            return False

        now = datetime.now(timezone.utc)
        row.expires_at = now + timedelta(seconds=defer_seconds)
        row.status_code = PostFillVerifyStatus.WAITING_SNAPSHOT.value
        row.next_retry_at = self._next_retry_at(int(row.retry_count))
        row.claimed_by = None
        row.claim_expires_at = None
        detail["deferred_kill"] = True
        detail["sync_pending"] = True
        detail["snapshot_defer_count"] = defer_count + 1
        detail["last_snapshot_defer_at"] = now.isoformat()
        detail["snapshot_defer_seconds"] = defer_seconds
        row.detail = detail
        row.updated_at = now
        self._session.flush()
        self._audit(
            event_type=POST_FILL_RETRY_SCHEDULED,
            row=row,
            actor=actor,
            detail={
                "reason_code": "WAITING_SNAPSHOT_TTL_DEFERRED",
                "snapshot_defer_count": defer_count + 1,
                "max_snapshot_defers": max_defers,
                "new_expires_at": row.expires_at.isoformat(),
            },
        )
        return True

    @staticmethod
    def _has_contradictory_position_evidence(detail: dict[str, Any]) -> bool:
        """broker qty가 0이 아니면서 expected와 불일치하면 확정 mismatch 후보."""

        try:
            broker_raw = detail.get("broker_qty")
            db_raw = detail.get("db_qty")
            if broker_raw is None:
                return False
            broker_qty = Decimal(str(broker_raw))
            if broker_qty == 0:
                return False  # lag 전형
            if db_raw is None:
                return False
            db_qty = Decimal(str(db_raw))
            # 둘 다 양수인데 크게 다르면 contradiction
            if db_qty > 0 and broker_qty > 0 and broker_qty != db_qty:
                return True
        except Exception:  # noqa: BLE001
            return False
        return False

    def _order_fill_canonical_for_defer(
        self, row: PostFillVerificationEntity
    ) -> bool:
        """broker fill 확인된 terminal order만 snapshot defer 허용."""

        if row.order_id is None:
            return False
        try:
            from stock_platform.order.entities import TradingOrderEntity

            order = self._session.get(TradingOrderEntity, int(row.order_id))
            if order is None:
                return False
            status = str(getattr(order, "status_code", "") or "").upper()
            if status not in {"FILLED", "PARTIAL_FILLED", "PARTIALLY_FILLED"}:
                return False
            if not str(getattr(order, "broker_order_id", "") or "").strip():
                return False
            return True
        except Exception:  # noqa: BLE001
            return False

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
