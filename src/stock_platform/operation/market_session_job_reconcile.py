"""STEP 8-5-15 — Market Session Job Reconciliation Service.

향후 N일(``market_session_job_reconcile_days_ahead``)의 VERIFIED KRX 거래일에
누락된 Job을 채워 넣고, 오래 방치된 Claim을 EXPIRED로 정리한다. Admin 수동
트리거(`/reconcile`)와 주기 Scheduler에서 공용으로 사용한다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.common.settings import get_settings
from stock_platform.operation.calendar_constants import KRX_TIMEZONE
from stock_platform.operation.calendar_repository import (
    TradingCalendarRepository,
)
from stock_platform.operation.market_session_job_constants import (
    MarketSessionJobStatus,
)
from stock_platform.operation.market_session_job_entities import (
    MarketSessionJobEntity,
)
from stock_platform.operation.market_session_job_service import (
    MarketSessionJobService,
)
from stock_platform.operation.session_timeline import (
    TradingSessionTimelineResolver,
)

# Claim 만료 후 이 유예시간이 더 지나야 EXPIRED로 확정한다
# (Dispatcher가 종료 처리 중인 짧은 순간과의 경합 방지).
_EXPIRE_GRACE = timedelta(minutes=10)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MarketSessionJobReconciliationService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = TradingCalendarRepository(session)
        self._svc = MarketSessionJobService(session)

    def reconcile(
        self,
        *,
        exchange_code: str = "KRX",
        days_ahead: int | None = None,
    ) -> dict[str, Any]:
        settings = get_settings()
        days = (
            days_ahead
            if days_ahead is not None
            else int(settings.market_session_job_reconcile_days_ahead)
        )
        tz = ZoneInfo(KRX_TIMEZONE)
        today = datetime.now(tz).date()
        resolver = TradingSessionTimelineResolver()

        created_total = 0
        skipped_total = 0
        checked_days = 0

        for offset in range(0, max(0, days) + 1):
            market_date = today + timedelta(days=offset)
            row = self._repo.get_day(
                exchange_code=exchange_code, calendar_date=market_date
            )
            if row is None or not bool(row.is_trading_day):
                continue
            if str(getattr(row, "verified_status", "")) != "VERIFIED":
                continue
            checked_days += 1
            revision = int(getattr(row, "revision", 1) or 1)
            timeline = resolver.resolve_from_decision(
                exchange_code=exchange_code,
                market_date=market_date,
                is_trading_day=True,
                live_allowed=True,
                reason_code="CALENDAR_OPEN",
                session_type=row.session_type,
                regular_open_at=row.regular_open_at,
                regular_close_at=row.regular_close_at,
                preopen_at=getattr(row, "preopen_at", None),
                revision=revision,
                timezone=getattr(row, "timezone", None) or KRX_TIMEZONE,
            )
            result = self._svc.create_or_supersede_for_revision(
                exchange_code=exchange_code,
                market_date=market_date,
                revision=revision,
                timeline=timeline,
            )
            created_total += len(result.get("created") or [])
            skipped_total += len(result.get("skipped") or [])

        expired = self._expire_stale_claims()
        self._session.commit()

        return {
            "status": "OK",
            "checked_days": checked_days,
            "created": created_total,
            "skipped": skipped_total,
            "expired_claims": expired,
        }

    def _expire_stale_claims(self) -> int:
        """장시간(유예 포함) 방치된 CLAIMED/RUNNING Job을 EXPIRED로 전환."""

        cutoff = _utcnow() - _EXPIRE_GRACE
        stmt = select(MarketSessionJobEntity).where(
            MarketSessionJobEntity.status_code.in_(
                [
                    MarketSessionJobStatus.CLAIMED.value,
                    MarketSessionJobStatus.RUNNING.value,
                ]
            ),
            MarketSessionJobEntity.claim_expires_at.is_not(None),
            MarketSessionJobEntity.claim_expires_at < cutoff,
        )
        rows = list(self._session.scalars(stmt))
        now = _utcnow()
        for row in rows:
            row.status_code = MarketSessionJobStatus.EXPIRED.value
            row.claimed_by = None
            row.claimed_at = None
            row.claim_expires_at = None
            row.run_token = None
            row.updated_at = now
        if rows:
            self._session.flush()
        return len(rows)

    def maybe_purge(self) -> dict[str, Any]:
        settings = get_settings()
        return self._svc.purge_old_jobs(
            retention_days=int(
                settings.market_session_job_retention_days
            ),
            run_retention_days=int(
                settings.market_session_job_run_retention_days
            ),
        )
