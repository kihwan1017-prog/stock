"""STEP 8-5-14 — Upbit Ambiguous Order Resolver Scheduler 배치 실행 서비스.

DB Claim + 계좌 단위 분산 Lock + Credential 검증 + Rate Limit 게이트를 거쳐
`UpbitAmbiguousOrderResolver.resolve_one` (원격 조회 전용)만 호출한다.
주문 재생성/재제출 API는 이 서비스에서 절대 호출하지 않는다.
"""

from __future__ import annotations

import logging
import uuid
from collections import OrderedDict, deque
from datetime import datetime, timezone
from typing import Any, Sequence

from sqlalchemy import Row, or_, select, text
from sqlalchemy.orm import Session

from stock_platform.broker.credential_vault_service import (
    BrokerCredentialVaultService,
)
from stock_platform.broker.recovery_distributed_lock import (
    DistributedRecoveryLockManager,
    LockAcquireResult,
    LockOwnershipLostError,
    LockReleaseReason,
    build_distributed_lock_manager_from_settings,
)
from stock_platform.broker.recovery_distributed_lock_scope import (
    RecoveryAccountKind,
    RecoveryLockScope,
)
from stock_platform.broker.recovery_instance_id import (
    get_recovery_instance_identity,
)
from stock_platform.broker.upbit.ambiguous_constants import (
    SubmissionAttemptResult,
)
from stock_platform.broker.upbit.ambiguous_resolution_entities import (
    UpbitAmbiguousResolutionRunEntity,
)
from stock_platform.broker.upbit.ambiguous_resolver import (
    UpbitAmbiguousOrderResolver,
)
from stock_platform.broker.upbit.rate_limit_constants import (
    UpbitOperationType,
)
from stock_platform.broker.upbit.rate_limit_coordinator import (
    get_upbit_rate_limit_coordinator,
)
from stock_platform.broker.upbit.rate_limit_http import infer_group
from stock_platform.common.settings import Settings, get_settings
from stock_platform.order.entities import (
    OrderSubmissionAttemptEntity,
    TradingOrderEntity,
)
from stock_platform.order.models import OrderStatus

logger = logging.getLogger(__name__)

_DUE_STATUSES = (
    OrderStatus.AMBIGUOUS_SUBMISSION.value,
    OrderStatus.REMOTE_LOOKUP_PENDING.value,
)
# 이 상태는 이미 Manual/Conflict Queue — Due 대상에서 제외
_EXCLUDED_STATUSES = (
    OrderStatus.MANUAL_REVIEW_REQUIRED.value,
    OrderStatus.IDENTITY_CONFLICT.value,
)

# Lock 획득 대기는 짧게 — Recovery/실주문 흐름을 막지 않는다.
_LOCK_ACQUIRE_TIMEOUT_SECONDS = 2.0
_LOCK_BUSY_DEFER_SECONDS = 5
_CREDENTIAL_BLOCKED_DEFER_SECONDS = 30
_RATE_LIMIT_DEFAULT_DEFER_SECONDS = 5.0


