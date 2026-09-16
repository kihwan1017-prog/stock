"""STEP 12-1 — Strategy Request 승인 게이트 서비스.

AI Candidate(ai.candidate_lifecycle) -> Strategy Request(사람 심사) 까지만
다룬다. Strategy Draft 생성, Backtest, Paper/Live 승인, Runtime 등록은
이 서비스의 범위가 아니다(STEP12-2 이후).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from stock_platform.ai.candidate_lifecycle.entities import (
    AICandidateLifecycleEntity,
)
from stock_platform.ai.strategy_request.constants import (
    ALLOWED_TRANSITIONS,
    ELIGIBLE_CANDIDATE_LIFECYCLE_STATUSES,
)
from stock_platform.ai.strategy_request.entities import (
    StrategyRequestEntity,
    StrategyRequestHistoryEntity,
)


class StrategyRequestError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _to_dict(row: StrategyRequestEntity) -> dict[str, Any]:
    return {
        "strategy_request_id": int(row.strategy_request_id),
        "candidate_id": int(row.candidate_id),
        "user_id": int(row.user_id),
        "reviewer_user_id": (
            int(row.reviewer_user_id) if row.reviewer_user_id is not None else None
        ),
        "status": row.status,
        "candidate_lifecycle_status_snapshot": (
            row.candidate_lifecycle_status_snapshot
        ),
        "candidate_status_at_review": row.candidate_status_at_review,
        "candidate_fingerprint_at_review": row.candidate_fingerprint_at_review,
        "request_note": row.request_note,
        "review_note": row.review_note,
        "version": int(row.version),
        "requested_at": row.requested_at,
        "reviewed_at": row.reviewed_at,
        "cancelled_at": row.cancelled_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _history_to_dict(row: StrategyRequestHistoryEntity) -> dict[str, Any]:
    return {
        "history_id": int(row.history_id),
        "strategy_request_id": int(row.strategy_request_id),
        "action": row.action,
        "previous_status": row.previous_status,
        "new_status": row.new_status,
        "reason": row.reason,
        "actor": row.actor,
        "correlation_id": row.correlation_id,
        "created_at": row.created_at,
    }


class StrategyRequestService:
    def __init__(self, session: Session) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # 생성
    # ------------------------------------------------------------------
    def create(
        self,
        *,
        candidate_id: int,
        user_id: int,
        request_note: str | None,
        actor: str,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        # 주의: AICandidateLifecycleEntity의 PK는 lifecycle_id이고
        # candidate_id는 별도의 UniqueConstraint 컬럼이므로 session.get()
        # (PK 조회)이 아니라 candidate_id로 select() 조회해야 한다.
        lifecycle = self._session.scalar(
            select(AICandidateLifecycleEntity).where(
                AICandidateLifecycleEntity.candidate_id == int(candidate_id)
            )
        )
        if lifecycle is None:
            raise StrategyRequestError(
                "CANDIDATE_NOT_FOUND",
                f"Candidate not found: {candidate_id}",
            )
        if lifecycle.lifecycle_status not in ELIGIBLE_CANDIDATE_LIFECYCLE_STATUSES:
            raise StrategyRequestError(
                "CANDIDATE_NOT_ACTIVE",
                (
                    "ACTIVE 상태(PROMOTED/ACTIVE_REVIEW) Candidate만 요청 "
                    f"가능합니다. 현재 상태: {lifecycle.lifecycle_status}"
                ),
            )

        # 동일 Candidate의 활성(PENDING_REVIEW) 요청 중복 사전 검사.
        # 최종 안전망은 부분 유니크 인덱스(ux_ai_strategy_request_candidate_active).
        existing = self._session.scalar(
            select(StrategyRequestEntity).where(
                StrategyRequestEntity.candidate_id == int(candidate_id),
                StrategyRequestEntity.status == "PENDING_REVIEW",
            )
        )
        if existing is not None:
            raise StrategyRequestError(
                "DUPLICATE_ACTIVE_REQUEST",
                (
                    "이미 심사 대기 중인 Strategy Request가 있습니다: "
                    f"#{existing.strategy_request_id}"
                ),
            )

        note = (request_note or "").strip() or None
        row = StrategyRequestEntity(
            candidate_id=int(candidate_id),
            user_id=int(user_id),
            status="PENDING_REVIEW",
            candidate_lifecycle_status_snapshot=lifecycle.lifecycle_status,
            request_note=note,
        )
        self._session.add(row)
        try:
            self._session.flush()
        except IntegrityError as exc:
            self._session.rollback()
            raise StrategyRequestError(
                "DUPLICATE_ACTIVE_REQUEST",
                "이미 심사 대기 중인 Strategy Request가 있습니다(동시 요청 감지).",
            ) from exc

        self._record_history(
            row,
            action="CREATE",
            previous_status=None,
            new_status="PENDING_REVIEW",
            reason=note,
            actor=actor,
            correlation_id=correlation_id,
        )
        self._session.commit()
        self._session.refresh(row)
        return _to_dict(row)

    # ------------------------------------------------------------------
    # 조회
    # ------------------------------------------------------------------
    def list(
        self,
        *,
        user_id: int | None = None,
        status: str | None = None,
        candidate_id: int | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        stmt = select(StrategyRequestEntity)
        if user_id is not None:
            stmt = stmt.where(StrategyRequestEntity.user_id == int(user_id))
        if status is not None:
            stmt = stmt.where(StrategyRequestEntity.status == status)
        if candidate_id is not None:
            stmt = stmt.where(
                StrategyRequestEntity.candidate_id == int(candidate_id)
            )
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = int(self._session.scalar(count_stmt) or 0)

        rows = list(
            self._session.scalars(
                stmt.order_by(StrategyRequestEntity.strategy_request_id.desc())
                .offset(max(0, offset))
                .limit(min(max(limit, 1), 200))
            )
        )
        return {
            "items": [_to_dict(r) for r in rows],
            "total": total,
        }

    def get(self, strategy_request_id: int) -> dict[str, Any]:
        row = self._require(strategy_request_id)
        return _to_dict(row)

    def get_owned(self, strategy_request_id: int, *, user_id: int) -> dict[str, Any]:
        row = self._require(strategy_request_id)
        if int(row.user_id) != int(user_id):
            raise StrategyRequestError(
                "OWNERSHIP_DENIED", "본인 Strategy Request가 아닙니다."
            )
        return _to_dict(row)

    def get_history(
        self, strategy_request_id: int, *, limit: int = 100, offset: int = 0
    ) -> dict[str, Any]:
        self._require(strategy_request_id)
        stmt = (
            select(StrategyRequestHistoryEntity)
            .where(
                StrategyRequestHistoryEntity.strategy_request_id
                == int(strategy_request_id)
            )
            .order_by(StrategyRequestHistoryEntity.history_id.desc())
            .offset(max(0, offset))
            .limit(min(max(limit, 1), 200))
        )
        rows = list(self._session.scalars(stmt))
        return {"items": [_history_to_dict(r) for r in rows]}

    # ------------------------------------------------------------------
    # 상태 변경 (취소/승인/반려) — 전부 단일 트랜잭션
    # ------------------------------------------------------------------
    def cancel(
        self,
        strategy_request_id: int,
        *,
        user_id: int,
        reason: str | None,
        actor: str,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        # for_update: 동일 요청에 대한 approve/reject/cancel 동시 호출 시
        # 마지막 커밋이 이전 결과를 조용히 덮어쓰는 것을 방지(STEP12-1A).
        row = self._require(strategy_request_id, for_update=True)
        if int(row.user_id) != int(user_id):
            raise StrategyRequestError(
                "OWNERSHIP_DENIED", "본인 Strategy Request만 취소할 수 있습니다."
            )
        return self._transition(
            row,
            new_status="CANCELLED",
            action="CANCEL",
            reason=reason,
            actor=actor,
            correlation_id=correlation_id,
            timestamp_field="cancelled_at",
        )

    def approve(
        self,
        strategy_request_id: int,
        *,
        reviewer_user_id: int,
        review_note: str | None,
        actor: str,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        # STEP12-1A: 승인 직전 Candidate Lifecycle을 재검증한다. 요청 생성
        # 시점에는 ACTIVE였더라도, 심사 대기 중 revoke/expire/supersede로
        # 비활성화됐을 수 있으므로 승인 순간의 상태를 다시 확인해야 한다.
        #
        # 잠금 순서: strategy_request -> candidate_lifecycle (고정 순서).
        # candidate_lifecycle 쪽의 expire/revoke/supersede는 strategy_request를
        # 잠그지 않으므로 역순 잠금이 발생하지 않아 교착 상태 위험이 없다.
        # Postgres READ COMMITTED에서 FOR UPDATE로 블로킹된 트랜잭션은 락 해제
        # (상대 COMMIT) 후 최신 커밋된 행 값을 다시 읽으므로, 두 트랜잭션 중
        # 하나가 커밋되면 나머지 하나는 항상 그 이후의 최신 상태를 보고 검증한다.
        row = self._require(strategy_request_id, for_update=True)

        candidate = self._session.scalar(
            select(AICandidateLifecycleEntity)
            .where(
                AICandidateLifecycleEntity.candidate_id == int(row.candidate_id)
            )
            .with_for_update()
        )
        if candidate is None:
            raise StrategyRequestError(
                "CANDIDATE_NOT_FOUND",
                f"Candidate not found: {row.candidate_id}",
            )
        if candidate.lifecycle_status not in ELIGIBLE_CANDIDATE_LIFECYCLE_STATUSES:
            raise StrategyRequestError(
                "CANDIDATE_NOT_ACTIVE_AT_REVIEW",
                (
                    "승인 시점 재검증 실패 — ACTIVE 상태(PROMOTED/ACTIVE_REVIEW) "
                    "Candidate만 승인 가능합니다. 현재 상태: "
                    f"{candidate.lifecycle_status}"
                ),
            )

        return self._transition(
            row,
            new_status="APPROVED",
            action="APPROVE",
            reason=review_note,
            actor=actor,
            correlation_id=correlation_id,
            timestamp_field="reviewed_at",
            extra_fields={
                "reviewer_user_id": int(reviewer_user_id),
                "review_note": (review_note or "").strip() or None,
                "candidate_status_at_review": candidate.lifecycle_status,
                "candidate_fingerprint_at_review": candidate.source_fingerprint,
            },
        )

    def reject(
        self,
        strategy_request_id: int,
        *,
        reviewer_user_id: int,
        review_note: str | None,
        actor: str,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        row = self._require(strategy_request_id, for_update=True)
        if not (review_note or "").strip():
            raise StrategyRequestError(
                "REVIEW_NOTE_REQUIRED", "반려 시 review_note(사유)가 필요합니다."
            )
        return self._transition(
            row,
            new_status="REJECTED",
            action="REJECT",
            reason=review_note,
            actor=actor,
            correlation_id=correlation_id,
            timestamp_field="reviewed_at",
            extra_fields={
                "reviewer_user_id": int(reviewer_user_id),
                "review_note": review_note.strip(),
            },
        )

    # ------------------------------------------------------------------
    # 내부 헬퍼
    # ------------------------------------------------------------------
    def _require(
        self, strategy_request_id: int, *, for_update: bool = False
    ) -> StrategyRequestEntity:
        if for_update:
            stmt = select(StrategyRequestEntity).where(
                StrategyRequestEntity.strategy_request_id == int(strategy_request_id)
            ).with_for_update()
            row = self._session.scalar(stmt)
        else:
            row = self._session.get(
                StrategyRequestEntity, int(strategy_request_id)
            )
        if row is None:
            raise StrategyRequestError(
                "NOT_FOUND",
                f"Strategy Request not found: {strategy_request_id}",
            )
        return row

    def _transition(
        self,
        row: StrategyRequestEntity,
        *,
        new_status: str,
        action: str,
        reason: str | None,
        actor: str,
        correlation_id: str | None,
        timestamp_field: str,
        extra_fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        allowed = ALLOWED_TRANSITIONS.get(row.status, frozenset())
        if new_status not in allowed:
            raise StrategyRequestError(
                "INVALID_STATE_TRANSITION",
                f"{row.status} -> {new_status} 전이는 허용되지 않습니다.",
            )
        previous_status = row.status
        # extra_fields는 전이 유효성 검사를 통과한 뒤에만 적용한다 — 검사 실패 시
        # reviewer_user_id/review_note 등이 부분적으로 세팅된 채 남아있다가 이후
        # (실패 감사로깅 등의) session.commit()으로 의도치 않게 영속화되는 것을
        # 방지한다(STEP12-1A에서 발견된 부분 commit 결함 수정).
        if extra_fields:
            for key, value in extra_fields.items():
                setattr(row, key, value)
        row.status = new_status
        row.version = int(row.version) + 1
        setattr(row, timestamp_field, _utcnow())
        self._session.flush()

        self._record_history(
            row,
            action=action,
            previous_status=previous_status,
            new_status=new_status,
            reason=reason,
            actor=actor,
            correlation_id=correlation_id,
        )
        self._session.commit()
        self._session.refresh(row)
        return _to_dict(row)

    def _record_history(
        self,
        row: StrategyRequestEntity,
        *,
        action: str,
        previous_status: str | None,
        new_status: str | None,
        reason: str | None,
        actor: str,
        correlation_id: str | None,
    ) -> None:
        history = StrategyRequestHistoryEntity(
            strategy_request_id=int(row.strategy_request_id),
            action=action,
            previous_status=previous_status,
            new_status=new_status,
            reason=(reason or "").strip()[:1000] or None,
            actor=actor,
            correlation_id=correlation_id,
        )
        self._session.add(history)
        self._session.flush()
