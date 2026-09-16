"""STEP 2-5-3 — Settlement/Ledger 계좌 FK 통합 테스트.

실제 PostgreSQL(로컬 dev DB)을 사용한다. 이 파일이 만든 행은
market_date/settlement_type 또는 reason 접두어(STEP253_TEST_)로 표시하고
finally에서 명시적으로 정리한다.

TradingOrder FK(STEP 2-5-2), UserBrokerAccount Soft Delete(STEP 2-5-1)는
이 파일 범위 밖이므로 다루지 않는다(각각 전용 테스트 파일 참고).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from stock_platform.database.session import get_session_factory

pytestmark = pytest.mark.integration

_PREFIX = "STEP253_TEST_"


@pytest.fixture()
def session():
    Session = get_session_factory()
    s = Session()
    try:
        yield s
    finally:
        s.rollback()
        s.execute(
            text(
                "DELETE FROM trading.account_daily_settlement "
                "WHERE settlement_type LIKE :p"
            ),
            {"p": f"{_PREFIX}%"},
        )
        s.execute(
            text(
                "DELETE FROM trading.ledger_adjustment WHERE reason LIKE :p"
            ),
            {"p": f"{_PREFIX}%"},
        )
        s.execute(
            text(
                "DELETE FROM trading.paper_account "
                "WHERE account_name LIKE :p"
            ),
            {"p": f"{_PREFIX}%"},
        )
        s.commit()
        s.close()


def _stype() -> str:
    return f"{_PREFIX}{uuid.uuid4().hex[:10]}"


# ---------------------------------------------------------------------------
# Migration / Constraint 상태
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "table,name,ref_table",
    [
        (
            "account_daily_settlement",
            "fk_account_daily_settlement_uba",
            "user_broker_account",
        ),
        (
            "account_daily_settlement",
            "fk_account_daily_settlement_paper_account",
            "paper_account",
        ),
        ("ledger_adjustment", "fk_ledger_adjustment_uba", "user_broker_account"),
        (
            "ledger_adjustment",
            "fk_ledger_adjustment_paper_account",
            "paper_account",
        ),
    ],
)
def test_fk_constraint_exists_validated_restrict(
    session, table, name, ref_table
) -> None:
    row = session.execute(
        text(
            """
            SELECT contype, convalidated, confrelid::regclass::text,
                   confdeltype
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            WHERE n.nspname = 'trading'
              AND t.relname = :table
              AND c.conname = :name
            """
        ),
        {"table": table, "name": name},
    ).fetchone()
    assert row is not None, f"{name} 제약이 존재해야 함"
    contype, convalidated, ref, confdeltype = row
    assert contype == "f"
    assert ref == ref_table
    assert confdeltype == "r"
    # STEP 2-5-3B: 로컬 dev DB 기준 orphan 0건이라 즉시 VALIDATE했음
    assert convalidated is True


def test_xor_check_constraints_unchanged(session) -> None:
    settlement_checks = session.execute(
        text(
            """
            SELECT COUNT(*) FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            WHERE n.nspname = 'trading' AND t.relname = 'account_daily_settlement'
              AND c.contype = 'c'
            """
        )
    ).scalar()
    ledger_checks = session.execute(
        text(
            """
            SELECT COUNT(*) FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            WHERE n.nspname = 'trading' AND t.relname = 'ledger_adjustment'
              AND c.contype = 'c'
            """
        )
    ).scalar()
    # STEP 2-5-3 이전과 동일한 개수(3개/1개) — FK 추가로 CHECK가
    # 사라지거나 늘지 않았어야 함
    assert settlement_checks == 3
    assert ledger_checks == 1


# ---------------------------------------------------------------------------
# AccountDailySettlement 무결성
# ---------------------------------------------------------------------------


def test_settlement_valid_uba_insert_succeeds(session) -> None:
    uba_id = session.execute(
        text("SELECT user_broker_account_id FROM trading.user_broker_account LIMIT 1")
    ).scalar()
    assert uba_id is not None
    session.execute(
        text(
            """
            INSERT INTO trading.account_daily_settlement
            (user_broker_account_id, paper_account_id, broker_code,
             market_date, settlement_type, status_code)
            VALUES (:uba, NULL, 'UPBIT', '2026-07-28', :stype, 'PENDING')
            """
        ),
        {"uba": uba_id, "stype": _stype()},
    )
    session.commit()


def test_settlement_invalid_uba_insert_blocked(session) -> None:
    with pytest.raises(IntegrityError):
        session.execute(
            text(
                """
                INSERT INTO trading.account_daily_settlement
                (user_broker_account_id, paper_account_id, broker_code,
                 market_date, settlement_type, status_code)
                VALUES (999999999, NULL, 'UPBIT', '2026-07-28', :stype, 'PENDING')
                """
            ),
            {"stype": _stype()},
        )
        session.commit()
    session.rollback()


def test_settlement_valid_paper_insert_succeeds(session) -> None:
    paper_id = session.execute(
        text("SELECT account_id FROM trading.paper_account LIMIT 1")
    ).scalar()
    assert paper_id is not None
    session.execute(
        text(
            """
            INSERT INTO trading.account_daily_settlement
            (user_broker_account_id, paper_account_id, broker_code,
             market_date, settlement_type, status_code)
            VALUES (NULL, :pid, 'PAPER', '2026-07-28', :stype, 'PENDING')
            """
        ),
        {"pid": paper_id, "stype": _stype()},
    )
    session.commit()


def test_settlement_invalid_paper_insert_blocked(session) -> None:
    with pytest.raises(IntegrityError):
        session.execute(
            text(
                """
                INSERT INTO trading.account_daily_settlement
                (user_broker_account_id, paper_account_id, broker_code,
                 market_date, settlement_type, status_code)
                VALUES (NULL, 999999999, 'PAPER', '2026-07-28', :stype, 'PENDING')
                """
            ),
            {"stype": _stype()},
        )
        session.commit()
    session.rollback()


def test_settlement_xor_both_null_blocked(session) -> None:
    with pytest.raises(IntegrityError):
        session.execute(
            text(
                """
                INSERT INTO trading.account_daily_settlement
                (user_broker_account_id, paper_account_id, broker_code,
                 market_date, settlement_type, status_code)
                VALUES (NULL, NULL, 'PAPER', '2026-07-28', :stype, 'PENDING')
                """
            ),
            {"stype": _stype()},
        )
        session.commit()
    session.rollback()


def test_settlement_xor_both_set_blocked(session) -> None:
    uba_id = session.execute(
        text("SELECT user_broker_account_id FROM trading.user_broker_account LIMIT 1")
    ).scalar()
    paper_id = session.execute(
        text("SELECT account_id FROM trading.paper_account LIMIT 1")
    ).scalar()
    with pytest.raises(IntegrityError):
        session.execute(
            text(
                """
                INSERT INTO trading.account_daily_settlement
                (user_broker_account_id, paper_account_id, broker_code,
                 market_date, settlement_type, status_code)
                VALUES (:uba, :pid, 'PAPER', '2026-07-28', :stype, 'PENDING')
                """
            ),
            {"uba": uba_id, "pid": paper_id, "stype": _stype()},
        )
        session.commit()
    session.rollback()


def test_settlement_restrict_blocks_paper_account_delete(session) -> None:
    new_id = session.execute(
        text(
            """
            INSERT INTO trading.paper_account
            (account_name, currency_code, initial_cash, available_cash,
             realized_profit_loss, is_default, is_active)
            VALUES (:name, 'KRW', 1000, 1000, 0, false, true)
            RETURNING account_id
            """
        ),
        {"name": f"{_PREFIX}restrict"},
    ).scalar_one()
    session.commit()

    session.execute(
        text(
            """
            INSERT INTO trading.account_daily_settlement
            (user_broker_account_id, paper_account_id, broker_code,
             market_date, settlement_type, status_code)
            VALUES (NULL, :pid, 'PAPER', '2026-07-29', :stype, 'PENDING')
            """
        ),
        {"pid": new_id, "stype": _stype()},
    )
    session.commit()

    with pytest.raises(IntegrityError):
        session.execute(
            text("DELETE FROM trading.paper_account WHERE account_id=:aid"),
            {"aid": new_id},
        )
        session.commit()
    session.rollback()


def test_soft_deleted_account_settlement_history_still_queryable(
    session,
) -> None:
    """과거에 생성된 정산이 삭제된 계좌를 계속 참조할 수 있어야 함
    (요구사항: 이미 생성된 과거 정산은 삭제 계좌를 계속 참조 가능)."""
    new_id = session.execute(
        text(
            """
            INSERT INTO trading.paper_account
            (account_name, currency_code, initial_cash, available_cash,
             realized_profit_loss, is_default, is_active)
            VALUES (:name, 'KRW', 1000, 1000, 0, false, true)
            RETURNING account_id
            """
        ),
        {"name": f"{_PREFIX}softref"},
    ).scalar_one()
    session.execute(
        text(
            """
            INSERT INTO trading.account_daily_settlement
            (user_broker_account_id, paper_account_id, broker_code,
             market_date, settlement_type, status_code)
            VALUES (NULL, :pid, 'PAPER', '2026-07-29', :stype, 'PENDING')
            """
        ),
        {"pid": new_id, "stype": _stype()},
    )
    session.commit()

    # Soft delete the paper account (mirrors production soft-delete flow)
    session.execute(
        text(
            "UPDATE trading.paper_account SET deleted_at = now(), "
            "is_active = false WHERE account_id = :aid"
        ),
        {"aid": new_id},
    )
    session.commit()

    row = session.execute(
        text(
            "SELECT paper_account_id FROM trading.account_daily_settlement "
            "WHERE paper_account_id = :aid"
        ),
        {"aid": new_id},
    ).fetchone()
    assert row is not None, "삭제된 계좌를 참조하는 과거 정산 기록이 조회되어야 함"


# ---------------------------------------------------------------------------
# LedgerAdjustment 무결성
# ---------------------------------------------------------------------------


def test_ledger_valid_uba_insert_succeeds(session) -> None:
    uba_id = session.execute(
        text("SELECT user_broker_account_id FROM trading.user_broker_account LIMIT 1")
    ).scalar()
    session.execute(
        text(
            """
            INSERT INTO trading.ledger_adjustment
            (user_broker_account_id, paper_account_id, asset_code,
             adjustment_type, reason, requested_by, status_code)
            VALUES (:uba, NULL, 'KRW', 'MANUAL', :reason, 'tester', 'REQUESTED')
            """
        ),
        {"uba": uba_id, "reason": f"{_PREFIX}uba"},
    )
    session.commit()


def test_ledger_invalid_uba_insert_blocked(session) -> None:
    with pytest.raises(IntegrityError):
        session.execute(
            text(
                """
                INSERT INTO trading.ledger_adjustment
                (user_broker_account_id, paper_account_id, asset_code,
                 adjustment_type, reason, requested_by, status_code)
                VALUES (999999999, NULL, 'KRW', 'MANUAL', :reason, 'tester', 'REQUESTED')
                """
            ),
            {"reason": f"{_PREFIX}baduba"},
        )
        session.commit()
    session.rollback()


def test_ledger_valid_paper_insert_succeeds(session) -> None:
    paper_id = session.execute(
        text("SELECT account_id FROM trading.paper_account LIMIT 1")
    ).scalar()
    session.execute(
        text(
            """
            INSERT INTO trading.ledger_adjustment
            (user_broker_account_id, paper_account_id, asset_code,
             adjustment_type, reason, requested_by, status_code)
            VALUES (NULL, :pid, 'KRW', 'MANUAL', :reason, 'tester', 'REQUESTED')
            """
        ),
        {"pid": paper_id, "reason": f"{_PREFIX}paper"},
    )
    session.commit()


def test_ledger_invalid_paper_insert_blocked(session) -> None:
    with pytest.raises(IntegrityError):
        session.execute(
            text(
                """
                INSERT INTO trading.ledger_adjustment
                (user_broker_account_id, paper_account_id, asset_code,
                 adjustment_type, reason, requested_by, status_code)
                VALUES (NULL, 999999999, 'KRW', 'MANUAL', :reason, 'tester', 'REQUESTED')
                """
            ),
            {"reason": f"{_PREFIX}badpaper"},
        )
        session.commit()
    session.rollback()


def test_ledger_xor_violation_blocked(session) -> None:
    with pytest.raises(IntegrityError):
        session.execute(
            text(
                """
                INSERT INTO trading.ledger_adjustment
                (user_broker_account_id, paper_account_id, asset_code,
                 adjustment_type, reason, requested_by, status_code)
                VALUES (NULL, NULL, 'KRW', 'MANUAL', :reason, 'tester', 'REQUESTED')
                """
            ),
            {"reason": f"{_PREFIX}xor"},
        )
        session.commit()
    session.rollback()


def test_ledger_status_code_cancel_reject_structure_unchanged() -> None:
    """LedgerAdjustment는 물리 삭제가 아니라 status_code로 취소/거부를
    표현하는 기존 구조를 유지해야 함(엔티티 필드 확인)."""
    from stock_platform.settlement.entities import LedgerAdjustmentEntity

    columns = {c.name for c in LedgerAdjustmentEntity.__table__.columns}
    assert "status_code" in columns
    assert "resolved" not in columns  # 이 필드는 별도 엔티티에 속함


# ---------------------------------------------------------------------------
# 운영 경로(코드 레벨 확인 — STEP 2-5-1에서 이미 patch된 is_active 필터 포함)
# ---------------------------------------------------------------------------


def test_runner_excludes_soft_deleted_paper_accounts_by_source() -> None:
    import inspect

    from stock_platform.settlement import runner as runner_module

    source = inspect.getsource(runner_module.run_krx_eod_settlement)
    assert "deleted_at" in source


def test_runner_excludes_inactive_uba_by_source() -> None:
    import inspect

    from stock_platform.settlement import runner as runner_module

    source = inspect.getsource(runner_module)
    assert "is_active.is_(True)" in source


def test_admin_run_paper_settlement_validates_existence_by_source() -> None:
    import inspect

    from stock_platform.api.v1 import admin_settlements as mod

    source = inspect.getsource(mod.run_paper_settlement)
    assert "PaperAccount" in source
    assert "404" in source
