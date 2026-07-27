"""STEP 8-9C-1 — RBAC user_role / JSONB 정합."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from stock_platform.auth.role_sync import (
    reconcile_user_roles,
    resolve_role_codes,
)


def test_resolve_role_codes_prefers_rbac() -> None:
    user = SimpleNamespace(user_id=1, roles=["user"])
    rbac = MagicMock()
    rbac.list_role_codes_for_user.return_value = ["admin"]
    assert resolve_role_codes(user, rbac) == ["admin"]


def test_resolve_role_codes_falls_back_to_jsonb() -> None:
    user = SimpleNamespace(user_id=1, roles=["admin"])
    rbac = MagicMock()
    rbac.list_role_codes_for_user.return_value = []
    assert resolve_role_codes(user, rbac) == ["admin"]


def test_reconcile_fills_user_role_from_jsonb() -> None:
    session = MagicMock()
    user = SimpleNamespace(user_id=7, roles=["admin"])
    rbac = MagicMock()
    rbac.list_role_codes_for_user.return_value = []
    rbac.get_role_ids_by_codes.return_value = [1]

    codes, changed = reconcile_user_roles(session, user, rbac)
    assert codes == ["admin"]
    assert changed is True
    rbac.replace_user_roles.assert_called_once_with(7, [1])
    session.flush.assert_called()


def test_reconcile_noop_when_rbac_present() -> None:
    session = MagicMock()
    user = SimpleNamespace(user_id=7, roles=["admin"])
    rbac = MagicMock()
    rbac.list_role_codes_for_user.return_value = ["admin"]

    codes, changed = reconcile_user_roles(session, user, rbac)
    assert codes == ["admin"]
    assert changed is False
    rbac.replace_user_roles.assert_not_called()
