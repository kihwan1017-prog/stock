"""STEP 8-5-14 — Upbit Ambiguous Resolver Scheduler (DB Claim / Lock) tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from stock_platform.broker.recovery_distributed_lock import (
    DistributedRecoveryLockManager,
    LockAcquireResult,
    LockOwnershipLostError,
    RecoveryLockHandle,
)
from stock_platform.broker.upbit import ambiguous_resolution_service as svc_mod
from stock_platform.broker.upbit.ambiguous_resolution_entities import (
    UpbitAmbiguousResolutionRunEntity,
)
from stock_platform.broker.upbit.ambiguous_resolution_service import (
    UpbitAmbiguousOrderResolutionService,
)
from stock_platform.common.settings import get_settings
from tests.migration_helpers import (
    alembic_current_head,
    assert_revision_exists,
)


def test_step8_5_14_revision_head() -> None:
    assert_revision_exists("a4b5c6d7e8f9")
    assert_revision_exists("b5c6d7e8f9a0")
    head = alembic_current_head()
    assert_revision_exists(head)


def _fake_settings(**overrides) -> SimpleNamespace:
    base = dict(
        upbit_ambiguous_resolver_enabled=True,
        upbit_ambiguous_resolver_batch_size=20,
        upbit_ambiguous_max_orders_per_account_per_run=5,
        upbit_ambiguous_resolver_claim_seconds=60,
        upbit_ambiguous_lookup_max_interval_seconds=60,
        upbit_ambiguous_resolver_run_history_days=30,
        recovery_distributed_lock_enabled=False,
        recovery_lock_lease_seconds=120,
        recovery_lock_heartbeat_seconds=30,
        recovery_lock_acquire_timeout_seconds=5.0,
        recovery_lock_namespace="stock-platform-recovery-test",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _row(order_id: int, uba_id: int | None, ambiguous_since=None):
    return SimpleNamespace(
        order_id=order_id,
        user_broker_account_id=uba_id,
        ambiguous_since=ambiguous_since,
    )


# ---------------------------------------------------------------------------
# 순수 함수 — Fairness / Bucket 매핑
# ---------------------------------------------------------------------------


def test_apply_fairness_caps_per_account() -> None:
    rows = [_row(i, uba_id=1) for i in range(10)] + [
        _row(100 + i, uba_id=2) for i in range(2)
    ]
    out = UpbitAmbiguousOrderResolutionService._apply_fairness(
        rows, batch_size=6, max_per_account=3
    )
    ids_by_account = {}
    for r in out:
        ids_by_account.setdefault(r.user_broker_account_id, []).append(
            r.order_id
        )
    assert len(ids_by_account.get(1, [])) <= 3
    assert len(ids_by_account.get(2, [])) <= 3
    assert len(out) <= 6
    # 계좌 1 은 오래된(작은 order_id) 순서 유지
    assert ids_by_account[1] == sorted(ids_by_account[1])


def test_apply_fairness_no_single_account_monopoly() -> None:
    rows = [_row(i, uba_id=1) for i in range(20)] + [_row(200, uba_id=2)]
    out = UpbitAmbiguousOrderResolutionService._apply_fairness(
        rows, batch_size=5, max_per_account=10
    )
    # 계좌 2 는 데이터가 1건뿐이지만 Round-robin 덕분에 배치에 포함된다.
    assert any(r.order_id == 200 for r in out)


def test_bucket_for_outcome_mapping() -> None:
    fn = UpbitAmbiguousOrderResolutionService._bucket_for_outcome
    assert fn({"status": "FOUND_MATCHED"}) == "found_count"
    assert fn({"status": "MANUAL_REVIEW_REQUIRED"}) == "manual_review_count"
    assert fn({"status": "CONFLICT"}) == "conflict_count"
    assert fn({"status": "FOUND_MISMATCHED"}) == "conflict_count"
    assert fn({"status": "NOT_FOUND_TRANSIENT"}) == "not_found_count"
    assert fn({"status": "RATE_LIMITED"}) == "not_found_count"
    assert fn({"status": "SOMETHING_UNKNOWN"}) == "error_count"


# ---------------------------------------------------------------------------
# Scheduler Disabled
# ---------------------------------------------------------------------------


def test_run_once_disabled_never_touches_db() -> None:
    session = MagicMock()
    lock_manager = MagicMock()
    service = UpbitAmbiguousOrderResolutionService(
        session,
        settings=_fake_settings(upbit_ambiguous_resolver_enabled=False),
        lock_manager=lock_manager,
    )
    result = service.run_once()
    assert result["status"] == "DISABLED"
    session.execute.assert_not_called()
    session.commit.assert_not_called()


def test_run_once_no_due_skips_run_row() -> None:
    session = MagicMock()
    lock_manager = MagicMock()
    service = UpbitAmbiguousOrderResolutionService(
        session,
        settings=_fake_settings(),
        lock_manager=lock_manager,
    )
    service._select_due_candidates = lambda *, limit: []  # type: ignore[method-assign]
    result = service.run_once()
    assert result["status"] == "NO_DUE"
    assert result["due_count"] == 0
    # RUNNING Row 를 만들지 않아야 한다 (빈 폴링 감사 로그 skip)
    session.add.assert_not_called()


# ---------------------------------------------------------------------------
# Lock Busy → Attempt 미증가, Claim 해제
# ---------------------------------------------------------------------------


def test_lock_busy_defers_without_attempt_and_records_lock_attempt() -> None:
    session = MagicMock()
    lock_manager = MagicMock()
    lock_manager.acquire.return_value = (LockAcquireResult.BUSY, None)
    service = UpbitAmbiguousOrderResolutionService(
        session,
        settings=_fake_settings(),
        lock_manager=lock_manager,
    )
    calls: list[tuple] = []
    service._defer_without_attempt = (  # type: ignore[method-assign]
        lambda order_id, *, seconds: calls.append(("defer", order_id, seconds))
    )
    session.get.return_value = SimpleNamespace(
        client_order_identifier="spu-x",
        remote_lookup_attempt_count=0,
    )

    outcome = service._process_claimed_order(
        order_id=42, uba_id=7, run_token="tok-1"
    )

    assert outcome["bucket"] == "lock_busy_count"
    assert calls and calls[0][0] == "defer" and calls[0][1] == 42
    # Lock 이 획득되지 않았으므로 release() 는 호출되지 않는다.
    lock_manager.release.assert_not_called()
    # LOCK_NOT_ACQUIRED Attempt 기록은 남긴다 (실제 원격 조회 Attempt 아님).
    added = [c.args[0] for c in session.add.call_args_list]
    assert any(
        getattr(a, "result_type", None) == "LOCK_NOT_ACQUIRED"
        for a in added
    )


def test_lock_ownership_lost_rolls_back_and_does_not_confirm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock()
    session.get.return_value = SimpleNamespace(
        client_order_identifier="spu-x", remote_lookup_attempt_count=0
    )
    lock_manager = MagicMock(spec=DistributedRecoveryLockManager)
    handle = RecoveryLockHandle(
        lock_scope_key="rlk:test",
        owner_instance_id="inst-a",
        lease_id="lease-1",
        fencing_token=1,
        acquired_at=datetime.now(timezone.utc),
        lease_expires_at=datetime.now(timezone.utc),
        acquire_result=LockAcquireResult.ACQUIRED,
    )
    lock_manager.acquire.return_value = (LockAcquireResult.ACQUIRED, handle)
    lock_manager.assert_owns.side_effect = LockOwnershipLostError("lost")

    service = UpbitAmbiguousOrderResolutionService(
        session,
        settings=_fake_settings(),
        lock_manager=lock_manager,
    )

    class _FakeCredStatus:
        verification_status = "VERIFIED"

    fake_cred_service = MagicMock()
    fake_cred_service.status.return_value = _FakeCredStatus()
    monkeypatch.setattr(
        svc_mod,
        "BrokerCredentialVaultService",
        MagicMock(return_value=fake_cred_service),
    )
    monkeypatch.setattr(
        svc_mod,
        "get_upbit_rate_limit_coordinator",
        MagicMock(
            return_value=MagicMock(
                check_allowed=MagicMock(return_value=(True, None, 0.0))
            )
        ),
    )
    fake_resolver = MagicMock()
    fake_resolver.resolve_one.return_value = {"status": "FOUND_MATCHED"}
    monkeypatch.setattr(
        svc_mod,
        "UpbitAmbiguousOrderResolver",
        MagicMock(return_value=fake_resolver),
    )

    outcome = service._process_claimed_order(
        order_id=99, uba_id=5, run_token="tok-2"
    )

    assert outcome["bucket"] == "error_count"
    assert outcome["reason"] == "LOCK_OWNERSHIP_LOST"
    session.rollback.assert_called()
    # 성공 확정(release_claim commit=False 이후 최종 commit) 경로로 가지 않는다.
    lock_manager.release.assert_called()


# ---------------------------------------------------------------------------
# Attempt 는 실제 원격 API 호출 직전에만 증가한다
# ---------------------------------------------------------------------------


def test_resolve_one_does_not_bump_attempt_when_deferred() -> None:
    from stock_platform.broker.upbit.ambiguous_resolver import (
        UpbitAmbiguousOrderResolver,
    )

    future = datetime.now(timezone.utc) + timedelta(seconds=60)
    order = SimpleNamespace(
        order_id=1,
        broker_code="UPBIT",
        client_order_identifier="spu-aaaa",
        remote_lookup_attempt_count=3,
        next_remote_lookup_at=future,
        ambiguous_since=datetime.now(timezone.utc),
        status_code="AMBIGUOUS_SUBMISSION",
    )
    session = MagicMock()
    repo = MagicMock()
    repo.get.return_value = order
    resolver = UpbitAmbiguousOrderResolver(session)
    resolver._repo = repo

    out = resolver.resolve_one(1, force=False)

    assert out["status"] == "DEFERRED"
    # Attempt 는 여전히 3 — Deferred 경로에서 증가하지 않았다.
    assert order.remote_lookup_attempt_count == 3


def test_resolve_one_bumps_attempt_only_right_before_api_call() -> None:
    from stock_platform.broker.upbit.ambiguous_resolver import (
        UpbitAmbiguousOrderResolver,
    )

    order = SimpleNamespace(
        order_id=2,
        broker_code="UPBIT",
        client_order_identifier="spu-bbbb",
        remote_lookup_attempt_count=0,
        next_remote_lookup_at=None,
        ambiguous_since=datetime.now(timezone.utc),
        status_code="AMBIGUOUS_SUBMISSION",
        user_broker_account_id=1,
    )
    session = MagicMock()
    repo = MagicMock()
    repo.get.return_value = order
    resolver = UpbitAmbiguousOrderResolver(session)
    resolver._repo = repo
    resolver._audit = lambda *a, **k: None  # type: ignore[method-assign]

    attempt_seen_at_call_time = {}

    class _FakeClient:
        def get_order(self, *, identifier: str) -> dict:
            attempt_seen_at_call_time["value"] = (
                order.remote_lookup_attempt_count
            )
            raise RuntimeError("stop before full flow")

    resolver._client = _FakeClient()

    with pytest.raises(RuntimeError):
        resolver.resolve_one(2, force=True)

    # get_order 호출 시점에는 이미 Attempt 가 1로 증가해 있어야 한다.
    assert attempt_seen_at_call_time["value"] == 1


# ---------------------------------------------------------------------------
# 배치 크기 / 계좌당 상한
# ---------------------------------------------------------------------------


def test_run_once_respects_batch_size_and_per_account_limit() -> None:
    session = MagicMock()
    lock_manager = MagicMock()
    settings = _fake_settings(
        upbit_ambiguous_resolver_batch_size=3,
        upbit_ambiguous_max_orders_per_account_per_run=1,
    )
    service = UpbitAmbiguousOrderResolutionService(
        session, settings=settings, lock_manager=lock_manager
    )
    rows = [_row(i, uba_id=(i % 5) + 1) for i in range(20)]
    service._select_due_candidates = lambda *, limit: rows  # type: ignore[method-assign]
    fake_run = UpbitAmbiguousResolutionRunEntity(
        trigger_type="SCHEDULER", status_code="RUNNING", due_count=20
    )
    fake_run.upbit_ambiguous_resolution_run_id = 1
    service._start_run = lambda **kwargs: fake_run  # type: ignore[method-assign]
    service._audit_run = lambda *a, **k: None  # type: ignore[method-assign]
    claimed_orders: list[int] = []
    service._try_claim = (  # type: ignore[method-assign]
        lambda order_id, *, run_token, claim_seconds: (
            claimed_orders.append(order_id) or True
        )
    )
    service._process_claimed_order = (  # type: ignore[method-assign]
        lambda *, order_id, uba_id, run_token: {
            "order_id": order_id,
            "bucket": "found_count",
        }
    )

    result = service.run_once()

    assert result["claimed_count"] == 3
    assert len(claimed_orders) == 3
    # 계좌당 최대 1건이므로 3개 계좌에서 각 1건씩 뽑혔어야 한다.
    assert len(set(o % 5 for o in claimed_orders)) == 3


# ---------------------------------------------------------------------------
# Run History 영속화
# ---------------------------------------------------------------------------


def test_run_history_persisted_with_counters() -> None:
    session = MagicMock()
    service = UpbitAmbiguousOrderResolutionService(
        session, settings=_fake_settings(), lock_manager=MagicMock()
    )
    run = UpbitAmbiguousResolutionRunEntity(
        trigger_type="SCHEDULER",
        status_code="RUNNING",
        due_count=5,
    )
    run.started_at = datetime.now(timezone.utc) - timedelta(seconds=2)

    counters = {
        "claimed_count": 3,
        "found_count": 2,
        "not_found_count": 1,
        "manual_review_count": 0,
        "conflict_count": 0,
        "lock_busy_count": 0,
        "credential_blocked_count": 0,
        "rate_limited_count": 0,
        "error_count": 0,
    }
    status_code = service._finish_run(run, counters=counters, details=[])

    assert status_code == "SUCCEEDED"
    assert run.found_count == 2
    assert run.not_found_count == 1
    assert run.claimed_count == 3
    assert run.finished_at is not None
    assert run.duration_ms is not None and run.duration_ms >= 0
    session.commit.assert_called()


def test_run_history_partial_when_some_errors() -> None:
    session = MagicMock()
    service = UpbitAmbiguousOrderResolutionService(
        session, settings=_fake_settings(), lock_manager=MagicMock()
    )
    run = UpbitAmbiguousResolutionRunEntity(
        trigger_type="SCHEDULER", status_code="RUNNING", due_count=4
    )
    run.started_at = datetime.now(timezone.utc)
    counters = {
        "claimed_count": 4,
        "found_count": 3,
        "not_found_count": 0,
        "manual_review_count": 0,
        "conflict_count": 0,
        "lock_busy_count": 0,
        "credential_blocked_count": 0,
        "rate_limited_count": 0,
        "error_count": 1,
    }
    status_code = service._finish_run(run, counters=counters, details=[])
    assert status_code == "PARTIAL"


# ---------------------------------------------------------------------------
# Claim / Reclaim / Release Stale — 실제 PostgreSQL (Migration 적용됨)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_claim_exclusive_and_expired_reclaim_real_db() -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    try:
        with engine.connect() as probe:
            probe.execute(text("SELECT 1"))
    except OperationalError as exc:
        pytest.fail(f"PostgreSQL 연결 불가: {exc}")

    session = factory()
    order_id: int | None = None
    identifier = f"spu-t-{uuid4().hex[:24]}"
    try:
        order_id = int(
            session.execute(
                text(
                    """
                    INSERT INTO trading.trading_order (
                        client_order_id, account_id, broker_code,
                        exchange_code, symbol, side_code, order_type_code,
                        order_quantity, remaining_quantity, status_code,
                        client_order_identifier, next_remote_lookup_at,
                        ambiguous_since
                    ) VALUES (
                        :cid, 1, 'UPBIT', 'UPBIT', 'BTC', 'BUY', 'LIMIT',
                        1, 1, 'AMBIGUOUS_SUBMISSION',
                        :ident, NOW() - INTERVAL '1 second', NOW()
                    )
                    RETURNING order_id
                    """
                ),
                {"cid": f"race-{uuid4().hex[:16]}", "ident": identifier},
            ).scalar_one()
        )
        session.commit()

        service = UpbitAmbiguousOrderResolutionService(
            session,
            settings=_fake_settings(),
            lock_manager=MagicMock(),
        )

        first = service._try_claim(
            order_id, run_token="run-a", claim_seconds=60
        )
        assert first is True

        second = service._try_claim(
            order_id, run_token="run-b", claim_seconds=60
        )
        assert second is False, "이미 유효한 Claim 이 있으면 재claim 불가"

        # Claim 을 강제로 만료시킨 뒤 재claim 가능해야 한다.
        session.execute(
            text(
                """
                UPDATE trading.trading_order
                SET resolver_claim_expires_at = NOW() - INTERVAL '1 second'
                WHERE order_id = :order_id
                """
            ),
            {"order_id": order_id},
        )
        session.commit()

        third = service._try_claim(
            order_id, run_token="run-c", claim_seconds=60
        )
        assert third is True, "만료된 Claim 은 재claim 되어야 한다"

        stale = service.release_stale_claim(order_id)
        assert stale["status"] == "NOT_STALE_OR_NOT_CLAIMED"

        session.execute(
            text(
                """
                UPDATE trading.trading_order
                SET resolver_claim_expires_at = NOW() - INTERVAL '1 second'
                WHERE order_id = :order_id
                """
            ),
            {"order_id": order_id},
        )
        session.commit()
        released = service.release_stale_claim(order_id)
        assert released["status"] == "RELEASED"
    finally:
        cleanup = factory()
        try:
            if order_id is not None:
                cleanup.execute(
                    text(
                        "DELETE FROM trading.trading_order "
                        "WHERE order_id = :id"
                    ),
                    {"id": order_id},
                )
                cleanup.commit()
        finally:
            cleanup.close()
        session.close()
