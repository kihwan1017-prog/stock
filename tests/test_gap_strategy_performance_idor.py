"""사용자 계좌 전략 성과 API — 소유권/IDOR 가드 존재 검증."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


@pytest.mark.unit
def test_strategy_performance_api_asserts_ownership() -> None:
    path = (
        Path(__file__).resolve().parents[1]
        / "src/stock_platform/api/v1/user_account_strategy_performance.py"
    )
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "assert_paper_account_access" in calls
    assert "assert_broker_account_access" in calls
    assert "ACCOUNT_LEDGER_NOT_BACKTEST" in source
    assert "require_permission" in source
