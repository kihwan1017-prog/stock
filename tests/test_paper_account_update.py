"""Paper 계좌 PATCH(부분 수정) 단위·API 테스트."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from stock_platform.api.main import app
from stock_platform.auth.account_ownership import assert_paper_account_access
from stock_platform.auth.deps import AuthenticatedUser, get_current_user
from stock_platform.database.session import get_db_session
from stock_platform.api.deps_admin import get_audit_service
from stock_platform.trading.account_models import PaperAccount
from stock_platform.trading.account_service import (
    PaperAccountError,
    PaperAccountService,
)


class UpdateFakeRepository:
    def __init__(self, *, has_activity: bool = False) -> None:
        self.account = PaperAccount(
            account_name="원본계좌",
            currency_code="KRW",
            initial_cash=Decimal("1000000.00"),
            available_cash=Decimal("1000000.00"),
            realized_profit_loss=Decimal("0"),
            is_default=False,
            is_active=True,
            user_id=10,
        )
        self.account.account_id = 5
        self.account.deleted_at = None
        self.has_activity = has_activity
        self.names: dict[str, PaperAccount] = {
            "원본계좌": self.account,
        }
        self.committed = False

    def get_account(self, account_id, *, include_deleted: bool = False):
        if account_id != 5:
            return None
        if self.account.deleted_at is not None and not include_deleted:
            return None
        return self.account

    def has_trading_activity(self, account_id: int) -> bool:
        return self.has_activity

    def find_by_account_name(self, account_name, *, exclude_account_id=None):
        found = self.names.get(account_name)
        if found is None:
            return None
        if exclude_account_id is not None and found.account_id == exclude_account_id:
            return None
        return found

    def clear_defaults_for_user(self, user_id, *, exclude_account_id=None):
        return None

    def persist_account(self, account):
        self.names[account.account_name] = account
        return account

    def commit(self) -> None:
        self.committed = True


def test_update_account_name_and_keep_other_fields() -> None:
    repo = UpdateFakeRepository()
    service = PaperAccountService(repo)  # type: ignore[arg-type]
    account, changes = service.update_account(
        5,
        account_name="새이름",
        fields_set={"account_name"},
    )
    assert account.account_name == "새이름"
    assert account.initial_cash == Decimal("1000000.00")
    assert account.is_active is True
    assert any(c["field"] == "account_name" for c in changes)
    assert repo.committed is True


def test_update_rejects_blank_name() -> None:
    repo = UpdateFakeRepository()
    service = PaperAccountService(repo)  # type: ignore[arg-type]
    with pytest.raises(PaperAccountError, match="공백"):
        service.update_account(
            5,
            account_name="   ",
            fields_set={"account_name"},
        )


def test_update_rejects_initial_cash_when_trading_history() -> None:
    repo = UpdateFakeRepository(has_activity=True)
    service = PaperAccountService(repo)  # type: ignore[arg-type]
    with pytest.raises(PaperAccountError, match="초기 자산"):
        service.update_account(
            5,
            initial_cash=Decimal("2000000"),
            fields_set={"initial_cash"},
        )


def test_update_initial_cash_when_no_history_syncs_available() -> None:
    repo = UpdateFakeRepository(has_activity=False)
    service = PaperAccountService(repo)  # type: ignore[arg-type]
    account, changes = service.update_account(
        5,
        initial_cash=Decimal("2500000"),
        fields_set={"initial_cash"},
    )
    assert account.initial_cash == Decimal("2500000.00")
    assert account.available_cash == Decimal("2500000.00")
    fields = {c["field"] for c in changes}
    assert "initial_cash" in fields
    assert "available_cash" in fields


def test_update_rejects_empty_patch() -> None:
    repo = UpdateFakeRepository()
    service = PaperAccountService(repo)  # type: ignore[arg-type]
    with pytest.raises(PaperAccountError, match="수정할 필드"):
        service.update_account(5, fields_set=set())


def test_update_rejects_deleted_account() -> None:
    repo = UpdateFakeRepository()
    repo.account.deleted_at = datetime.now(timezone.utc)
    service = PaperAccountService(repo)  # type: ignore[arg-type]
    # get_account include_deleted=False → None → LookupError
    with pytest.raises(LookupError):
        service.update_account(
            5,
            account_name="x",
            fields_set={"account_name"},
        )


def test_assert_hides_deleted_for_update_path() -> None:
    session = MagicMock()
    paper = MagicMock()
    paper.user_id = 10
    paper.deleted_at = datetime.now(timezone.utc)
    with pytest.MonkeyPatch.context() as mp:
        repo = MagicMock()
        repo.get_account.return_value = paper
        mp.setattr(
            "stock_platform.auth.account_ownership.PaperAccountRepository",
            lambda _s: repo,
        )
        with pytest.raises(HTTPException) as exc:
            assert_paper_account_access(
                AuthenticatedUser(
                    user_id=10,
                    username="u",
                    roles=["user"],
                    permissions=["trading:write"],
                ),
                1,
                session,
            )
        assert exc.value.status_code == 404


def test_patch_requires_auth() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    assert (
        client.patch(
            "/api/v1/paper-accounts/1",
            json={"account_name": "x"},
        ).status_code
        == 401
    )


def test_patch_idor_forbidden() -> None:
    client = TestClient(app, raise_server_exceptions=False)

    def _user() -> AuthenticatedUser:
        return AuthenticatedUser(
            user_id=2,
            username="other",
            roles=["user"],
            permissions=["trading:write", "trading:read"],
        )

    paper = MagicMock()
    paper.user_id = 99
    paper.account_id = 1
    paper.deleted_at = None

    app.dependency_overrides[get_current_user] = _user
    with pytest.MonkeyPatch.context() as mp:
        repo = MagicMock()
        repo.get_account.return_value = paper
        mp.setattr(
            "stock_platform.auth.account_ownership.PaperAccountRepository",
            lambda _s: repo,
        )
        try:
            response = client.patch(
                "/api/v1/paper-accounts/1",
                json={"account_name": "hack"},
            )
            assert response.status_code == 403
        finally:
            app.dependency_overrides.clear()


def test_patch_admin_success_writes_audit() -> None:
    client = TestClient(app, raise_server_exceptions=False)

    def _admin() -> AuthenticatedUser:
        return AuthenticatedUser(
            user_id=1,
            username="admin",
            roles=["admin"],
            permissions=["*"],
        )

    account = PaperAccount(
        account_name="after",
        currency_code="KRW",
        initial_cash=Decimal("1000000"),
        available_cash=Decimal("1000000"),
        realized_profit_loss=Decimal("0"),
        is_default=False,
        is_active=True,
        user_id=3,
    )
    account.account_id = 7
    account.deleted_at = None
    account.created_at = datetime.now(timezone.utc)
    account.updated_at = datetime.now(timezone.utc)

    changes = [
        {"field": "account_name", "before": "before", "after": "after"},
    ]
    audit = MagicMock()
    session = MagicMock()

    class _FakeService:
        def update_account(self, account_id, **kwargs):
            assert account_id == 7
            return account, changes

    app.dependency_overrides[get_current_user] = _admin
    app.dependency_overrides[get_db_session] = lambda: session
    app.dependency_overrides[get_audit_service] = lambda: audit

    with pytest.MonkeyPatch.context() as mp:
        access_account = MagicMock()
        access_account.user_id = 3
        access_account.deleted_at = None
        mp.setattr(
            "stock_platform.api.v1.paper_accounts.assert_paper_account_access",
            lambda *a, **k: access_account,
        )
        mp.setattr(
            "stock_platform.api.v1.paper_accounts._service",
            lambda _s: _FakeService(),
        )
        mp.setattr(
            "stock_platform.api.v1.paper_accounts.PaperAccountRepository",
            lambda _s: MagicMock(
                has_trading_activity=lambda _id: False,
            ),
        )
        try:
            response = client.patch(
                "/api/v1/paper-accounts/7",
                json={"account_name": "after"},
            )
            assert response.status_code == 200
            body = response.json()
            assert body["account_name"] == "after"
            assert body["can_edit_initial_cash"] is True
            audit.record.assert_called_once()
            kwargs = audit.record.call_args.kwargs
            assert kwargs["event_type"] == "PAPER_ACCOUNT_UPDATE"
            assert kwargs["detail"]["account_id"] == 7
            assert "account_name" in kwargs["detail"]["changed_fields"]
        finally:
            app.dependency_overrides.clear()


def test_patch_not_found() -> None:
    client = TestClient(app, raise_server_exceptions=False)

    def _admin() -> AuthenticatedUser:
        return AuthenticatedUser(
            user_id=1,
            username="admin",
            roles=["admin"],
            permissions=["*"],
        )

    app.dependency_overrides[get_current_user] = _admin
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "stock_platform.api.v1.paper_accounts.assert_paper_account_access",
            lambda *a, **k: (_ for _ in ()).throw(
                HTTPException(status_code=404, detail="not found")
            ),
        )
        try:
            response = client.patch(
                "/api/v1/paper-accounts/99999",
                json={"account_name": "x"},
            )
            assert response.status_code == 404
        finally:
            app.dependency_overrides.clear()
