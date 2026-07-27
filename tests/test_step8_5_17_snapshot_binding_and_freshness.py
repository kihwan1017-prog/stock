"""STEP 8-5-17 — Broker Snapshot UBA Binding & Freshness tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from stock_platform.broker.account_dto import (
    BrokerAccountSyncResult,
)
from stock_platform.broker.account_repository import (
    BrokerAccountSnapshotRepository,
    BrokerSnapshotBindingError,
)
from stock_platform.broker.snapshot_constants import BrokerSnapshotStatus
from stock_platform.broker.snapshot_freshness import (
    compute_snapshot_hash,
    evaluate_snapshot_freshness,
)
from stock_platform.common.settings import get_settings
from stock_platform.settlement.adapters_live import KiwoomSettlementAdapter
from stock_platform.trading.account_masking import hash_account_ref
from tests.migration_helpers import (
    alembic_current_head,
    assert_revision_exists,
)

import stock_platform.auth.models  # noqa: F401
import stock_platform.broker.account_models  # noqa: F401
import stock_platform.trading.account_models  # noqa: F401


def test_step8_5_17_revision_head() -> None:
    assert_revision_exists("d7e8f9a0b1c2")
    assert_revision_exists("e8f9a0b1c2d3")
    # 후속 STEP이 head를 전진시켜도 본 revision은 체인에 유지
    head = alembic_current_head()
    assert head  # single head
    assert_revision_exists(head)


def test_compute_snapshot_hash_stable() -> None:
    now = datetime(2026, 7, 26, tzinfo=timezone.utc)
    a = compute_snapshot_hash(
        broker_code="kiwoom",
        account_number="1234",
        deposit_amount=Decimal("1"),
        available_order_amount=Decimal("2"),
        total_evaluation_amount=Decimal("3"),
        synchronized_at=now,
    )
    b = compute_snapshot_hash(
        broker_code="KIWOOM",
        account_number="1234",
        deposit_amount=Decimal("1"),
        available_order_amount=Decimal("2"),
        total_evaluation_amount=Decimal("3"),
        synchronized_at=now,
    )
    assert a == b
    assert len(a) == 64


def test_freshness_rejects_stale_and_orphan() -> None:
    now = datetime.now(timezone.utc)
    stale = SimpleNamespace(
        user_broker_account_id=1,
        broker_code="KIWOOM",
        snapshot_status=BrokerSnapshotStatus.ACTIVE.value,
        snapshot_generation=1,
        snapshot_hash="abc",
        snapshot_time=now - timedelta(hours=5),
        synchronized_at=now - timedelta(hours=5),
    )
    r = evaluate_snapshot_freshness(
        snapshot=stale,
        expected_uba_id=1,
        expected_broker_code="KIWOOM",
        max_age_seconds=3600,
        now=now,
    )
    assert r.ok is False
    assert r.reason == "STALE_BROKER_SNAPSHOT"

    orphan = SimpleNamespace(
        user_broker_account_id=1,
        broker_code="KIWOOM",
        snapshot_status=BrokerSnapshotStatus.ORPHAN.value,
        snapshot_generation=1,
        snapshot_hash="abc",
        snapshot_time=now,
        synchronized_at=now,
    )
    r2 = evaluate_snapshot_freshness(
        snapshot=orphan,
        expected_uba_id=1,
        expected_broker_code="KIWOOM",
        max_age_seconds=3600,
        now=now,
    )
    assert r2.ok is False
    assert "ORPHAN" in (r2.reason or "")


def test_freshness_rejects_wrong_uba() -> None:
    now = datetime.now(timezone.utc)
    snap = SimpleNamespace(
        user_broker_account_id=99,
        broker_code="KIWOOM",
        snapshot_status=BrokerSnapshotStatus.ACTIVE.value,
        snapshot_generation=2,
        snapshot_hash="x",
        snapshot_time=now,
        synchronized_at=now,
    )
    r = evaluate_snapshot_freshness(
        snapshot=snap,
        expected_uba_id=1,
        expected_broker_code="KIWOOM",
        max_age_seconds=3600,
        now=now,
    )
    assert r.ok is False
    assert r.reason == "SNAPSHOT_UBA_MISMATCH"


def test_save_requires_uba_binding() -> None:
    engine, Session = _db()
    session = Session()
    try:
        repo = BrokerAccountSnapshotRepository(session)
        result = _sync_result(account_number=f"ACC-{uuid4().hex[:8]}")
        with pytest.raises(BrokerSnapshotBindingError):
            repo.save(result)
    finally:
        session.close()
        engine.dispose()


def test_save_and_get_by_uba_roundtrip() -> None:
    engine, Session = _db()
    session = Session()
    acct = f"T817{uuid4().hex[:8]}"
    try:
        uba_id = _ensure_uba(session, broker="KIWOOM", account_number=acct)
        repo = BrokerAccountSnapshotRepository(session)
        entity = repo.save(
            _sync_result(account_number=acct, deposit=Decimal("5000")),
            user_broker_account_id=uba_id,
        )
        assert entity.user_broker_account_id == uba_id
        assert entity.snapshot_status == BrokerSnapshotStatus.ACTIVE.value
        assert entity.snapshot_hash
        assert int(entity.snapshot_generation) >= 1

        found, positions = repo.get_active_by_uba(uba_id)
        assert found is not None
        assert int(found.broker_account_snapshot_id) == int(
            entity.broker_account_snapshot_id
        )
        assert positions == []

        # Settlement adapter uses UBA only
        bundle = KiwoomSettlementAdapter(
            session, user_broker_account_id=uba_id
        ).fetch_bundle()
        assert bundle.sync_ok is True
        assert bundle.meta.get("uba_id") == uba_id
        assert "latest broker snapshot" not in str(
            bundle.meta.get("note") or ""
        ).lower()
    finally:
        _cleanup_uba(session, acct)
        session.close()
        engine.dispose()


def test_adapter_rejects_broker_only_heuristic() -> None:
    """UBA 없이 broker 최신 휴리스틱으로 조회하지 않는다."""

    engine, Session = _db()
    session = Session()
    try:
        bundle = KiwoomSettlementAdapter(
            session, user_broker_account_id=9_999_888_777
        ).fetch_bundle()
        assert bundle.sync_ok is False
        assert bundle.sync_error in {
            "UBA_NOT_FOUND",
            "BROKER_SNAPSHOT_MISSING",
            "SNAPSHOT_STATUS_ORPHAN",
        }
    finally:
        session.close()
        engine.dispose()


@pytest.mark.asyncio
async def test_settlement_handler_checks_snapshot_dependency() -> None:
    from unittest.mock import MagicMock

    from stock_platform.operation.market_session_job_constants import (
        MarketSessionJobResult,
        MarketSessionJobStatus,
    )
    from stock_platform.operation.market_session_job_entities import (
        MarketSessionJobEntity,
    )
    from stock_platform.operation.market_session_job_handlers import (
        KrxSettlementHandler,
    )

    handler = KrxSettlementHandler()
    dep = MarketSessionJobEntity(
        exchange_code="KRX",
        market_date=datetime.now(timezone.utc).date(),
        calendar_revision=1,
        job_type="KRX_EQUITY_SNAPSHOT",
        job_key="dep",
        scheduled_for=datetime.now(timezone.utc),
        status_code=MarketSessionJobStatus.RUNNING.value,
    )
    dep.market_session_job_id = 42
    job = MarketSessionJobEntity(
        exchange_code="KRX",
        market_date=datetime.now(timezone.utc).date(),
        calendar_revision=1,
        job_type="KRX_SETTLEMENT",
        job_key="settle",
        scheduled_for=datetime.now(timezone.utc),
        status_code=MarketSessionJobStatus.RUNNING.value,
        depends_on_job_id=42,
    )
    session = MagicMock()
    session.get.return_value = dep
    outcome = await handler.handle(session, job)
    assert outcome.result_code == MarketSessionJobResult.RETRY.value


# --- helpers ---


def _db():
    settings = get_settings()
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except OperationalError as exc:
        pytest.skip(f"database unavailable: {exc}")
    return engine, sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _sync_result(
    *,
    account_number: str,
    deposit: Decimal = Decimal("1000"),
):
    now = datetime.now(timezone.utc)
    return BrokerAccountSyncResult(
        broker_code="KIWOOM",
        account_number=account_number,
        deposit_amount=deposit,
        available_order_amount=deposit,
        total_purchase_amount=Decimal("0"),
        total_evaluation_amount=deposit,
        total_profit_loss=Decimal("0"),
        total_return_rate=Decimal("0"),
        positions=[],
        synchronized_at=now,
        raw_data={},
    )


def _ensure_uba(session, *, broker: str, account_number: str) -> int:
    from stock_platform.auth.models import AuthUser
    from stock_platform.trading.account_models import UserBrokerAccount

    username = f"snap17_{uuid4().hex[:10]}"
    user = AuthUser(
        username=username,
        password_hash="x",
        display_name=username,
        is_active=True,
    )
    session.add(user)
    session.flush()
    uba = UserBrokerAccount(
        user_id=int(user.user_id),
        broker_code=broker.upper(),
        account_alias=f"test-{account_number}",
        account_ref_hash=hash_account_ref(account_number),
        masked_account_number="****" + account_number[-4:],
        is_active=True,
    )
    session.add(uba)
    session.commit()
    return int(uba.user_broker_account_id)


def _cleanup_uba(session, account_number: str) -> None:
    digest = hash_account_ref(account_number)
    session.execute(
        text(
            """
            DELETE FROM trading.broker_position_snapshot
            WHERE user_broker_account_id IN (
              SELECT user_broker_account_id FROM trading.user_broker_account
              WHERE account_ref_hash = :h
            )
            """
        ),
        {"h": digest},
    )
    session.execute(
        text(
            """
            DELETE FROM trading.broker_account_snapshot
            WHERE user_broker_account_id IN (
              SELECT user_broker_account_id FROM trading.user_broker_account
              WHERE account_ref_hash = :h
            )
            """
        ),
        {"h": digest},
    )
    session.execute(
        text(
            "DELETE FROM trading.user_broker_account WHERE account_ref_hash = :h"
        ),
        {"h": digest},
    )
    session.execute(
        text(
            """
            DELETE FROM auth.user
            WHERE username LIKE 'snap17_%'
              AND user_id NOT IN (
                SELECT user_id FROM trading.user_broker_account
              )
            """
        )
    )
    session.commit()
