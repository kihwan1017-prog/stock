"""STEP 2-5-2 — trading.trading_order.account_id FK(NOT VALID) 통합 테스트.

실제 PostgreSQL(로컬 dev DB)을 사용한다. 이 파일이 만든 행은
client_order_id/account_name 접두어(STEP252_TEST_)로 표시하고 각 테스트
finally에서 명시적으로 정리한다.

Settlement/Ledger FK, UserBrokerAccount 관련 변경은 STEP 2-5-2 범위 밖이므로
이 파일에서 다루지 않는다.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from stock_platform.database.session import get_session_factory

pytestmark = pytest.mark.integration

_PREFIX = "STEP252_TEST_"


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
                "DELETE FROM trading.trading_order "
                "WHERE client_order_id LIKE :p"
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


def _cid() -> str:
    return f"{_PREFIX}{uuid.uuid4().hex[:12]}"


def _insert_order(session, account_id: int, cid: str) -> int:
    return int(
        session.execute(
            text(
                """
                INSERT INTO trading.trading_order (
                    client_order_id, account_id, broker_code,
                    exchange_code, symbol, side_code, order_type_code,
                    order_quantity, remaining_quantity
                ) VALUES (
                    :cid, :aid, 'PAPER', 'PAPER', 'TESTSYM', 'BUY',
                    'MARKET', 1, 1
                )
                RETURNING order_id
                """
            ),
            {"cid": cid, "aid": account_id},
        ).scalar_one()
    )


# ---------------------------------------------------------------------------
# Migration / Constraint 상태
# ---------------------------------------------------------------------------


def test_fk_constraint_exists_not_valid_restrict(session) -> None:
    row = session.execute(
        text(
            """
            SELECT contype, convalidated, confrelid::regclass::text,
                   confdeltype
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            WHERE n.nspname = 'trading'
              AND t.relname = 'trading_order'
              AND c.conname = 'fk_trading_order_account'
            """
        )
    ).fetchone()
    assert row is not None, "fk_trading_order_account 제약이 존재해야 함"
    contype, convalidated, ref_table, confdeltype = row
    assert contype == "f"
    assert ref_table == "paper_account"
    assert confdeltype == "r"  # RESTRICT
    # STEP 2-5-2B에서 확인된 미해소 orphan(order_id=250) 때문에
    # 의도적으로 NOT VALID 상태를 유지한다.
    assert convalidated is False, (
        "orphan(order_id=250) 미해소로 인해 convalidated=False 여야 함 — "
        "만약 True라면 누군가 VALIDATE CONSTRAINT를 실행한 것이므로 "
        "orphan 처리 방침을 먼저 확인해야 함"
    )


def test_known_orphan_order_250_still_present_and_untouched(session) -> None:
    row = session.execute(
        text(
            "SELECT account_id, user_broker_account_id, status_code "
            "FROM trading.trading_order WHERE order_id = 250"
        )
    ).fetchone()
    if row is None:
        pytest.skip(
            "order_id=250이 이 환경에 없음 — 다른 DB 스냅샷일 수 있음"
        )
    account_id, uba_id, status_code = row
    # STEP 2-5-2B 조사 결과 그대로 — 삭제/변경되지 않았어야 함
    assert account_id == 58
    assert uba_id == 58
    assert status_code == "FILLED"


# ---------------------------------------------------------------------------
# DB 무결성 — 신규 행에 대한 FK 강제
# ---------------------------------------------------------------------------


def test_insert_with_existing_account_id_succeeds(session) -> None:
    existing_account_id = session.execute(
        text("SELECT account_id FROM trading.paper_account LIMIT 1")
    ).scalar()
    assert existing_account_id is not None
    order_id = _insert_order(session, existing_account_id, _cid())
    session.commit()
    assert order_id is not None


def test_insert_with_nonexistent_account_id_blocked(session) -> None:
    with pytest.raises(IntegrityError):
        _insert_order(session, 99_999_999, _cid())
        session.commit()
    session.rollback()


def test_restrict_blocks_deleting_referenced_paper_account(session) -> None:
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

    _insert_order(session, new_id, _cid())
    session.commit()

    with pytest.raises(IntegrityError):
        session.execute(
            text("DELETE FROM trading.paper_account WHERE account_id=:aid"),
            {"aid": new_id},
        )
        session.commit()
    session.rollback()


def test_trading_order_has_no_delete_endpoint_semantics() -> None:
    """TradingOrder는 append-only 유지 — 삭제 기능이 새로 생기지 않았음을
    코드 레벨로 확인(session.delete 호출부 부재)."""
    import inspect

    from stock_platform.order import repository as repo_module

    source = inspect.getsource(repo_module)
    assert "session.delete" not in source


def test_existing_order_data_preserved(session) -> None:
    total = session.execute(
        text("SELECT COUNT(*) FROM trading.trading_order")
    ).scalar()
    assert total is not None and total >= 1
