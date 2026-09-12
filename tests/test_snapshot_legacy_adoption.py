"""SHARED legacy snapshot adoption — RETIRED unbound + position replace."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from stock_platform.broker.account_dto import (
    BrokerAccountSyncResult,
    BrokerPositionSnapshot,
)
from stock_platform.broker.account_models import (
    BrokerAccountSnapshotEntity,
    BrokerPositionSnapshotEntity,
)
from stock_platform.broker.account_repository import (
    BrokerAccountSnapshotRepository,
)
from stock_platform.broker.kiwoom.account_identity import (
    build_kiwoom_legacy_adoption_proof,
    matches_kiwoom_account_identity,
)
from stock_platform.broker.snapshot_constants import BrokerSnapshotStatus
from stock_platform.broker.snapshot_legacy_adoption import (
    LegacySnapshotAdoptionRejected,
    SnapshotLegacyAdoptionProof,
)
from stock_platform.common.settings import get_settings
from stock_platform.trading.account_masking import hash_account_ref

import stock_platform.auth.models  # noqa: F401
import stock_platform.broker.account_models  # noqa: F401
import stock_platform.trading.account_models  # noqa: F401


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
    broker: str = "KIWOOM",
    account_number: str,
    deposit: Decimal = Decimal("1000"),
    positions: list[BrokerPositionSnapshot] | None = None,
):
    now = datetime.now(timezone.utc)
    return BrokerAccountSyncResult(
        broker_code=broker,
        account_number=account_number,
        deposit_amount=deposit,
        available_order_amount=deposit,
        total_purchase_amount=Decimal("0"),
        total_evaluation_amount=deposit,
        total_profit_loss=Decimal("0"),
        total_return_rate=Decimal("0"),
        positions=list(positions or []),
        synchronized_at=now,
        raw_data={"source": "test"},
    )


def _pos(symbol: str, account_number: str) -> BrokerPositionSnapshot:
    return BrokerPositionSnapshot(
        exchange_code="KRX",
        symbol=symbol,
        name=symbol,
        quantity=Decimal("1"),
        available_quantity=Decimal("1"),
        average_purchase_price=Decimal("10"),
        current_price=Decimal("11"),
        purchase_amount=Decimal("10"),
        evaluation_amount=Decimal("11"),
        profit_loss=Decimal("1"),
        return_rate=Decimal("0.1"),
        raw_data={},
    )


def _ensure_uba(session, *, broker: str, account_number: str) -> int:
    from stock_platform.auth.models import AuthUser
    from stock_platform.trading.account_models import UserBrokerAccount

    username = f"legadopt_{uuid4().hex[:10]}"
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


def _cleanup_by_acct(session, account_numbers: list[str]) -> None:
    for acct in account_numbers:
        session.execute(
            text(
                "DELETE FROM trading.broker_position_snapshot "
                "WHERE account_number = :a"
            ),
            {"a": acct},
        )
        session.execute(
            text(
                "DELETE FROM trading.broker_account_snapshot "
                "WHERE account_number = :a"
            ),
            {"a": acct},
        )
    session.commit()


def _exact_proof(uba_id: int, broker: str, *accts: str) -> SnapshotLegacyAdoptionProof:
    allowed = {a for a in accts if a}

    def matcher(candidate: str) -> bool:
        return candidate in allowed

    return SnapshotLegacyAdoptionProof(
        target_uba_id=uba_id,
        broker_code=broker,
        account_matcher=matcher,
    )


def test_matches_kiwoom_account_identity_8_vs_10() -> None:
    assert matches_kiwoom_account_identity("57804145", "5780414511")
    assert matches_kiwoom_account_identity("5780414511", "57804145")
    assert not matches_kiwoom_account_identity("57804145", "57804146")


def test_a_active_same_uba_updates() -> None:
    engine, Session = _db()
    session = Session()
    base = f"9{uuid4().hex[:7]}"
    try:
        uba = _ensure_uba(session, broker="KIWOOM", account_number=base)
        repo = BrokerAccountSnapshotRepository(session)
        first = repo.save(
            _sync_result(account_number=base, deposit=Decimal("1")),
            user_broker_account_id=uba,
        )
        pk = int(first.broker_account_snapshot_id)
        second = repo.save(
            _sync_result(account_number=base, deposit=Decimal("2")),
            user_broker_account_id=uba,
        )
        assert int(second.broker_account_snapshot_id) == pk
        assert second.deposit_amount == Decimal("2")
        assert second.snapshot_status == BrokerSnapshotStatus.ACTIVE.value
    finally:
        _cleanup_by_acct(session, [base])
        session.close()
        engine.dispose()


def test_b_retired_same_uba_reactivates() -> None:
    engine, Session = _db()
    session = Session()
    base = f"8{uuid4().hex[:7]}"
    try:
        uba = _ensure_uba(session, broker="KIWOOM", account_number=base)
        repo = BrokerAccountSnapshotRepository(session)
        row = repo.save(
            _sync_result(account_number=base),
            user_broker_account_id=uba,
        )
        pk = int(row.broker_account_snapshot_id)
        row.snapshot_status = BrokerSnapshotStatus.RETIRED.value
        row.raw_data = {"_retire": {"reason": "test"}}
        session.commit()

        again = repo.save(
            _sync_result(account_number=base, deposit=Decimal("9")),
            user_broker_account_id=uba,
        )
        assert int(again.broker_account_snapshot_id) == pk
        assert again.snapshot_status == BrokerSnapshotStatus.ACTIVE.value
        assert again.user_broker_account_id == uba
        assert (again.raw_data or {}).get("_retire", {}).get("reason") == "test"
        assert "_adopt" in (again.raw_data or {})
    finally:
        _cleanup_by_acct(session, [base])
        session.close()
        engine.dispose()


def test_c_retired_null_proven_adopts() -> None:
    engine, Session = _db()
    session = Session()
    vault8 = f"7{uuid4().hex[:7]}"
    broker10 = vault8 + "11"
    try:
        uba = _ensure_uba(session, broker="KIWOOM", account_number=vault8)
        # legacy unbound RETIRED (no UBA)
        legacy = BrokerAccountSnapshotEntity(
            broker_code="KIWOOM",
            account_number=broker10,
            user_broker_account_id=None,
            paper_account_id=None,
            snapshot_status=BrokerSnapshotStatus.RETIRED.value,
            snapshot_generation=1,
            snapshot_version=1,
            deposit_amount=Decimal("0"),
            available_order_amount=Decimal("0"),
            total_purchase_amount=Decimal("0"),
            total_evaluation_amount=Decimal("0"),
            total_profit_loss=Decimal("0"),
            total_return_rate=Decimal("0"),
            raw_data={"_retire": {"actor": "SYSTEM", "reason": "ORPHAN"}},
            synchronized_at=datetime.now(timezone.utc),
        )
        session.add(legacy)
        session.commit()
        legacy_id = int(legacy.broker_account_snapshot_id)

        proof = build_kiwoom_legacy_adoption_proof(
            target_uba_id=uba,
            broker_account_number=broker10,
            vault_account_number=vault8,
        )
        repo = BrokerAccountSnapshotRepository(session)
        entity = repo.save(
            _sync_result(account_number=broker10, deposit=Decimal("55")),
            user_broker_account_id=uba,
            legacy_adoption=proof,
        )
        assert int(entity.broker_account_snapshot_id) == legacy_id
        assert entity.user_broker_account_id == uba
        assert entity.snapshot_status == BrokerSnapshotStatus.ACTIVE.value
        assert entity.deposit_amount == Decimal("55")
        assert (entity.raw_data or {}).get("_retire")
        assert (entity.raw_data or {}).get("_adopt", {}).get("target_uba_id") == uba
    finally:
        _cleanup_by_acct(session, [vault8, broker10])
        session.close()
        engine.dispose()


def test_d_retired_null_ambiguous_rejects() -> None:
    engine, Session = _db()
    session = Session()
    vault8 = f"6{uuid4().hex[:7]}"
    try:
        uba = _ensure_uba(session, broker="KIWOOM", account_number=vault8)
        # matcher that matches everything → ambiguous if 2 rows
        a1 = vault8 + "11"
        a2 = vault8 + "22"
        for acct in (a1, a2):
            session.add(
                BrokerAccountSnapshotEntity(
                    broker_code="KIWOOM",
                    account_number=acct,
                    snapshot_status=BrokerSnapshotStatus.RETIRED.value,
                    snapshot_generation=1,
                    snapshot_version=1,
                    deposit_amount=Decimal("0"),
                    available_order_amount=Decimal("0"),
                    total_purchase_amount=Decimal("0"),
                    total_evaluation_amount=Decimal("0"),
                    total_profit_loss=Decimal("0"),
                    total_return_rate=Decimal("0"),
                    raw_data={},
                    synchronized_at=datetime.now(timezone.utc),
                )
            )
        session.commit()
        proof = SnapshotLegacyAdoptionProof(
            target_uba_id=uba,
            broker_code="KIWOOM",
            account_matcher=lambda _c: True,
        )
        repo = BrokerAccountSnapshotRepository(session)
        with pytest.raises(LegacySnapshotAdoptionRejected):
            repo.save(
                _sync_result(account_number=a1),
                user_broker_account_id=uba,
                legacy_adoption=proof,
            )
    finally:
        _cleanup_by_acct(session, [vault8, vault8 + "11", vault8 + "22"])
        session.close()
        engine.dispose()


def test_e_active_different_uba_rejects() -> None:
    engine, Session = _db()
    session = Session()
    acct = f"5{uuid4().hex[:7]}"
    try:
        uba1 = _ensure_uba(session, broker="KIWOOM", account_number=acct + "a")
        uba2 = _ensure_uba(session, broker="KIWOOM", account_number=acct + "b")
        repo = BrokerAccountSnapshotRepository(session)
        repo.save(
            _sync_result(account_number=acct),
            user_broker_account_id=uba1,
        )
        # unbound RETIRED also present? Use proof matching acct while ACTIVE other uba
        session.add(
            BrokerAccountSnapshotEntity(
                broker_code="KIWOOM",
                account_number=acct + "X",
                snapshot_status=BrokerSnapshotStatus.RETIRED.value,
                snapshot_generation=1,
                snapshot_version=1,
                deposit_amount=Decimal("0"),
                available_order_amount=Decimal("0"),
                total_purchase_amount=Decimal("0"),
                total_evaluation_amount=Decimal("0"),
                total_profit_loss=Decimal("0"),
                total_return_rate=Decimal("0"),
                raw_data={},
                synchronized_at=datetime.now(timezone.utc),
            )
        )
        session.commit()
        proof = _exact_proof(uba2, "KIWOOM", acct, acct + "X")
        with pytest.raises(LegacySnapshotAdoptionRejected):
            repo.save(
                _sync_result(account_number=acct),
                user_broker_account_id=uba2,
                legacy_adoption=proof,
            )
    finally:
        _cleanup_by_acct(session, [acct, acct + "X"])
        session.close()
        engine.dispose()


def test_f_retired_different_uba_rejects() -> None:
    engine, Session = _db()
    session = Session()
    acct = f"4{uuid4().hex[:7]}"
    try:
        uba1 = _ensure_uba(session, broker="KIWOOM", account_number=acct + "1")
        uba2 = _ensure_uba(session, broker="KIWOOM", account_number=acct + "2")
        session.add(
            BrokerAccountSnapshotEntity(
                broker_code="KIWOOM",
                account_number=acct,
                user_broker_account_id=uba1,
                snapshot_status=BrokerSnapshotStatus.RETIRED.value,
                snapshot_generation=1,
                snapshot_version=1,
                deposit_amount=Decimal("0"),
                available_order_amount=Decimal("0"),
                total_purchase_amount=Decimal("0"),
                total_evaluation_amount=Decimal("0"),
                total_profit_loss=Decimal("0"),
                total_return_rate=Decimal("0"),
                raw_data={},
                synchronized_at=datetime.now(timezone.utc),
            )
        )
        # also need unbound candidate so adopt path runs
        session.add(
            BrokerAccountSnapshotEntity(
                broker_code="KIWOOM",
                account_number=acct + "0",
                snapshot_status=BrokerSnapshotStatus.RETIRED.value,
                snapshot_generation=1,
                snapshot_version=1,
                deposit_amount=Decimal("0"),
                available_order_amount=Decimal("0"),
                total_purchase_amount=Decimal("0"),
                total_evaluation_amount=Decimal("0"),
                total_profit_loss=Decimal("0"),
                total_return_rate=Decimal("0"),
                raw_data={},
                synchronized_at=datetime.now(timezone.utc),
            )
        )
        session.commit()
        proof = _exact_proof(uba2, "KIWOOM", acct, acct + "0")
        repo = BrokerAccountSnapshotRepository(session)
        with pytest.raises(LegacySnapshotAdoptionRejected):
            repo.save(
                _sync_result(account_number=acct),
                user_broker_account_id=uba2,
                legacy_adoption=proof,
            )
    finally:
        _cleanup_by_acct(session, [acct, acct + "0"])
        session.close()
        engine.dispose()


def test_g_no_row_inserts() -> None:
    engine, Session = _db()
    session = Session()
    acct = f"3{uuid4().hex[:7]}"
    try:
        uba = _ensure_uba(session, broker="KIWOOM", account_number=acct)
        repo = BrokerAccountSnapshotRepository(session)
        entity = repo.save(
            _sync_result(account_number=acct),
            user_broker_account_id=uba,
        )
        assert entity.broker_account_snapshot_id
        assert entity.snapshot_status == BrokerSnapshotStatus.ACTIVE.value
    finally:
        _cleanup_by_acct(session, [acct])
        session.close()
        engine.dispose()


def test_h_repeated_adoption_idempotent() -> None:
    engine, Session = _db()
    session = Session()
    vault8 = f"2{uuid4().hex[:7]}"
    broker10 = vault8 + "11"
    try:
        uba = _ensure_uba(session, broker="KIWOOM", account_number=vault8)
        session.add(
            BrokerAccountSnapshotEntity(
                broker_code="KIWOOM",
                account_number=broker10,
                snapshot_status=BrokerSnapshotStatus.RETIRED.value,
                snapshot_generation=1,
                snapshot_version=1,
                deposit_amount=Decimal("0"),
                available_order_amount=Decimal("0"),
                total_purchase_amount=Decimal("0"),
                total_evaluation_amount=Decimal("0"),
                total_profit_loss=Decimal("0"),
                total_return_rate=Decimal("0"),
                raw_data={"_retire": {"reason": "x"}},
                synchronized_at=datetime.now(timezone.utc),
            )
        )
        session.commit()
        proof = build_kiwoom_legacy_adoption_proof(
            target_uba_id=uba,
            broker_account_number=broker10,
            vault_account_number=vault8,
        )
        repo = BrokerAccountSnapshotRepository(session)
        a = repo.save(
            _sync_result(account_number=broker10, deposit=Decimal("1")),
            user_broker_account_id=uba,
            legacy_adoption=proof,
        )
        b = repo.save(
            _sync_result(account_number=broker10, deposit=Decimal("2")),
            user_broker_account_id=uba,
            legacy_adoption=proof,
        )
        assert int(a.broker_account_snapshot_id) == int(
            b.broker_account_snapshot_id
        )
        assert b.deposit_amount == Decimal("2")
    finally:
        _cleanup_by_acct(session, [vault8, broker10])
        session.close()
        engine.dispose()


def test_i_j_legacy_unique_and_12_positions() -> None:
    """I+J: RETIRED account + 12 RETIRED positions → adopt without IntegrityError."""

    engine, Session = _db()
    session = Session()
    vault8 = f"1{uuid4().hex[:7]}"
    broker10 = vault8 + "11"
    try:
        uba = _ensure_uba(session, broker="KIWOOM", account_number=vault8)
        session.add(
            BrokerAccountSnapshotEntity(
                broker_code="KIWOOM",
                account_number=broker10,
                snapshot_status=BrokerSnapshotStatus.RETIRED.value,
                snapshot_generation=1,
                snapshot_version=1,
                deposit_amount=Decimal("0"),
                available_order_amount=Decimal("0"),
                total_purchase_amount=Decimal("0"),
                total_evaluation_amount=Decimal("0"),
                total_profit_loss=Decimal("0"),
                total_return_rate=Decimal("0"),
                raw_data={"_retire": {"reason": "ORPHAN"}},
                synchronized_at=datetime.now(timezone.utc),
            )
        )
        now = datetime.now(timezone.utc)
        for i in range(12):
            session.add(
                BrokerPositionSnapshotEntity(
                    broker_code="KIWOOM",
                    account_number=broker10,
                    user_broker_account_id=None,
                    snapshot_status=BrokerSnapshotStatus.RETIRED.value,
                    exchange_code="KRX",
                    symbol=f"S{i:04d}",
                    name=f"S{i:04d}",
                    quantity=Decimal("1"),
                    available_quantity=Decimal("1"),
                    average_purchase_price=Decimal("1"),
                    current_price=Decimal("1"),
                    purchase_amount=Decimal("1"),
                    evaluation_amount=Decimal("1"),
                    profit_loss=Decimal("0"),
                    return_rate=Decimal("0"),
                    raw_data={},
                    synchronized_at=now,
                )
            )
        session.commit()

        proof = build_kiwoom_legacy_adoption_proof(
            target_uba_id=uba,
            broker_account_number=broker10,
            vault_account_number=vault8,
        )
        positions = [_pos(f"S{i:04d}", broker10) for i in range(12)]
        repo = BrokerAccountSnapshotRepository(session)
        entity = repo.save(
            _sync_result(account_number=broker10, positions=positions),
            user_broker_account_id=uba,
            legacy_adoption=proof,
        )
        assert entity.snapshot_status == BrokerSnapshotStatus.ACTIVE.value
        assert entity.user_broker_account_id == uba
        rows = list(
            session.scalars(
                select(BrokerPositionSnapshotEntity).where(
                    BrokerPositionSnapshotEntity.user_broker_account_id
                    == uba,
                    BrokerPositionSnapshotEntity.snapshot_status
                    == BrokerSnapshotStatus.ACTIVE.value,
                )
            )
        )
        assert len(rows) == 12
        leftover = session.scalar(
            select(BrokerPositionSnapshotEntity).where(
                BrokerPositionSnapshotEntity.account_number == broker10,
                BrokerPositionSnapshotEntity.snapshot_status
                == BrokerSnapshotStatus.RETIRED.value,
            )
        )
        assert leftover is None
    finally:
        _cleanup_by_acct(session, [vault8, broker10])
        session.close()
        engine.dispose()


def test_k_other_uba_positions_untouched() -> None:
    engine, Session = _db()
    session = Session()
    acct_a = f"A{uuid4().hex[:7]}"
    acct_b = f"B{uuid4().hex[:7]}"
    try:
        uba_a = _ensure_uba(session, broker="KIWOOM", account_number=acct_a)
        uba_b = _ensure_uba(session, broker="KIWOOM", account_number=acct_b)
        repo = BrokerAccountSnapshotRepository(session)
        repo.save(
            _sync_result(
                account_number=acct_b,
                positions=[_pos("KEEP", acct_b)],
            ),
            user_broker_account_id=uba_b,
        )
        before = session.scalar(
            select(BrokerPositionSnapshotEntity).where(
                BrokerPositionSnapshotEntity.user_broker_account_id
                == uba_b
            )
        )
        assert before is not None
        keep_id = int(before.broker_position_snapshot_id)

        # uba_a save with proof only for acct_a
        session.add(
            BrokerAccountSnapshotEntity(
                broker_code="KIWOOM",
                account_number=acct_a + "11",
                snapshot_status=BrokerSnapshotStatus.RETIRED.value,
                snapshot_generation=1,
                snapshot_version=1,
                deposit_amount=Decimal("0"),
                available_order_amount=Decimal("0"),
                total_purchase_amount=Decimal("0"),
                total_evaluation_amount=Decimal("0"),
                total_profit_loss=Decimal("0"),
                total_return_rate=Decimal("0"),
                raw_data={},
                synchronized_at=datetime.now(timezone.utc),
            )
        )
        session.commit()
        proof = build_kiwoom_legacy_adoption_proof(
            target_uba_id=uba_a,
            broker_account_number=acct_a + "11",
            vault_account_number=acct_a,
        )
        repo.save(
            _sync_result(account_number=acct_a + "11"),
            user_broker_account_id=uba_a,
            legacy_adoption=proof,
        )
        still = session.get(BrokerPositionSnapshotEntity, keep_id)
        assert still is not None
        assert int(still.user_broker_account_id) == uba_b
    finally:
        _cleanup_by_acct(session, [acct_a, acct_b, acct_a + "11"])
        session.close()
        engine.dispose()


def test_l_paper_path_unaffected_by_proof() -> None:
    """Paper save는 legacy_adoption 없이 account_number replace 계약 유지."""

    engine, Session = _db()
    session = Session()
    acct = f"P{uuid4().hex[:7]}"
    paper_id: int | None = None
    try:
        from stock_platform.auth.models import AuthUser
        from stock_platform.trading.account_models import PaperAccount

        user = AuthUser(
            username=f"paper_{uuid4().hex[:8]}",
            password_hash="x",
            display_name="p",
            is_active=True,
        )
        session.add(user)
        session.flush()
        paper = PaperAccount(
            user_id=int(user.user_id),
            account_name=f"paper-{acct}",
            currency_code="KRW",
            is_active=True,
        )
        session.add(paper)
        session.commit()
        paper_id = int(paper.account_id)
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        pytest.skip(f"paper fixture unavailable: {exc}")

    try:
        repo = BrokerAccountSnapshotRepository(session)
        entity = repo.save(
            _sync_result(account_number=acct),
            paper_account_id=paper_id,
        )
        assert entity.paper_account_id == paper_id
        assert entity.user_broker_account_id is None
    finally:
        _cleanup_by_acct(session, [acct])
        if paper_id is not None:
            session.execute(
                text(
                    "DELETE FROM trading.paper_account WHERE account_id=:id"
                ),
                {"id": paper_id},
            )
            session.commit()
        session.close()
        engine.dispose()


def test_m_n_upbit_no_auto_adopt_without_proof() -> None:
    engine, Session = _db()
    session = Session()
    legacy_acct = f"LEG{uuid4().hex[:6]}"
    uba_acct = None
    try:
        uba = _ensure_uba(session, broker="UPBIT", account_number="UPBITMAIN")
        uba_acct = f"UBA:{uba}"
        # unique legacy RETIRED unbound — proof 없이 자동 adopt 금지
        session.add(
            BrokerAccountSnapshotEntity(
                broker_code="UPBIT",
                account_number=legacy_acct,
                snapshot_status=BrokerSnapshotStatus.RETIRED.value,
                snapshot_generation=1,
                snapshot_version=1,
                deposit_amount=Decimal("0"),
                available_order_amount=Decimal("0"),
                total_purchase_amount=Decimal("0"),
                total_evaluation_amount=Decimal("0"),
                total_profit_loss=Decimal("0"),
                total_return_rate=Decimal("0"),
                raw_data={"_retire": {"reason": "legacy"}},
                synchronized_at=datetime.now(timezone.utc),
            )
        )
        session.commit()
        repo = BrokerAccountSnapshotRepository(session)
        # without proof: insert UBA:id — normal path
        entity = repo.save(
            _sync_result(broker="UPBIT", account_number=uba_acct),
            user_broker_account_id=uba,
        )
        assert entity.account_number == uba_acct
        assert entity.snapshot_status == BrokerSnapshotStatus.ACTIVE.value
        # legacy still RETIRED unbound
        main = session.scalar(
            select(BrokerAccountSnapshotEntity).where(
                BrokerAccountSnapshotEntity.broker_code == "UPBIT",
                BrokerAccountSnapshotEntity.account_number == legacy_acct,
            )
        )
        assert main is not None
        assert main.snapshot_status == BrokerSnapshotStatus.RETIRED.value
        assert main.user_broker_account_id is None

        entity2 = repo.save(
            _sync_result(
                broker="UPBIT",
                account_number=uba_acct,
                deposit=Decimal("3"),
            ),
            user_broker_account_id=uba,
        )
        assert int(entity2.broker_account_snapshot_id) == int(
            entity.broker_account_snapshot_id
        )
    finally:
        accts = [legacy_acct]
        if uba_acct:
            accts.append(uba_acct)
        _cleanup_by_acct(session, accts)
        session.close()
        engine.dispose()


def test_o_p_trading_order_outbox_unchanged_counters() -> None:
    engine, Session = _db()
    session = Session()
    before_to = session.execute(
        text("SELECT COUNT(*) FROM trading.trading_order")
    ).scalar()
    before_ob = session.execute(
        text("SELECT COUNT(*) FROM trading.order_outbox")
    ).scalar()
    acct = f"0{uuid4().hex[:7]}"
    try:
        uba = _ensure_uba(session, broker="KIWOOM", account_number=acct)
        BrokerAccountSnapshotRepository(session).save(
            _sync_result(account_number=acct),
            user_broker_account_id=uba,
        )
        after_to = session.execute(
            text("SELECT COUNT(*) FROM trading.trading_order")
        ).scalar()
        after_ob = session.execute(
            text("SELECT COUNT(*) FROM trading.order_outbox")
        ).scalar()
        assert after_to == before_to
        assert after_ob == before_ob
    finally:
        _cleanup_by_acct(session, [acct])
        session.close()
        engine.dispose()
