"""STEP 8-5-15 — Market Session Job 영속화/Claim/생명주기 서비스.

DB(`operation.market_session_job`)를 Source of Truth로 삼아 Calendar
Revision별 KRX 세션 Job을 생성·Supersede하고, Dispatcher가 원자적으로
Claim/실행/종료할 수 있는 기본 연산을 제공한다. Claim은 반드시 DB `NOW()`
기준의 단일 `UPDATE ... WHERE ... RETURNING` 문으로 수행해 다중 인스턴스에서
경쟁이 나더라도 하나만 성공하도록 한다.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from stock_platform.operation.market_session_job_constants import (
    ACTIVE_JOB_STATUSES,
    CLAIMABLE_JOB_STATUSES,
    POST_CLOSE_JOB_TYPES,
    MarketSessionJobResult,
    MarketSessionJobStatus,
    MarketSessionJobType,
    TERMINAL_JOB_STATUSES,
    build_job_key,
)
from stock_platform.operation.market_session_job_entities import (
    MarketSessionJobEntity,
    MarketSessionJobRunEntity,
)


class MarketSessionJobError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def plan_from_timeline(timeline: Any) -> list[tuple[str, datetime | None]]:
    """Timeline → (job_type, scheduled_for) 후보 목록.

    `calendar_scheduler_recompute`의 기존 offset 매핑과 동일한 필드를 사용한다.
    """

    return [
        (
            MarketSessionJobType.KRX_PREOPEN_RECOVERY.value,
            timeline.recovery_preopen_at,
        ),
        (
            MarketSessionJobType.KRX_POSTCLOSE_RECOVERY.value,
            timeline.recovery_postclose_at,
        ),
        (
            MarketSessionJobType.KRX_EQUITY_SNAPSHOT.value,
            timeline.snapshot_at,
        ),
        (
            MarketSessionJobType.KRX_SETTLEMENT.value,
            timeline.settlement_at,
        ),
        (
            MarketSessionJobType.KRX_AI_ANALYSIS.value,
            timeline.analysis_at,
        ),
    ]


def _catchup_eligible(
    *,
    job_type: str,
    scheduled_for: datetime,
    now: datetime,
    regular_close_at: datetime | None,
    grace_seconds: int = 120,
) -> bool:
    """생성 시점 기준 이 Job이 여전히 의미 있는 시각인지 판정.

    - 아직 도래하지 않았거나 아주 최근(``grace_seconds``)이면 항상 생성.
    - POST_CLOSE 계열(Postclose Recovery/Snapshot/Settlement/AI)은 당일
      장마감 이후 3시간 이내라면 Catch-up 목적으로 생성을 허용한다.
    """

    if scheduled_for >= now - timedelta(seconds=grace_seconds):
        return True
    if job_type in POST_CLOSE_JOB_TYPES and regular_close_at is not None:
        if now.date() == regular_close_at.date():
            return now <= regular_close_at + timedelta(hours=3)
    return False


class MarketSessionJobService:
    """단일 세션(Session) 범위에서 동작하는 CRUD/생명주기 서비스."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # 생성 / Supersede (Calendar Recompute 경로 — 동일 트랜잭션 사용)
    # ------------------------------------------------------------------

    def create_or_supersede_for_revision(
        self,
        *,
        exchange_code: str,
        market_date: date,
        revision: int,
        timeline: Any,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """새 Revision Job을 생성하고 이전 Revision Job은 SUPERSEDED 처리.

        Calendar 변경과 같은 트랜잭션에서 호출될 수 있도록 commit을 호출하지
        않는다 (flush만 사용) — 호출자가 트랜잭션 경계를 관리한다.
        """

        exchange = exchange_code.upper()
        moment = now or _utcnow()
        superseded = self.supersede_previous_revision(
            exchange_code=exchange,
            market_date=market_date,
            new_revision=revision,
        )

        created: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        snapshot_job: MarketSessionJobEntity | None = None
        pending_ai: MarketSessionJobEntity | None = None
        pending_settlement: MarketSessionJobEntity | None = None

        for job_type, scheduled_for in plan_from_timeline(timeline):
            if scheduled_for is None:
                continue
            job_key = build_job_key(
                exchange_code=exchange,
                market_date=market_date,
                job_type=job_type,
                revision=revision,
            )
            existing = self._get_by_key(job_key)
            if existing is not None:
                if job_type == MarketSessionJobType.KRX_EQUITY_SNAPSHOT.value:
                    snapshot_job = existing
                if job_type == MarketSessionJobType.KRX_AI_ANALYSIS.value:
                    pending_ai = existing
                if job_type == MarketSessionJobType.KRX_SETTLEMENT.value:
                    pending_settlement = existing
                continue

            if not _catchup_eligible(
                job_type=job_type,
                scheduled_for=scheduled_for,
                now=moment,
                regular_close_at=timeline.regular_close_at,
            ):
                skipped.append(
                    {
                        "job_type": job_type,
                        "scheduled_for": scheduled_for.isoformat(),
                        "reason": "PAST_NOT_CATCHUP_ELIGIBLE",
                    }
                )
                continue

            row = MarketSessionJobEntity(
                exchange_code=exchange,
                market_date=market_date,
                calendar_revision=int(revision),
                job_type=job_type,
                job_key=job_key,
                scheduled_for=scheduled_for,
                status_code=MarketSessionJobStatus.SCHEDULED.value,
                payload={},
            )
            self._session.add(row)
            self._session.flush()
            created.append({"job_type": job_type, "job_id": row.market_session_job_id})
            if job_type == MarketSessionJobType.KRX_EQUITY_SNAPSHOT.value:
                snapshot_job = row
            if job_type == MarketSessionJobType.KRX_AI_ANALYSIS.value:
                pending_ai = row
            if job_type == MarketSessionJobType.KRX_SETTLEMENT.value:
                pending_settlement = row

        # AI_ANALYSIS / SETTLEMENT → EQUITY_SNAPSHOT 의존관계
        if pending_ai is not None and snapshot_job is not None:
            pending_ai.depends_on_job_id = snapshot_job.market_session_job_id
            self._session.flush()
        if pending_settlement is not None and snapshot_job is not None:
            pending_settlement.depends_on_job_id = (
                snapshot_job.market_session_job_id
            )
            self._session.flush()

        return {
            "status": "OK",
            "superseded": superseded,
            "created": created,
            "skipped": skipped,
        }

    def supersede_previous_revision(
        self,
        *,
        exchange_code: str,
        market_date: date,
        new_revision: int,
    ) -> int:
        stmt = select(MarketSessionJobEntity).where(
            MarketSessionJobEntity.exchange_code == exchange_code,
            MarketSessionJobEntity.market_date == market_date,
            MarketSessionJobEntity.calendar_revision != int(new_revision),
            MarketSessionJobEntity.status_code.in_(ACTIVE_JOB_STATUSES),
        )
        rows = list(self._session.scalars(stmt))
        now = _utcnow()
        for row in rows:
            row.status_code = MarketSessionJobStatus.SUPERSEDED.value
            row.superseded_at = now
        if rows:
            self._session.flush()
        return len(rows)

    def _get_by_key(self, job_key: str) -> MarketSessionJobEntity | None:
        stmt = select(MarketSessionJobEntity).where(
            MarketSessionJobEntity.job_key == job_key
        )
        return self._session.scalar(stmt)

    # ------------------------------------------------------------------
    # 조회
    # ------------------------------------------------------------------

    def get(self, job_id: int) -> MarketSessionJobEntity | None:
        return self._session.get(MarketSessionJobEntity, int(job_id))

    def list_for_date(
        self, *, exchange_code: str, market_date: date
    ) -> list[MarketSessionJobEntity]:
        stmt = (
            select(MarketSessionJobEntity)
            .where(
                MarketSessionJobEntity.exchange_code
                == exchange_code.upper(),
                MarketSessionJobEntity.market_date == market_date,
            )
            .order_by(MarketSessionJobEntity.scheduled_for.asc())
        )
        return list(self._session.scalars(stmt))

    def list_jobs(
        self,
        *,
        exchange_code: str | None = None,
        market_date: date | None = None,
        status_code: str | None = None,
        job_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[MarketSessionJobEntity]:
        stmt = select(MarketSessionJobEntity)
        if exchange_code:
            stmt = stmt.where(
                MarketSessionJobEntity.exchange_code
                == exchange_code.upper()
            )
        if market_date:
            stmt = stmt.where(
                MarketSessionJobEntity.market_date == market_date
            )
        if status_code:
            stmt = stmt.where(
                MarketSessionJobEntity.status_code == status_code
            )
        if job_type:
            stmt = stmt.where(MarketSessionJobEntity.job_type == job_type)
        stmt = (
            stmt.order_by(MarketSessionJobEntity.scheduled_for.desc())
            .offset(max(0, offset))
            .limit(max(1, min(limit, 500)))
        )
        return list(self._session.scalars(stmt))

    def list_runs(self, job_id: int) -> list[MarketSessionJobRunEntity]:
        stmt = (
            select(MarketSessionJobRunEntity)
            .where(
                MarketSessionJobRunEntity.market_session_job_id
                == int(job_id)
            )
            .order_by(MarketSessionJobRunEntity.run_number.desc())
        )
        return list(self._session.scalars(stmt))

    def has_succeeded(
        self, *, exchange_code: str, market_date: date, job_type: str
    ) -> bool:
        """해당 날짜의 (가장 최근 Revision) Job이 SUCCEEDED 상태인지 확인.

        USER 화면의 소프트 상태(snapshot_ready/analysis_ready) 계산 용도.
        """

        stmt = (
            select(MarketSessionJobEntity.status_code)
            .where(
                MarketSessionJobEntity.exchange_code
                == exchange_code.upper(),
                MarketSessionJobEntity.market_date == market_date,
                MarketSessionJobEntity.job_type == job_type,
            )
            .order_by(MarketSessionJobEntity.calendar_revision.desc())
            .limit(1)
        )
        status_code = self._session.scalar(stmt)
        return status_code == MarketSessionJobStatus.SUCCEEDED.value

    def health_summary(self) -> dict[str, Any]:
        rows = list(self._session.scalars(select(MarketSessionJobEntity)))
        counts: dict[str, int] = {}
        lag_samples: list[float] = []
        for row in rows:
            counts[row.status_code] = counts.get(row.status_code, 0) + 1
            if row.started_at is not None:
                lag_samples.append(
                    (row.started_at - row.scheduled_for).total_seconds()
                )
        avg_lag = (
            sum(lag_samples) / len(lag_samples) if lag_samples else None
        )
        due_count = sum(
            1
            for row in rows
            if row.status_code in CLAIMABLE_JOB_STATUSES
            and row.scheduled_for <= _utcnow()
        )
        return {
            "counts_by_status": counts,
            "due_count": due_count,
            "running_count": counts.get(
                MarketSessionJobStatus.RUNNING.value, 0
            ),
            "failed_count": counts.get(
                MarketSessionJobStatus.FAILED.value, 0
            ),
            "superseded_count": counts.get(
                MarketSessionJobStatus.SUPERSEDED.value, 0
            ),
            "average_lag_seconds": avg_lag,
        }

    # ------------------------------------------------------------------
    # Claim / 실행 생명주기 (Dispatcher 전용 — 실 DB 세션 필요)
    # ------------------------------------------------------------------

    def select_due_job_ids(self, *, limit: int) -> list[int]:
        """Due 후보를 짧게 잠갔다 즉시 커밋 (경합은 try_claim이 최종 판정)."""

        stmt = (
            select(MarketSessionJobEntity.market_session_job_id)
            .where(
                MarketSessionJobEntity.status_code.in_(
                    CLAIMABLE_JOB_STATUSES
                ),
                MarketSessionJobEntity.scheduled_for <= _utcnow(),
                (
                    (MarketSessionJobEntity.claim_expires_at.is_(None))
                    | (MarketSessionJobEntity.claim_expires_at < _utcnow())
                ),
                (
                    (MarketSessionJobEntity.next_retry_at.is_(None))
                    | (MarketSessionJobEntity.next_retry_at <= _utcnow())
                ),
            )
            .order_by(
                MarketSessionJobEntity.priority.asc(),
                MarketSessionJobEntity.scheduled_for.asc(),
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        ids = [int(row) for row in self._session.scalars(stmt)]
        self._session.commit()
        return ids

    def try_claim(
        self,
        job_id: int,
        *,
        instance_id: str,
        claim_seconds: int,
    ) -> str | None:
        """단일 원자적 UPDATE — 성공 시 run_token 반환, 실패 시 None."""

        run_token = uuid.uuid4().hex
        stmt = text(
            """
            UPDATE operation.market_session_job
            SET status_code = 'CLAIMED',
                claimed_by = :owner,
                claimed_at = NOW(),
                claim_expires_at = NOW() + make_interval(secs => :secs),
                run_token = :run_token,
                updated_at = NOW()
            WHERE market_session_job_id = :job_id
              AND status_code IN ('SCHEDULED', 'RETRY_PENDING')
              AND scheduled_for <= NOW()
              AND (claim_expires_at IS NULL OR claim_expires_at < NOW())
            RETURNING market_session_job_id
            """
        )
        row = self._session.execute(
            stmt,
            {
                "owner": instance_id[:200],
                "secs": max(1, int(claim_seconds)),
                "run_token": run_token,
                "job_id": int(job_id),
            },
        ).first()
        self._session.commit()
        return run_token if row is not None else None

    def mark_running(self, job_id: int, *, run_token: str) -> bool:
        stmt = text(
            """
            UPDATE operation.market_session_job
            SET status_code = 'RUNNING',
                started_at = NOW(),
                updated_at = NOW()
            WHERE market_session_job_id = :job_id
              AND run_token = :run_token
              AND status_code = 'CLAIMED'
            RETURNING market_session_job_id
            """
        )
        row = self._session.execute(
            stmt, {"job_id": int(job_id), "run_token": run_token}
        ).first()
        self._session.commit()
        return row is not None

    def finish_job(
        self,
        job_id: int,
        *,
        run_token: str,
        status_code: str,
        error_code: str | None = None,
        error_summary: str | None = None,
        next_retry_at: datetime | None = None,
    ) -> bool:
        """종료 직전 run_token 재검증 — Ownership 상실 시 False 반환."""

        stmt = text(
            """
            UPDATE operation.market_session_job
            SET status_code = :status_code,
                finished_at = NOW(),
                last_error_code = :error_code,
                last_error_summary = :error_summary,
                attempt_count = attempt_count + 1,
                next_retry_at = :next_retry_at,
                claimed_by = NULL,
                claimed_at = NULL,
                claim_expires_at = NULL,
                run_token = NULL,
                updated_at = NOW()
            WHERE market_session_job_id = :job_id
              AND run_token = :run_token
              AND status_code IN ('CLAIMED', 'RUNNING')
            RETURNING market_session_job_id
            """
        )
        row = self._session.execute(
            stmt,
            {
                "status_code": status_code,
                "error_code": (error_code or "")[:80] or None,
                "error_summary": (error_summary or "")[:2000] or None,
                "next_retry_at": next_retry_at,
                "job_id": int(job_id),
                "run_token": run_token,
            },
        ).first()
        self._session.commit()
        return row is not None

    def release_claim(self, job_id: int) -> None:
        self._session.execute(
            text(
                """
                UPDATE operation.market_session_job
                SET status_code = 'SCHEDULED',
                    claimed_by = NULL,
                    claimed_at = NULL,
                    claim_expires_at = NULL,
                    run_token = NULL,
                    updated_at = NOW()
                WHERE market_session_job_id = :job_id
                """
            ),
            {"job_id": int(job_id)},
        )
        self._session.commit()

    def record_run(
        self,
        *,
        job_id: int,
        run_number: int,
        instance_id: str,
        run_token: str | None,
        started_at: datetime | None,
        finished_at: datetime | None,
        status_code: str,
        result_code: str | None,
        result_summary: str | None,
        error_code: str | None = None,
        error_summary: str | None = None,
        calendar_revision: int | None = None,
        scheduled_for: datetime | None = None,
    ) -> MarketSessionJobRunEntity:
        lag_seconds = None
        if started_at is not None and scheduled_for is not None:
            lag_seconds = int((started_at - scheduled_for).total_seconds())
        run = MarketSessionJobRunEntity(
            market_session_job_id=int(job_id),
            run_number=run_number,
            instance_id=instance_id[:200],
            run_token=run_token,
            started_at=started_at,
            finished_at=finished_at,
            status_code=status_code,
            result_code=result_code,
            result_summary=(result_summary or "")[:4000] or None,
            error_code=error_code,
            error_summary=error_summary,
            calendar_revision=calendar_revision,
            scheduled_for=scheduled_for,
            actual_started_at=started_at,
            lag_seconds=lag_seconds,
        )
        self._session.add(run)
        self._session.commit()
        return run

    # ------------------------------------------------------------------
    # 관리자 조작
    # ------------------------------------------------------------------

    def release_stale_claim(
        self, job_id: int, *, actor: str = "ADMIN"
    ) -> dict[str, Any]:
        row = self._session.execute(
            text(
                """
                UPDATE operation.market_session_job
                SET status_code = 'SCHEDULED',
                    claimed_by = NULL,
                    claimed_at = NULL,
                    claim_expires_at = NULL,
                    run_token = NULL,
                    updated_at = NOW()
                WHERE market_session_job_id = :job_id
                  AND claim_expires_at IS NOT NULL
                  AND claim_expires_at < NOW()
                RETURNING market_session_job_id
                """
            ),
            {"job_id": int(job_id)},
        ).first()
        self._session.commit()
        if row is None:
            return {"status": "NOT_STALE_OR_NOT_CLAIMED", "job_id": job_id}
        return {"status": "RELEASED", "job_id": job_id}

    def retry_job(
        self, job_id: int, *, actor: str, reason: str
    ) -> dict[str, Any]:
        row = self.get(job_id)
        if row is None:
            raise MarketSessionJobError("not_found", "Job not found")
        if row.status_code not in {
            MarketSessionJobStatus.FAILED.value,
            MarketSessionJobStatus.RETRY_PENDING.value,
            MarketSessionJobStatus.EXPIRED.value,
            MarketSessionJobStatus.SKIPPED.value,
        }:
            raise MarketSessionJobError(
                "invalid_status",
                f"Cannot retry from {row.status_code}",
            )
        row.status_code = MarketSessionJobStatus.SCHEDULED.value
        row.scheduled_for = _utcnow()
        row.next_retry_at = None
        row.claimed_by = None
        row.claimed_at = None
        row.claim_expires_at = None
        row.run_token = None
        row.updated_at = _utcnow()
        self._session.commit()
        return {"status": "RETRY_SCHEDULED", "job_id": job_id, "actor": actor}

    def cancel_job(
        self, job_id: int, *, actor: str, reason: str
    ) -> dict[str, Any]:
        row = self.get(job_id)
        if row is None:
            raise MarketSessionJobError("not_found", "Job not found")
        if row.status_code in TERMINAL_JOB_STATUSES:
            raise MarketSessionJobError(
                "invalid_status",
                f"Cannot cancel terminal status {row.status_code}",
            )
        row.status_code = MarketSessionJobStatus.CANCELLED.value
        row.claimed_by = None
        row.claimed_at = None
        row.claim_expires_at = None
        row.run_token = None
        row.updated_at = _utcnow()
        self._session.commit()
        return {"status": "CANCELLED", "job_id": job_id, "actor": actor}

    def ensure_wakeup(
        self,
        *,
        exchange_code: str,
        job_type: str,
        market_date: date,
    ) -> dict[str, Any]:
        """Cron Fallback Gate 전용 — Job 존재/기상을 보장하고 실행은 Dispatcher에 위임."""

        exchange = exchange_code.upper()
        stmt = (
            select(MarketSessionJobEntity)
            .where(
                MarketSessionJobEntity.exchange_code == exchange,
                MarketSessionJobEntity.market_date == market_date,
                MarketSessionJobEntity.job_type == job_type,
            )
            .order_by(MarketSessionJobEntity.calendar_revision.desc())
        )
        row = self._session.scalars(stmt).first()
        now = _utcnow()
        if row is None or row.status_code not in (
            ACTIVE_JOB_STATUSES | {MarketSessionJobStatus.SCHEDULED.value}
        ):
            # 활성 Job이 없으면(전부 Superseded/Cancelled/없음) revision 1로 즉시 생성
            revision = (row.calendar_revision + 1) if row else 1
            job_key = build_job_key(
                exchange_code=exchange,
                market_date=market_date,
                job_type=job_type,
                revision=revision,
            )
            new_row = MarketSessionJobEntity(
                exchange_code=exchange,
                market_date=market_date,
                calendar_revision=revision,
                job_type=job_type,
                job_key=job_key,
                scheduled_for=now,
                status_code=MarketSessionJobStatus.SCHEDULED.value,
                payload={"created_by": "cron_wakeup"},
            )
            self._session.add(new_row)
            self._session.commit()
            return {
                "status": "CREATED",
                "job_id": new_row.market_session_job_id,
            }
        if (
            row.status_code == MarketSessionJobStatus.SCHEDULED.value
            and row.scheduled_for > now
        ):
            row.scheduled_for = now
            row.updated_at = now
            self._session.commit()
            return {"status": "WOKEN", "job_id": row.market_session_job_id}
        return {
            "status": "NOOP",
            "job_id": row.market_session_job_id,
            "current_status": row.status_code,
        }

    # ------------------------------------------------------------------
    # 보존(Retention)
    # ------------------------------------------------------------------

    def purge_old_jobs(
        self,
        *,
        retention_days: int,
        run_retention_days: int,
    ) -> dict[str, Any]:
        job_cutoff = _utcnow() - timedelta(days=max(1, retention_days))
        run_cutoff = _utcnow() - timedelta(days=max(1, run_retention_days))

        deleted_runs = self._session.execute(
            text(
                """
                DELETE FROM operation.market_session_job_run
                WHERE created_at < :cutoff
                RETURNING market_session_job_run_id
                """
            ),
            {"cutoff": run_cutoff},
        ).rowcount
        deleted_jobs = self._session.execute(
            text(
                """
                DELETE FROM operation.market_session_job
                WHERE status_code IN (
                    'SUCCEEDED', 'SUPERSEDED', 'EXPIRED', 'CANCELLED',
                    'SKIPPED'
                )
                AND COALESCE(finished_at, updated_at) < :cutoff
                RETURNING market_session_job_id
                """
            ),
            {"cutoff": job_cutoff},
        ).rowcount
        self._session.commit()
        return {
            "deleted_jobs": int(deleted_jobs or 0),
            "deleted_runs": int(deleted_runs or 0),
        }


def job_as_dict(row: MarketSessionJobEntity) -> dict[str, Any]:
    return row.as_dict()
