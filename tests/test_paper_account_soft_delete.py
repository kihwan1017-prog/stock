"""Paper 계좌 Soft Delete 단위 테스트."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from stock_platform.api.main import app
from stock_platform.auth.account_ownership import assert_paper_account_access
from stock_platform.auth.deps import AuthenticatedUser, get_current_user, require_admin_user
from stock_platform.trading.account_models import PaperAccount
from stock_platform.trading.account_service import (
    PaperAccountError,
    PaperAccountService,
)


class SoftDeleteFakeRepository:
    def __init__(self, *, has_history: bool = False) -> None:
        self.account = PaperAccount(
            account_name="테스트계좌",
            currency_code="KRW",
            initial_cash=Decimal("1000000"),
            available_cash=Decimal("1000000"),
            realized_profit_loss=Decimal("0"),
            is_default=False,
            is_active=True,
        )
        self.account.account_id = 11
        self.account.deleted_at = None
        self.has_history = has_history
        self.committed = False
        self.soft_deleted = False

    def get_account(self, account_id, *, include_deleted: bool = False):
        if account_id != 11:
            return None
        if self.account.deleted_at is not None and not include_deleted:
            return None
        return self.account

    def has_order_or_trade_history(self, account_id: int) -> bool:
        return self.has_history

    def soft_delete_account(self, account, *, deleted_at=None):
        stamp = deleted_at or datetime.now(timezone.utc)
        account.is_active = False
        account.is_default = False
        account.deleted_at = stamp
        account.account_name = f"{account.account_name}__deleted_{account.account_id}"
        self.soft_deleted = True
        return account

    def commit(self) -> None:
        self.committed = True


def test_soft_delete_sets_deleted_at_and_never_hard_deletes() -> None:
    repo = SoftDeleteFakeRepository(has_history=True)
    service = PaperAccountService(repo)  # type: ignore[arg-type]

    result = service.soft_delete_account(11, allow_default=True)

    assert result["deleted"] is True
    assert result["mode"] == "soft_delete"
    assert result["has_trading_history"] is True
    assert result["hard_delete_allowed"] is False
    assert repo.soft_deleted is True
    assert repo.committed is True
    assert repo.account.deleted_at is not None
    assert repo.account.is_active is False
    assert "__deleted_11" in repo.account.account_name


def test_soft_delete_rejects_already_deleted() -> None:
    repo = SoftDeleteFakeRepository()
    repo.account.deleted_at = datetime.now(timezone.utc)
    service = PaperAccountService(repo)  # type: ignore[arg-type]

    with pytest.raises(PaperAccountError, match="이미 삭제"):
        service.soft_delete_account(11, allow_default=True)


def test_soft_delete_rejects_default_unless_allowed() -> None:
    repo = SoftDeleteFakeRepository()
    repo.account.is_default = True
    service = PaperAccountService(repo)  # type: ignore[arg-type]

    with pytest.raises(PaperAccountError, match="기본 Paper"):
        service.soft_delete_account(11, allow_default=False)

    result = service.soft_delete_account(11, allow_default=True)
    assert result["deleted"] is True


def test_assert_paper_account_access_hides_soft_deleted() -> None:
    session = MagicMock()
    paper = MagicMock()
    paper.user_id = 10
    paper.account_id = 1
    paper.deleted_at = datetime.now(timezone.utc)

    with pytest.MonkeyPatch.context() as mp:
        repo = MagicMock()
        repo.get_account.return_value = paper
        mp.setattr(
            "stock_platform.auth.account_ownership.PaperAccountRepository",
            lambda _session: repo,
        )
        with pytest.raises(HTTPException) as exc:
            assert_paper_account_access(
                AuthenticatedUser(
                    user_id=10,
                    username="owner",
                    roles=["user"],
                    permissions=["trading:read"],
                ),
                1,
                session,
            )
        assert exc.value.status_code == 404


def test_delete_paper_account_requires_admin() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    assert client.delete("/api/v1/paper-accounts/1").status_code == 401

    def _member() -> AuthenticatedUser:
        return AuthenticatedUser(
            user_id=2,
            username="member",
            roles=["user"],
            permissions=["trading:write", "trading:read"],
        )

    app.dependency_overrides[get_current_user] = _member
    try:
        # require_admin_user 는 get_current_user 기반 — user 는 403
        response = client.delete("/api/v1/paper-accounts/1")
        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_delete_paper_account_admin_soft_deletes_and_audits() -> None:
    client = TestClient(app, raise_server_exceptions=False)

    def _admin() -> AuthenticatedUser:
        return AuthenticatedUser(
            user_id=1,
            username="admin",
            roles=["admin"],
            permissions=["*"],
        )

    fake_result = {
        "deleted": True,
        "account_id": 99,
        "mode": "soft_delete",
        "deleted_at": "2026-07-22T00:00:00+00:00",
        "has_trading_history": True,
        "hard_delete_allowed": False,
    }
    audit = MagicMock()
    session = MagicMock()

    class _FakeService:
        def soft_delete_account(self, account_id, *, allow_default=False):
            assert account_id == 99
            assert allow_default is True
            return fake_result

    app.dependency_overrides[get_current_user] = _admin
    app.dependency_overrides[require_admin_user] = _admin

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "stock_platform.api.v1.paper_accounts._service",
            lambda _session: _FakeService(),
        )
        mp.setattr(
            "stock_platform.api.v1.paper_accounts.get_db_session",
            lambda: session,
        )
        # Depends(get_db_session) / get_audit_service 는 FastAPI DI — override
        from stock_platform.database.session import get_db_session
        from stock_platform.api.deps_admin import get_audit_service

        app.dependency_overrides[get_db_session] = lambda: session
        app.dependency_overrides[get_audit_service] = lambda: audit

        try:
            response = client.delete("/api/v1/paper-accounts/99")
            assert response.status_code == 200
            body = response.json()
            assert body["mode"] == "soft_delete"
            assert body["hard_delete_allowed"] is False
            audit.record.assert_called_once()
            kwargs = audit.record.call_args.kwargs
            assert kwargs["event_type"] == "PAPER_ACCOUNT_SOFT_DELETE"
            assert kwargs["actor"] == "admin"
            assert kwargs["detail"]["account_id"] == 99
            session.commit.assert_called()
        finally:
            app.dependency_overrides.clear()


def test_openapi_lists_paper_account_delete() -> None:
    paths = app.openapi()["paths"]
    assert "/api/v1/paper-accounts/{account_id}" in paths
    assert "delete" in paths["/api/v1/paper-accounts/{account_id}"]
