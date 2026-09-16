"""STEP 8-5-15 — 영속 Market Session Job (DB Claim 기반 Dispatcher/Reconcile) tests.

`_DYNAMIC_JOBS`(프로세스 메모리)를 대체하는 DB Source of Truth의 핵심 계약을
검증한다: Job Key 유일성, 원자적 Claim(다중 인스턴스 경쟁), Revision Supersede,
Dispatcher의 미래 Job Skip/Catch-up 판정, Ownership 상실 시 종료 거부, Reconcile
의 누락 Job 생성, Cron Wakeup의 무한 위임 루프 방지, Admin의 만료 Claim 해제까지
실제 PostgreSQL(Migration 적용됨)을 사용하는 통합 테스트와 순수 로직 단위 테스트로
구성한다.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import sessionmaker

from stock_platform.common.settings import get_settings
from stock_platform.operation.market_session_job_constants import (
    MarketSessionJobResult,
    MarketSessionJobStatus,
    MarketSessionJobType,
    build_job_key,
)
from stock_platform.operation.market_session_job_service import (
    MarketSessionJobService,
    _catchup_eligible,
)
from tests.migration_helpers import (
    alembic_current_head,
    assert_revision_exists,
)

TEST_EXCHANGE = "T815"  # 실 KRX 데이터와 충돌 방지용 전용 테스트 거래소 코드


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------


def test_step8_5_15_revision_head() -> None:
    assert_revision_exists("b5c6d7e8f9a0")
    assert_revision_exists("c6d7e8f9a0b1")
    head = alembic_current_head()
    assert_revision_exists(head)


# ---------------------------------------------------------------------------
# 순수 함수 — Job Key / Catch-up 판정
# ---------------------------------------------------------------------------


def test_build_job_key_format() -> None:
    key = build_job_key(
        exchange_code="krx",
        market_date=date(2026, 8, 26),
        job_type=MarketSessionJobType.KRX_EQUITY_SNAPSHOT.value,
        revision=3,
    )
    assert key == "KRX:2026-08-26:KRX_EQUITY_SNAPSHOT:rev3"


def test_catchup_eligible_future_always_true() -> None:
    now = datetime(2026, 8, 26, 9, 0, tzinfo=timezone.utc)
    future = now + timedelta(hours=1)
    assert _catchup_eligible(
        job_type=MarketSessionJobType.KRX_PREOPEN_RECOVERY.value,
        scheduled_for=future,
        now=now,
        regular_close_at=None,
    )


def test_catchup_eligible_preopen_past_not_eligible() -> None:
    """PREOPEN_RECOVERY는 POST_CLOSE 계열이 아니므로 유예시간 밖이면 재생성 불가."""

    now = datetime(2026, 8, 26, 9, 0, tzinfo=timezone.utc)
    past = now - timedelta(hours=2)
    assert not _catchup_eligible(
        job_type=MarketSessionJobType.KRX_PREOPEN_RECOVERY.value,
        scheduled_for=past,
        now=now,
        regular_close_at=None,
    )


def test_catchup_eligible_postclose_within_grace_window() -> None:
    """POST_CLOSE 계열은 당일 장마감 후 3시간 이내면 Catch-up 생성을 허용."""

    close_at = datetime(2026, 8, 26, 6, 30, tzinfo=timezone.utc)  # KST 15:30
    now = close_at + timedelta(hours=2)
    past_snapshot = close_at + timedelta(minutes=10)
    assert _catchup_eligible(
        job_type=MarketSessionJobType.KRX_EQUITY_SNAPSHOT.value,
        scheduled_for=past_snapshot,
        now=now,
        regular_close_at=close_at,
    )


def test_catchup_eligible_postclose_beyond_grace_window_rejected() -> None:
    close_at = datetime(2026, 8, 26, 6, 30, tzinfo=timezone.utc)
    now = close_at + timedelta(hours=4)
    past_snapshot = close_at + timedelta(minutes=10)
    assert not _catchup_eligible(
        job_type=MarketSessionJobType.KRX_EQUITY_SNAPSHOT.value,
        scheduled_for=past_snapshot,
        now=now,
        regular_close_at=close_at,
    )


# ---------------------------------------------------------------------------
# Preopen 핸들러 — 이미 장이 열린 이후면 SKIPPED_TOO_LATE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_preopen_handler_skips_too_late_when_market_already_open() -> None:
    from stock_platform.operation import market_session_job_handlers as handlers_mod
    from stock_platform.operation.market_session_job_entities import (
        MarketSessionJobEntity,
    )

    handler = handlers_mod.KrxPreopenRecoveryHandler()
    job = MarketSessionJobEntity(
        exchange_code="KRX",
        market_date=date(2026, 8, 26),
        calendar_revision=1,
        job_type=MarketSessionJobType.KRX_PREOPEN_RECOVERY.value,
        job_key="KRX:2026-08-26:KRX_PREOPEN_RECOVERY:rev1",
        scheduled_for=datetime.now(timezone.utc),
        status_code=MarketSessionJobStatus.RUNNING.value,
    )
    fake_timeline = SimpleNamespace(
        regular_open_at=datetime.now(timezone.utc) - timedelta(minutes=5),
    )

    with patch.object(
        handlers_mod._KiwoomRecoveryHandlerBase,
        "_resolve_timeline",
        AsyncMock(return_value=fake_timeline),
    ), patch(
        "stock_platform.broker.recovery_scheduler_service.run_recovery_scheduler_job",
        AsyncMock(),
    ) as fake_run:
        outcome = await handler.handle(MagicMock(), job)

    assert outcome.result_code == MarketSessionJobResult.SKIPPED_TOO_LATE.value
    fake_run.assert_not_called()


# ---------------------------------------------------------------------------
# Cron Wakeup — MARKET_SESSION_JOB Trigger는 위임하지 않음 (무한 루프 방지)
# ---------------------------------------------------------------------------


class _FakeCronSettings:
    krx_cron_fallback_enabled = True
    krx_cron_fallback_early_tolerance_minutes = 5
    krx_cron_fallback_late_tolerance_minutes = 60
    market_session_job_enabled = True
    market_session_cron_wakeup_enabled = True


def test_cron_gate_delegates_for_scheduler_trigger() -> None:
    from stock_platform.broker.recovery_scheduler_service import (
        krx_cron_fallback_gate,
    )

    now = datetime.now(timezone.utc)
    target = now - timedelta(minutes=1)  # 허용범위 내, 미실행
    job = SimpleNamespace(last_run_at=None, last_status=None)
    fake_timeline = SimpleNamespace(
        is_trading_day=True,
        live_allowed=True,
        recovery_preopen_at=target,
        recovery_postclose_at=None,
        revision=7,
    )
    fake_svc = MagicMock()
    fake_svc.ensure_wakeup.return_value = {"status": "WOKEN", "job_id": 1}

    with patch(
        "stock_platform.broker.recovery_scheduler_service.get_settings",
        return_value=_FakeCronSettings(),
    ), patch(
        "stock_platform.operation.session_timeline.resolve_krx_timeline",
        return_value=fake_timeline,
    ), patch(
        "stock_platform.operation.market_session_job_service.MarketSessionJobService",
        return_value=fake_svc,
    ):
        result = krx_cron_fallback_gate(
            MagicMock(),
            job_id="broker_recovery_kiwoom_preopen",
            job=job,
            trigger_type="SCHEDULER",
        )

    assert result is not None
    assert result["status"] == "DELEGATED_TO_MARKET_SESSION_JOB"
    fake_svc.ensure_wakeup.assert_called_once()


def test_cron_gate_does_not_delegate_for_market_session_job_trigger() -> None:
    """Dispatcher Handler가 재호출할 때는 위임하지 않고 실제 실행을 허용한다."""

    from stock_platform.broker.recovery_scheduler_service import (
        krx_cron_fallback_gate,
    )

    now = datetime.now(timezone.utc)
    target = now - timedelta(minutes=1)
    job = SimpleNamespace(last_run_at=None, last_status=None)
    fake_timeline = SimpleNamespace(
        is_trading_day=True,
        live_allowed=True,
        recovery_preopen_at=target,
        recovery_postclose_at=None,
        revision=7,
    )
    fake_svc = MagicMock()

    with patch(
        "stock_platform.broker.recovery_scheduler_service.get_settings",
        return_value=_FakeCronSettings(),
    ), patch(
        "stock_platform.operation.session_timeline.resolve_krx_timeline",
        return_value=fake_timeline,
    ), patch(
        "stock_platform.operation.market_session_job_service.MarketSessionJobService",
        return_value=fake_svc,
    ):
        result = krx_cron_fallback_gate(
            MagicMock(),
            job_id="broker_recovery_kiwoom_preopen",
            job=job,
            trigger_type="MARKET_SESSION_JOB",
        )

    assert result is None
    fake_svc.ensure_wakeup.assert_not_called()


# ---------------------------------------------------------------------------
# Reconcile — 누락 Job 생성 (완전 Mock, DB 불필요)
# ---------------------------------------------------------------------------


def test_reconcile_creates_missing_jobs_for_verified_trading_day() -> None:
    from stock_platform.operation.market_session_job_reconcile import (
        MarketSessionJobReconciliationService,
    )

    session = MagicMock()
    svc = MarketSessionJobReconciliationService(session)

    verified_day = SimpleNamespace(
        is_trading_day=True,
        verified_status="VERIFIED",
        revision=1,
        session_type="REGULAR",
        regular_open_at=None,
        regular_close_at=None,
        preopen_at=None,
        timezone="Asia/Seoul",
    )
    unverified_day = SimpleNamespace(
        is_trading_day=True,
        verified_status="PENDING_REVIEW",
        revision=1,
        session_type="REGULAR",
        regular_open_at=None,
        regular_close_at=None,
        preopen_at=None,
        timezone="Asia/Seoul",
    )

    day_by_offset = {0: verified_day, 1: unverified_day}
    today = datetime.now().date()

    def _fake_get_day(*, exchange_code, calendar_date):
        offset = (calendar_date - today).days
        return day_by_offset.get(offset)

    svc._repo.get_day = _fake_get_day  # type: ignore[method-assign]
    svc._svc.create_or_supersede_for_revision = MagicMock(  # type: ignore[method-assign]
        return_value={"created": [{"job_type": "X", "job_id": 1}], "skipped": []}
    )
    svc._expire_stale_claims = MagicMock(return_value=0)  # type: ignore[method-assign]

    result = svc.reconcile(exchange_code="KRX", days_ahead=1)

    # 검증된 거래일(offset=0)만 처리되고, 미검증(offset=1)은 건너뛴다.
    assert result["checked_days"] == 1
    assert result["created"] == 1
    svc._svc.create_or_supersede_for_revision.assert_called_once()
    session.commit.assert_called()


# ---------------------------------------------------------------------------
# Claim / Supersede / Ownership — 실제 PostgreSQL (Migration 적용됨)
# ---------------------------------------------------------------------------


def _get_pg_session_factory():
    settings = get_settings()
    engine = create_engine(settings.database_url)
    return engine, sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _cleanup_test_jobs(factory) -> None:
    cleanup = factory()
    try:
        cleanup.execute(
            text(
                "DELETE FROM operation.market_session_job "
                "WHERE exchange_code = :ex"
            ),
            {"ex": TEST_EXCHANGE},
        )
        cleanup.commit()
    finally:
        cleanup.close()


@pytest.mark.integration
def test_job_key_uniqueness_constraint_real_db() -> None:
    engine, factory = _get_pg_session_factory()
    try:
        with engine.connect() as probe:
            probe.execute(text("SELECT 1"))
    except OperationalError as exc:
        pytest.fail(f"PostgreSQL 연결 불가: {exc}")

    session = factory()
    market_date = date(2099, 1, 5)
    job_key = build_job_key(
        exchange_code=TEST_EXCHANGE,
        market_date=market_date,
        job_type=MarketSessionJobType.KRX_EQUITY_SNAPSHOT.value,
        revision=1,
    )
    try:
        _cleanup_test_jobs(factory)
        session.execute(
            text(
                """
                INSERT INTO operation.market_session_job (
                    exchange_code, market_date, calendar_revision, job_type,
                    job_key, scheduled_for, status_code
                ) VALUES (
                    :ex, :d, 1, 'KRX_EQUITY_SNAPSHOT', :key, NOW(), 'SCHEDULED'
                )
                """
            ),
            {"ex": TEST_EXCHANGE, "d": market_date, "key": job_key},
        )
        session.commit()

        with pytest.raises(IntegrityError):
            session.execute(
                text(
                    """
                    INSERT INTO operation.market_session_job (
                        exchange_code, market_date, calendar_revision,
                        job_type, job_key, scheduled_for, status_code
                    ) VALUES (
                        :ex, :d, 1, 'KRX_EQUITY_SNAPSHOT', :key, NOW(),
                        'SCHEDULED'
                    )
                    """
                ),
                {"ex": TEST_EXCHANGE, "d": market_date, "key": job_key},
            )
            session.commit()
        session.rollback()
    finally:
        session.close()
        _cleanup_test_jobs(factory)


@pytest.mark.integration
def test_claim_exclusive_and_expired_reclaim_real_db() -> None:
    engine, factory = _get_pg_session_factory()
    try:
        with engine.connect() as probe:
            probe.execute(text("SELECT 1"))
    except OperationalError as exc:
        pytest.fail(f"PostgreSQL 연결 불가: {exc}")

    session = factory()
    market_date = date(2099, 1, 6)
    job_key = build_job_key(
        exchange_code=TEST_EXCHANGE,
        market_date=market_date,
        job_type=MarketSessionJobType.KRX_PREOPEN_RECOVERY.value,
        revision=1,
    )
    job_id: int | None = None
    try:
        _cleanup_test_jobs(factory)
        job_id = int(
            session.execute(
                text(
                    """
                    INSERT INTO operation.market_session_job (
                        exchange_code, market_date, calendar_revision,
                        job_type, job_key, scheduled_for, status_code
                    ) VALUES (
                        :ex, :d, 1, 'KRX_PREOPEN_RECOVERY', :key,
                        NOW() - INTERVAL '1 second', 'SCHEDULED'
                    )
                    RETURNING market_session_job_id
                    """
                ),
                {"ex": TEST_EXCHANGE, "d": market_date, "key": job_key},
            ).scalar_one()
        )
        session.commit()

        svc = MarketSessionJobService(session)

        first = svc.try_claim(job_id, instance_id="inst-a", claim_seconds=60)
        assert first is not None, "첫 Claim은 성공해야 한다"

        second = svc.try_claim(job_id, instance_id="inst-b", claim_seconds=60)
        assert second is None, "이미 유효한 Claim이 있으면 재claim 불가"

        # run_token 불일치로 종료 시도 → Ownership 상실로 거부되어야 한다.
        assert svc.mark_running(job_id, run_token=first) is True
        lost = svc.finish_job(
            job_id,
            run_token="wrong-token",
            status_code=MarketSessionJobStatus.SUCCEEDED.value,
        )
        assert lost is False, "run_token이 다르면 종료 처리가 거부되어야 한다"

        # 올바른 run_token으로는 정상 종료된다.
        ok = svc.finish_job(
            job_id,
            run_token=first,
            status_code=MarketSessionJobStatus.SUCCEEDED.value,
        )
        assert ok is True

        # Claim을 강제로 만료시킨 뒤 재claim 가능해야 한다 (재시도 대비 시나리오).
        session.execute(
            text(
                """
                UPDATE operation.market_session_job
                SET status_code = 'RETRY_PENDING', claim_expires_at = NULL,
                    claimed_by = NULL, run_token = NULL
                WHERE market_session_job_id = :id
                """
            ),
            {"id": job_id},
        )
        session.commit()
        third = svc.try_claim(job_id, instance_id="inst-c", claim_seconds=60)
        assert third is not None, "RETRY_PENDING 상태는 재claim 가능해야 한다"
    finally:
        session.close()
        _cleanup_test_jobs(factory)


@pytest.mark.integration
def test_supersede_previous_revision_real_db() -> None:
    engine, factory = _get_pg_session_factory()
    try:
        with engine.connect() as probe:
            probe.execute(text("SELECT 1"))
    except OperationalError as exc:
        pytest.fail(f"PostgreSQL 연결 불가: {exc}")

    session = factory()
    market_date = date(2099, 1, 7)
    try:
        _cleanup_test_jobs(factory)
        future = datetime.now(timezone.utc) + timedelta(days=1)
        timeline_rev1 = SimpleNamespace(
            recovery_preopen_at=future,
            recovery_postclose_at=future + timedelta(hours=6),
            snapshot_at=future + timedelta(hours=6, minutes=10),
            settlement_at=future + timedelta(hours=6, minutes=20),
            analysis_at=future + timedelta(hours=6, minutes=30),
            regular_close_at=future + timedelta(hours=5, minutes=30),
        )
        svc = MarketSessionJobService(session)
        result1 = svc.create_or_supersede_for_revision(
            exchange_code=TEST_EXCHANGE,
            market_date=market_date,
            revision=1,
            timeline=timeline_rev1,
        )
        session.commit()
        assert len(result1["created"]) == 5

        timeline_rev2 = SimpleNamespace(
            recovery_preopen_at=future + timedelta(minutes=5),
            recovery_postclose_at=future + timedelta(hours=6, minutes=5),
            snapshot_at=future + timedelta(hours=6, minutes=15),
            settlement_at=future + timedelta(hours=6, minutes=25),
            analysis_at=future + timedelta(hours=6, minutes=35),
            regular_close_at=future + timedelta(hours=5, minutes=35),
        )
        result2 = svc.create_or_supersede_for_revision(
            exchange_code=TEST_EXCHANGE,
            market_date=market_date,
            revision=2,
            timeline=timeline_rev2,
        )
        session.commit()
        assert result2["superseded"] == 5
        assert len(result2["created"]) == 5

        rows = svc.list_for_date(
            exchange_code=TEST_EXCHANGE, market_date=market_date
        )
        rev1_rows = [r for r in rows if r.calendar_revision == 1]
        rev2_rows = [r for r in rows if r.calendar_revision == 2]
        assert len(rev1_rows) == 5
        assert all(
            r.status_code == MarketSessionJobStatus.SUPERSEDED.value
            for r in rev1_rows
        )
        assert len(rev2_rows) == 5
        assert all(
            r.status_code == MarketSessionJobStatus.SCHEDULED.value
            for r in rev2_rows
        )
    finally:
        session.close()
        _cleanup_test_jobs(factory)


@pytest.mark.integration
def test_dispatcher_skips_future_scheduled_job_real_db() -> None:
    engine, factory = _get_pg_session_factory()
    try:
        with engine.connect() as probe:
            probe.execute(text("SELECT 1"))
    except OperationalError as exc:
        pytest.fail(f"PostgreSQL 연결 불가: {exc}")

    session = factory()
    market_date = date(2099, 1, 8)
    try:
        _cleanup_test_jobs(factory)
        job_key_future = build_job_key(
            exchange_code=TEST_EXCHANGE,
            market_date=market_date,
            job_type=MarketSessionJobType.KRX_SETTLEMENT.value,
            revision=1,
        )
        job_key_due = build_job_key(
            exchange_code=TEST_EXCHANGE,
            market_date=market_date,
            job_type=MarketSessionJobType.KRX_AI_ANALYSIS.value,
            revision=1,
        )
        due_id = int(
            session.execute(
                text(
                    """
                    INSERT INTO operation.market_session_job (
                        exchange_code, market_date, calendar_revision,
                        job_type, job_key, scheduled_for, status_code
                    ) VALUES (
                        :ex, :d, 1, 'KRX_AI_ANALYSIS', :key,
                        NOW() - INTERVAL '1 minute', 'SCHEDULED'
                    ) RETURNING market_session_job_id
                    """
                ),
                {"ex": TEST_EXCHANGE, "d": market_date, "key": job_key_due},
            ).scalar_one()
        )
        session.execute(
            text(
                """
                INSERT INTO operation.market_session_job (
                    exchange_code, market_date, calendar_revision,
                    job_type, job_key, scheduled_for, status_code
                ) VALUES (
                    :ex, :d, 1, 'KRX_SETTLEMENT', :key,
                    NOW() + INTERVAL '1 day', 'SCHEDULED'
                )
                """
            ),
            {"ex": TEST_EXCHANGE, "d": market_date, "key": job_key_future},
        )
        session.commit()

        due_ids = MarketSessionJobService(session).select_due_job_ids(limit=50)
        assert due_id in due_ids
        # 미래 Job은 due 목록에 포함되지 않아야 한다.
        future_ids = [
            r.market_session_job_id
            for r in MarketSessionJobService(session).list_for_date(
                exchange_code=TEST_EXCHANGE, market_date=market_date
            )
            if r.job_type == MarketSessionJobType.KRX_SETTLEMENT.value
        ]
        assert not set(future_ids) & set(due_ids)
    finally:
        session.close()
        _cleanup_test_jobs(factory)


@pytest.mark.integration
def test_admin_release_stale_claim_real_db() -> None:
    engine, factory = _get_pg_session_factory()
    try:
        with engine.connect() as probe:
            probe.execute(text("SELECT 1"))
    except OperationalError as exc:
        pytest.fail(f"PostgreSQL 연결 불가: {exc}")

    session = factory()
    market_date = date(2099, 1, 9)
    try:
        _cleanup_test_jobs(factory)
        job_key = build_job_key(
            exchange_code=TEST_EXCHANGE,
            market_date=market_date,
            job_type=MarketSessionJobType.KRX_POSTCLOSE_RECOVERY.value,
            revision=1,
        )
        job_id = int(
            session.execute(
                text(
                    """
                    INSERT INTO operation.market_session_job (
                        exchange_code, market_date, calendar_revision,
                        job_type, job_key, scheduled_for, status_code,
                        claimed_by, claimed_at, claim_expires_at, run_token
                    ) VALUES (
                        :ex, :d, 1, 'KRX_POSTCLOSE_RECOVERY', :key, NOW(),
                        'CLAIMED', 'stale-instance', NOW() - INTERVAL '10 minutes',
                        NOW() - INTERVAL '5 minutes', 'stale-token'
                    ) RETURNING market_session_job_id
                    """
                ),
                {"ex": TEST_EXCHANGE, "d": market_date, "key": job_key},
            ).scalar_one()
        )
        session.commit()

        svc = MarketSessionJobService(session)
        not_stale = svc.release_stale_claim(job_id + 1_000_000)
        assert not_stale["status"] == "NOT_STALE_OR_NOT_CLAIMED"

        released = svc.release_stale_claim(job_id, actor="admin-tester")
        assert released["status"] == "RELEASED"

        row = svc.get(job_id)
        assert row is not None
        assert row.status_code == MarketSessionJobStatus.SCHEDULED.value
        assert row.claimed_by is None
        assert row.claim_expires_at is None
    finally:
        session.close()
        _cleanup_test_jobs(factory)
