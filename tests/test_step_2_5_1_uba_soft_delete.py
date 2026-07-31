"""STEP 2-5-1 — UserBrokerAccount Soft Delete 통합 테스트.

실제 PostgreSQL(로컬 dev DB)을 사용한다. 테스트가 만든 행은
account_alias 접두어(STEP251_TEST_)로 표시하고 finally에서 명시적으로
정리해, 공유 dev DB를 오염시키지 않는다.

TradingOrder FK / AccountDailySettlement FK / LedgerAdjustment FK는
STEP 2-5-1 범위 밖이므로 이 파일에서 다루지 않는다.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from stock_platform.database.session import get_session_factory
from stock_platform.trading.account_masking import hash_account_ref
from stock_platform.trading.account_models import UserBrokerAccount
from stock_platform.trading.admin_broker_account_service import (
    AdminBrokerAccountService,
)
from stock_platform.trading.user_account_service import (
    UserAccountError,
    UserAccountService,
)

pytestmark = pytest.mark.integration

_ALIAS_PREFIX = "STEP251_TEST_"


def _unique_account_number() -> str:
    # hash_account_ref만 통과하면 되므로 숫자 위주 임의 문자열 사용
    return "9" + uuid.uuid4().hex[:10]


@pytest.fixture()
def session():
    Session = get_session_factory()
    s = Session()
    try:
        # 테스트에 쓸 auth.user 하나를 확보(생성하지 않고 기존 행 재사용 —
        # 존재하지 않으면 스킵해 dev DB에 새 계정을 만들지 않는다)
        user_id = s.execute(
            text("SELECT user_id FROM auth.user ORDER BY user_id LIMIT 1")
        ).scalar()
        if user_id is None:
            pytest.skip("auth.user에 테스트용 행이 없어 스킵")
        s.info["test_user_id"] = int(user_id)
        yield s
    finally:
        # 이 파일이 만든 행만 정리 (다른 테스트/실데이터는 건드리지 않음)
        s.rollback()
        s.execute(
            text(
                "DELETE FROM trading.user_broker_account "
                "WHERE account_alias LIKE :prefix"
            ),
            {"prefix": f"{_ALIAS_PREFIX}%"},
        )
        s.commit()
        s.close()


def _create_test_uba(
    session, *, user_id: int, broker_code: str = "KIWOOM"
) -> tuple[UserBrokerAccount, str]:
    account_number = _unique_account_number()
    view = UserAccountService(session).create_account(
        user_id,
        account_type=broker_code,
        account_name=f"{_ALIAS_PREFIX}{uuid.uuid4().hex[:8]}",
        account_number=account_number,
        auto_commit=True,
    )
    row = session.get(UserBrokerAccount, int(view.account_id))
    assert row is not None
    return row, account_number


# ---------------------------------------------------------------------------
# 1) 연결 해제 → Soft Delete 상태 전환
# ---------------------------------------------------------------------------


def test_delete_account_soft_deletes_row_and_keeps_it_in_db(session) -> None:
    user_id = session.info["test_user_id"]
    row, _ = _create_test_uba(session, user_id=user_id)
    uba_id = int(row.user_broker_account_id)

    result = UserAccountService(session).delete_account(
        user_id, uba_id, account_type="KIWOOM"
    )

    assert result["deleted"] is True
    assert result["mode"] == "unlink"
    assert result["deletion_mode"] == "soft_delete"
    assert result["hard_delete_allowed"] is False

    # 행이 실제로 DB에 남아있는지 확인 (Hard Delete 아님)
    reloaded = session.get(UserBrokerAccount, uba_id)
    assert reloaded is not None
    assert reloaded.deleted_at is not None
    assert reloaded.is_active is False
    assert reloaded.is_default is False
    assert reloaded.connection_status == "DISCONNECTED"
    assert reloaded.live_order_enabled is False
    assert reloaded.live_armed is False
    assert reloaded.arm_token_hash is None
    assert reloaded.arm_expires_at is None
    assert reloaded.arm_armed_by is None
    assert reloaded.arm_armed_at is None


def test_delete_account_forces_live_and_arm_flags_off(session) -> None:
    user_id = session.info["test_user_id"]
    row, _ = _create_test_uba(session, user_id=user_id)
    uba_id = int(row.user_broker_account_id)

    # ARM/LIVE가 켜져 있던 상태를 흉내낸다
    row.live_order_enabled = True
    row.live_armed = True
    row.arm_token_hash = "dummy_hash"
    session.commit()

    UserAccountService(session).delete_account(
        user_id, uba_id, account_type="KIWOOM"
    )
    reloaded = session.get(UserBrokerAccount, uba_id)
    assert reloaded.live_order_enabled is False
    assert reloaded.live_armed is False
    assert reloaded.arm_token_hash is None


def test_delete_account_idempotent_on_already_deleted(session) -> None:
    user_id = session.info["test_user_id"]
    row, _ = _create_test_uba(session, user_id=user_id)
    uba_id = int(row.user_broker_account_id)

    UserAccountService(session).delete_account(
        user_id, uba_id, account_type="KIWOOM"
    )
    # 서버 오류(예외 전파로 500) 없이 명확한 도메인 오류로 처리되어야 함
    with pytest.raises(UserAccountError, match="이미 삭제"):
        UserAccountService(session).delete_account(
            user_id, uba_id, account_type="KIWOOM"
        )


# ---------------------------------------------------------------------------
# 2) 조회 필터 — 사용자 / 관리자
# ---------------------------------------------------------------------------


def test_user_list_excludes_deleted_even_with_include_inactive(session) -> None:
    user_id = session.info["test_user_id"]
    row, _ = _create_test_uba(session, user_id=user_id)
    uba_id = int(row.user_broker_account_id)
    UserAccountService(session).delete_account(
        user_id, uba_id, account_type="KIWOOM"
    )

    views_default = UserAccountService(session).list_accounts(user_id)
    assert all(v.account_id != uba_id for v in views_default)

    views_include_inactive = UserAccountService(session).list_accounts(
        user_id, include_inactive=True
    )
    assert all(v.account_id != uba_id for v in views_include_inactive)


def test_admin_list_excludes_deleted_by_default_includes_with_flag(
    session,
) -> None:
    user_id = session.info["test_user_id"]
    row, _ = _create_test_uba(session, user_id=user_id)
    uba_id = int(row.user_broker_account_id)
    UserAccountService(session).delete_account(
        user_id, uba_id, account_type="KIWOOM"
    )

    admin = AdminBrokerAccountService(session)
    default_result = admin.list_accounts(
        broker_code="KIWOOM", owner_user_id=user_id
    )
    assert all(
        item["user_broker_account_id"] != uba_id
        for item in default_result["items"]
    )

    with_deleted = admin.list_accounts(
        broker_code="KIWOOM",
        owner_user_id=user_id,
        include_deleted=True,
    )
    matching = [
        item
        for item in with_deleted["items"]
        if item["user_broker_account_id"] == uba_id
    ]
    assert len(matching) == 1
    assert matching[0]["deleted_at"] is not None


# ---------------------------------------------------------------------------
# 3) 쓰기 액션 차단(삭제된 계좌)
# ---------------------------------------------------------------------------


def test_update_account_blocks_deleted_broker_account(session) -> None:
    user_id = session.info["test_user_id"]
    row, _ = _create_test_uba(session, user_id=user_id)
    uba_id = int(row.user_broker_account_id)
    UserAccountService(session).delete_account(
        user_id, uba_id, account_type="KIWOOM"
    )

    with pytest.raises(UserAccountError, match="삭제된"):
        UserAccountService(session).update_account(
            user_id, uba_id, account_type="KIWOOM", account_name="X"
        )


def test_connect_blocks_deleted_broker_account(session) -> None:
    user_id = session.info["test_user_id"]
    row, _ = _create_test_uba(session, user_id=user_id)
    uba_id = int(row.user_broker_account_id)
    UserAccountService(session).delete_account(
        user_id, uba_id, account_type="KIWOOM"
    )

    with pytest.raises(UserAccountError, match="삭제된"):
        UserAccountService(session).connect(
            user_id, uba_id, account_type="KIWOOM"
        )


# ---------------------------------------------------------------------------
# 4) 재연결 Revive
# ---------------------------------------------------------------------------


def test_reconnect_revives_soft_deleted_row_instead_of_new_row(
    session,
) -> None:
    user_id = session.info["test_user_id"]
    row, account_number = _create_test_uba(session, user_id=user_id)
    uba_id = int(row.user_broker_account_id)

    UserAccountService(session).delete_account(
        user_id, uba_id, account_type="KIWOOM"
    )

    view = UserAccountService(session).create_account(
        user_id,
        account_type="KIWOOM",
        account_name=f"{_ALIAS_PREFIX}revived",
        account_number=account_number,  # 동일 계좌번호 → 동일 ref_hash
    )

    # 새 행이 아니라 기존 행이 재사용되어야 함(같은 PK)
    assert int(view.account_id) == uba_id
    reloaded = session.get(UserBrokerAccount, uba_id)
    assert reloaded.deleted_at is None
    assert reloaded.is_active is True
    assert reloaded.connection_status == "PENDING"
    assert reloaded.live_order_enabled is False
    assert reloaded.live_armed is False

    # 동일 (user_id, broker_code, account_ref_hash) 조합의 행이 1개뿐인지 확인
    ref_hash = hash_account_ref(account_number)
    count = session.scalar(
        select(UserBrokerAccount)
        .where(
            UserBrokerAccount.user_id == user_id,
            UserBrokerAccount.broker_code == "KIWOOM",
            UserBrokerAccount.account_ref_hash == ref_hash,
        )
        .with_only_columns(UserBrokerAccount.user_broker_account_id)
    )
    assert count == uba_id


def test_duplicate_active_connection_still_blocked(session) -> None:
    user_id = session.info["test_user_id"]
    row, account_number = _create_test_uba(session, user_id=user_id)

    with pytest.raises(UserAccountError, match="이미 연결된"):
        UserAccountService(session).create_account(
            user_id,
            account_type="KIWOOM",
            account_name=f"{_ALIAS_PREFIX}dup",
            account_number=account_number,
        )


def test_admin_create_account_duplicate_precheck_ignores_deleted(
    session,
) -> None:
    user_id = session.info["test_user_id"]
    row, account_number = _create_test_uba(session, user_id=user_id)
    uba_id = int(row.user_broker_account_id)
    UserAccountService(session).delete_account(
        user_id, uba_id, account_type="KIWOOM"
    )

    admin = AdminBrokerAccountService(session)
    out = admin.create_account(
        owner_user_id=user_id,
        broker_code="KIWOOM",
        account_alias=f"{_ALIAS_PREFIX}admin_revive",
        account_number=account_number,
        apply_recommended_risk=False,
        actor="TEST_ADMIN",
    )
    assert out["user_broker_account_id"] == uba_id
    assert out["deleted_at"] is None


# ---------------------------------------------------------------------------
# 5) DB 레벨 무결성 — 부분 유니크 인덱스
# ---------------------------------------------------------------------------


def test_db_rejects_duplicate_active_rows_via_partial_unique_index(
    session,
) -> None:
    user_id = session.info["test_user_id"]
    account_number = _unique_account_number()
    ref_hash = hash_account_ref(account_number)

    row1 = UserBrokerAccount(
        user_id=user_id,
        broker_code="KIWOOM",
        account_alias=f"{_ALIAS_PREFIX}raw1",
        account_ref_hash=ref_hash,
        currency_code="KRW",
        is_default=False,
        is_active=True,
        connection_status="PENDING",
    )
    session.add(row1)
    session.commit()

    row2 = UserBrokerAccount(
        user_id=user_id,
        broker_code="KIWOOM",
        account_alias=f"{_ALIAS_PREFIX}raw2",
        account_ref_hash=ref_hash,
        currency_code="KRW",
        is_default=False,
        is_active=True,
        connection_status="PENDING",
    )
    session.add(row2)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_db_allows_duplicate_when_one_is_soft_deleted(session) -> None:
    user_id = session.info["test_user_id"]
    account_number = _unique_account_number()
    ref_hash = hash_account_ref(account_number)

    row1 = UserBrokerAccount(
        user_id=user_id,
        broker_code="KIWOOM",
        account_alias=f"{_ALIAS_PREFIX}softdup1",
        account_ref_hash=ref_hash,
        currency_code="KRW",
        is_default=False,
        is_active=False,
        connection_status="DISCONNECTED",
    )
    session.add(row1)
    session.commit()
    from datetime import datetime, timezone

    row1.deleted_at = datetime.now(timezone.utc)
    session.commit()

    row2 = UserBrokerAccount(
        user_id=user_id,
        broker_code="KIWOOM",
        account_alias=f"{_ALIAS_PREFIX}softdup2",
        account_ref_hash=ref_hash,
        currency_code="KRW",
        is_default=False,
        is_active=True,
        connection_status="PENDING",
    )
    session.add(row2)
    # 삭제된 행과는 유니크 충돌 없음 — 정상 커밋되어야 함
    session.commit()
    assert row2.user_broker_account_id is not None
