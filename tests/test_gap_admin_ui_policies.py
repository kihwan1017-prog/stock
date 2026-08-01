"""업비트 화면 역할 분리 · 운영센터 planned 타일 · 회원 정리 정책."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FE = ROOT / "frontend" / "src"


@pytest.mark.unit
def test_upbit_account_and_market_pages_are_separated() -> None:
    account_page = (FE / "app/(admin)/admin/upbit/page.tsx").read_text(
        encoding="utf-8"
    )
    market_page = (
        FE / "app/(admin)/admin/upbit/markets/page.tsx"
    ).read_text(encoding="utf-8")
    routes = (FE / "config/routes.ts").read_text(encoding="utf-8")
    menu = (FE / "config/menu.tsx").read_text(encoding="utf-8")

    assert "AdminUpbitLiveUbaPanel" in account_page
    assert "getUpbitMarkets" not in account_page
    assert "시세/종목은 업비트 시세" in account_page

    assert "getUpbitMarkets" in market_page
    assert "AdminUpbitLiveUbaPanel" not in market_page
    assert "업비트 시세" in market_page

    assert 'upbitMarkets: "/admin/upbit/markets"' in routes
    assert "업비트 계좌" in menu
    assert "업비트 시세" in menu


@pytest.mark.unit
def test_ops_center_disables_unimplemented_backup_restore_log_tail() -> None:
    tiles = (
        FE / "features/admin/operations/operationCenterTiles.ts"
    ).read_text(encoding="utf-8")
    page = (FE / "app/(admin)/admin/operations/page.tsx").read_text(
        encoding="utf-8"
    )
    assert 'support: "planned"' in tiles
    assert "앱 로그 테일 API 미구현" in tiles
    assert "웹 Backup dump API 미구현" in tiles or "pg_dump" in tiles
    assert "UnimplementedApiPanel" in page
    assert "isPlanned" in page
    assert "disabled" in page


@pytest.mark.unit
def test_member_cleanup_execute_requires_confirm_and_forbids_hard_delete() -> None:
    src = (
        ROOT
        / "src/stock_platform/api/v1/admin_member_cleanup.py"
    ).read_text(encoding="utf-8")
    assert 'PROTECTED_USERNAMES = frozenset({"admin", "kikicom"})' in src
    assert "DELETE_TEST_ACCOUNTS" in src
    assert "backup_confirmed" in src
    assert "hard_delete forbidden" in src
    assert "hard_delete_performed\": False" in src or (
        '"hard_delete_performed": False' in src
    )