class UpbitAmbiguousOrderResolutionService:
    """1회 배치 실행 단위 — DB Claim → Lock → Credential → resolve_one."""

    def __init__(
        self,
        session: Session,
        *,
        settings: Settings | None = None,
        lock_manager: DistributedRecoveryLockManager | None = None,
    ) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._lock_manager = (
            lock_manager
            or build_distributed_lock_manager_from_settings(self._settings)
        )
        self._instance_id = get_recovery_instance_identity().instance_id

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run_once(
        self,
        *,
        trigger_type: str = "SCHEDULER",
        requested_by: str | None = None,
    ) -> dict[str, Any]:
        settings = self._settings
        if not settings.upbit_ambiguous_resolver_enabled:
            return {
                "status": "DISABLED",
                "due_count": 0,
                "claimed_count": 0,
            }

        batch_size = int(settings.upbit_ambiguous_resolver_batch_size)
        max_per_account = int(
            settings.upbit_ambiguous_max_orders_per_account_per_run
        )
        claim_seconds = int(settings.upbit_ambiguous_resolver_claim_seconds)

        candidates = self._select_due_candidates(limit=batch_size * 2)
        due_count = len(candidates)
        if due_count == 0:
            # 빈 폴링은 감사 로그를 남기지 않는다 (Noise 방지)
            return {
                "status": "NO_DUE",
                "due_count": 0,
                "claimed_count": 0,
            }

        fair_order = self._apply_fairness(
            candidates, batch_size=batch_size, max_per_account=max_per_account
        )

        run = self._start_run(
            trigger_type=trigger_type,
            requested_by=requested_by,
            due_count=due_count,
        )

        counters = {
            "claimed_count": 0,
            "found_count": 0,
            "not_found_count": 0,
            "manual_review_count": 0,
            "conflict_count": 0,
            "lock_busy_count": 0,
            "credential_blocked_count": 0,
            "rate_limited_count": 0,
            "error_count": 0,
        }
        details: list[dict[str, Any]] = []

        for row in fair_order:
            order_id = int(row.order_id)
            uba_id = row.user_broker_account_id
            run_token = uuid.uuid4().hex
            if not self._try_claim(
                order_id, run_token=run_token, claim_seconds=claim_seconds
            ):
                continue
            counters["claimed_count"] += 1
            outcome = self._process_claimed_order(
                order_id=order_id,
                uba_id=uba_id,
                run_token=run_token,
            )
            details.append(outcome)
            bucket = outcome.get("bucket", "error_count")
            counters[bucket] = counters.get(bucket, 0) + 1

        status_code = self._finish_run(
            run, counters=counters, details=details
        )
        self._audit_run(run, counters=counters, due_count=due_count)
        return {
            "status": status_code,
            "run_id": int(run.upbit_ambiguous_resolution_run_id),
            "due_count": due_count,
            **counters,
        }

    # ------------------------------------------------------------------
    # Candidate selection / fairness
    # ------------------------------------------------------------------

    def _select_due_candidates(self, *, limit: int) -> Sequence[Row]:
        now = datetime.now(timezone.utc)
        stmt = (
            select(
                TradingOrderEntity.order_id,
                TradingOrderEntity.user_broker_account_id,
                TradingOrderEntity.ambiguous_since,
            )
            .where(
                TradingOrderEntity.broker_code == "UPBIT",
                TradingOrderEntity.status_code.in_(_DUE_STATUSES),
                TradingOrderEntity.next_remote_lookup_at.is_not(None),
                TradingOrderEntity.next_remote_lookup_at <= now,
                TradingOrderEntity.client_order_identifier.is_not(None),
                TradingOrderEntity.client_order_identifier != "",
                or_(
                    TradingOrderEntity.resolver_claim_expires_at.is_(None),
                    TradingOrderEntity.resolver_claim_expires_at < now,
                ),
            )
            .order_by(
                TradingOrderEntity.ambiguous_since.asc().nulls_last(),
                TradingOrderEntity.order_id.asc(),
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        rows = list(self._session.execute(stmt).all())
        # SELECT ... FOR UPDATE 는 짧게 유지 — 커밋해 즉시 Row Lock 해제
        self._session.commit()
        return rows

    @staticmethod
    def _apply_fairness(
        rows: Sequence[Row],
        *,
        batch_size: int,
        max_per_account: int,
    ) -> list[Row]:
        """계좌 하나가 배치를 독점하지 않도록 Round-Robin 분배.

        각 계좌 내부에서는 ambiguous_since 오름차순(오래된 것 우선)을 유지한다.
        """

        buckets: "OrderedDict[Any, deque]" = OrderedDict()
        for row in rows:
            buckets.setdefault(row.user_broker_account_id, deque()).append(
                row
            )

        ordered: list[Row] = []
        per_account_taken: dict[Any, int] = {}
        while len(ordered) < batch_size:
            progressed = False
            for uba_id, bucket in buckets.items():
                if len(ordered) >= batch_size:
                    break
                if not bucket:
                    continue
                if per_account_taken.get(uba_id, 0) >= max_per_account:
                    continue
                ordered.append(bucket.popleft())
                per_account_taken[uba_id] = (
                    per_account_taken.get(uba_id, 0) + 1
                )
                progressed = True
            if not progressed:
                break
        return ordered

    # ------------------------------------------------------------------
    # Claim / release
    # ------------------------------------------------------------------

    def _try_claim(
        self,
        order_id: int,
        *,
        run_token: str,
        claim_seconds: int,
    ) -> bool:
        stmt = text(
            """
            UPDATE trading.trading_order
            SET
                resolver_claimed_by = :owner,
                resolver_claimed_at = NOW(),
                resolver_claim_expires_at =
                    NOW() + make_interval(secs => :claim_seconds),
                resolver_run_token = :run_token,
                updated_at = NOW()
            WHERE order_id = :order_id
              AND status_code IN ('AMBIGUOUS_SUBMISSION', 'REMOTE_LOOKUP_PENDING')
              AND status_code NOT IN ('MANUAL_REVIEW_REQUIRED', 'IDENTITY_CONFLICT')
              AND next_remote_lookup_at IS NOT NULL
              AND next_remote_lookup_at <= NOW()
              AND (
                resolver_claim_expires_at IS NULL
                OR resolver_claim_expires_at < NOW()
              )
              AND client_order_identifier IS NOT NULL
              AND client_order_identifier <> ''
            RETURNING order_id
            """
        )
        row = self._session.execute(
            stmt,
            {
                "owner": self._instance_id[:100],
                "claim_seconds": max(30, int(claim_seconds)),
                "run_token": run_token,
                "order_id": order_id,
            },
        ).first()
        self._session.commit()
        return row is not None

    def _release_claim(self, order_id: int, *, commit: bool = True) -> None:
        self._session.execute(
            text(
                """
                UPDATE trading.trading_order
                SET
                    resolver_claimed_by = NULL,
                    resolver_claimed_at = NULL,
                    resolver_claim_expires_at = NULL,
                    resolver_run_token = NULL
                WHERE order_id = :order_id
                """
            ),
            {"order_id": order_id},
        )
        if commit:
            self._session.commit()

    def _defer_without_attempt(
        self, order_id: int, *, seconds: float
    ) -> None:
        """Attempt를 소모하지 않고 Claim만 해제 + 다음 조회 시각 연기."""

        self._session.execute(
            text(
                """
                UPDATE trading.trading_order
                SET
                    next_remote_lookup_at =
                        NOW() + make_interval(secs => :secs),
                    resolver_claimed_by = NULL,
                    resolver_claimed_at = NULL,
                    resolver_claim_expires_at = NULL,
                    resolver_run_token = NULL,
                    updated_at = NOW()
                WHERE order_id = :order_id
                """
            ),
            {"order_id": order_id, "secs": max(1, int(seconds))},
        )
        self._session.commit()

    def release_stale_claim(
        self, order_id: int, *, actor: str = "ADMIN"
    ) -> dict[str, Any]:
        """만료된 Claim만 강제 해제 (ADMIN 전용, 유효 Claim은 거부)."""

        row = self._session.execute(
            text(
                """
                UPDATE trading.trading_order
                SET
                    resolver_claimed_by = NULL,
                    resolver_claimed_at = NULL,
                    resolver_claim_expires_at = NULL,
                    resolver_run_token = NULL,
                    updated_at = NOW()
                WHERE order_id = :order_id
                  AND resolver_claim_expires_at IS NOT NULL
                  AND resolver_claim_expires_at < NOW()
                RETURNING order_id
                """
            ),
            {"order_id": order_id},
        ).first()
        self._session.commit()
        if row is None:
            return {
                "status": "NOT_STALE_OR_NOT_CLAIMED",
                "order_id": order_id,
            }
        logger.info(
            "upbit_ambiguous_stale_claim_released",
            extra={"order_id": order_id, "actor": actor},
        )
        return {"status": "RELEASED", "order_id": order_id}

    # ------------------------------------------------------------------
    # Per-order processing
    # ------------------------------------------------------------------

    def _process_claimed_order(
        self,
        *,
        order_id: int,
        uba_id: int | None,
        run_token: str,
    ) -> dict[str, Any]:
        if uba_id is None:
            self._release_claim(order_id)
            return {
                "order_id": order_id,
                "bucket": "error_count",
                "reason": "NO_USER_BROKER_ACCOUNT",
            }

        scope = RecoveryLockScope(
            account_kind=RecoveryAccountKind.USER_BROKER,
            account_id=int(uba_id),
            broker_code="UPBIT",
            market_type="CRYPTO",
        )
        lock_result, handle = self._lock_manager.acquire(
            scope, timeout=_LOCK_ACQUIRE_TIMEOUT_SECONDS
        )
        if lock_result not in (
            LockAcquireResult.ACQUIRED,
            LockAcquireResult.STALE_TAKEN_OVER,
        ):
            self._defer_without_attempt(
                order_id, seconds=_LOCK_BUSY_DEFER_SECONDS
            )
            self._record_scheduler_attempt(
                order_id,
                result_type=SubmissionAttemptResult.LOCK_NOT_ACQUIRED.value,
            )
            return {"order_id": order_id, "bucket": "lock_busy_count"}

        try:
            credential = BrokerCredentialVaultService(self._session).status(
                int(uba_id), broker_code="UPBIT"
            )
            if credential.verification_status != "VERIFIED":
                self._defer_without_attempt(
                    order_id, seconds=_CREDENTIAL_BLOCKED_DEFER_SECONDS
                )
                return {
                    "order_id": order_id,
                    "bucket": "credential_blocked_count",
                    "reason": credential.verification_status,
                }

            allowed, _reason, wait_seconds = (
                get_upbit_rate_limit_coordinator().check_allowed(
                    user_broker_account_id=int(uba_id),
                    endpoint_group=infer_group(
                        UpbitOperationType.ORDER_QUERY
                    ),
                )
            )
            if not allowed:
                self._defer_without_attempt(
                    order_id,
                    seconds=max(
                        _RATE_LIMIT_DEFAULT_DEFER_SECONDS, wait_seconds
                    ),
                )
                return {
                    "order_id": order_id,
                    "bucket": "rate_limited_count",
                }

            resolver = UpbitAmbiguousOrderResolver(self._session)
            outcome = resolver.resolve_one(
                order_id,
                actor=f"SCHEDULER:{self._instance_id}",
                force=True,
            )

            try:
                self._lock_manager.assert_owns(handle)
            except LockOwnershipLostError:
                self._session.rollback()
                self._record_scheduler_attempt(
                    order_id,
                    result_type=(
                        SubmissionAttemptResult.LOCK_OWNERSHIP_LOST.value
                    ),
                )
                return {
                    "order_id": order_id,
                    "bucket": "error_count",
                    "reason": "LOCK_OWNERSHIP_LOST",
                }

            self._release_claim(order_id, commit=False)
            self._session.commit()
            return {
                "order_id": order_id,
                "bucket": self._bucket_for_outcome(outcome),
                "outcome": outcome.get("status"),
            }
        except Exception as exc:  # noqa: BLE001
            self._session.rollback()
            self._release_claim(order_id)
            logger.warning(
                "upbit_ambiguous_scheduler_process_error",
                extra={
                    "order_id": order_id,
                    "error": str(exc)[:300],
                },
            )
            return {
                "order_id": order_id,
                "bucket": "error_count",
                "reason": str(exc)[:200],
            }
        finally:
            self._lock_manager.release(handle, LockReleaseReason.SUCCESS)

    @staticmethod
    def _bucket_for_outcome(outcome: dict[str, Any]) -> str:
        status = str(outcome.get("status") or "")
        if status in {"FOUND_MATCHED"}:
            return "found_count"
        if status in {"MANUAL_REVIEW_REQUIRED"}:
            return "manual_review_count"
        if status in {"CONFLICT", "FOUND_MISMATCHED"}:
            return "conflict_count"
        if status in {"NOT_FOUND_TRANSIENT", "NOT_FOUND_FINAL"}:
            return "not_found_count"
        if status in {
            "RATE_LIMITED",
            "TEMPORARY_UNAVAILABLE",
            "LOOKUP_AMBIGUOUS",
            "LOOKUP_ERROR",
            "DEFERRED",
            "NO_IDENTIFIER",
            "NOT_FOUND",
            "SKIPPED_NOT_UPBIT",
        }:
            return "not_found_count"
        return "error_count"

    def _record_scheduler_attempt(
        self, order_id: int, *, result_type: str
    ) -> None:
        order = self._session.get(TradingOrderEntity, order_id)
        if order is None:
            return
        self._session.add(
            OrderSubmissionAttemptEntity(
                order_id=order_id,
                client_order_identifier=order.client_order_identifier,
                attempt_number=int(
                    order.remote_lookup_attempt_count or 0
                ),
                result_type=result_type,
                ambiguous=True,
                correlation_id=f"scheduler:{self._instance_id[:150]}",
            )
        )
        self._session.commit()

    # ------------------------------------------------------------------
    # Run history
    # ------------------------------------------------------------------

    def _start_run(
        self,
        *,
        trigger_type: str,
        requested_by: str | None,
        due_count: int,
    ) -> UpbitAmbiguousResolutionRunEntity:
        run = UpbitAmbiguousResolutionRunEntity(
            trigger_type=trigger_type,
            requested_by=(requested_by or "")[:150] or None,
            instance_id=self._instance_id[:200],
            status_code="RUNNING",
            due_count=due_count,
        )
        self._session.add(run)
        self._session.commit()
        return run

    def _finish_run(
        self,
        run: UpbitAmbiguousResolutionRunEntity,
        *,
        counters: dict[str, int],
        details: list[dict[str, Any]],
    ) -> str:
        now = datetime.now(timezone.utc)
        error_count = int(counters.get("error_count", 0))
        claimed = int(counters.get("claimed_count", 0))
        if error_count == 0:
            status_code = "SUCCEEDED"
        elif claimed > error_count:
            status_code = "PARTIAL"
        else:
            status_code = "FAILED"

        run.status_code = status_code
        run.claimed_count = claimed
        run.found_count = int(counters.get("found_count", 0))
        run.not_found_count = int(counters.get("not_found_count", 0))
        run.manual_review_count = int(
            counters.get("manual_review_count", 0)
        )
        run.conflict_count = int(counters.get("conflict_count", 0))
        run.lock_busy_count = int(counters.get("lock_busy_count", 0))
        run.credential_blocked_count = int(
            counters.get("credential_blocked_count", 0)
        )
        run.rate_limited_count = int(counters.get("rate_limited_count", 0))
        run.error_count = error_count
        run.result_summary = {"details": details[:200]}
        run.finished_at = now
        if run.started_at is not None:
            run.duration_ms = int(
                (now - run.started_at).total_seconds() * 1000
            )
        self._session.commit()
        return status_code

    def _audit_run(
        self,
        run: UpbitAmbiguousResolutionRunEntity,
        *,
        counters: dict[str, int],
        due_count: int,
    ) -> None:
        try:
            from stock_platform.operation.calendar_audit import (
                audit_calendar_event,
            )

            audit_calendar_event(
                "UPBIT_AMBIGUOUS_RESOLUTION_RUN",
                actor=f"scheduler:{self._instance_id[:80]}",
                detail={
                    "run_id": int(run.upbit_ambiguous_resolution_run_id),
                    "due_count": due_count,
                    **counters,
                },
            )
        except Exception:  # noqa: BLE001
            pass
