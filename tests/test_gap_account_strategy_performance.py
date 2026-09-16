"""계좌별 전략 성과 집계 + 미식별 처리."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from stock_platform.trading.account_strategy_performance_service import (
    AccountStrategyPerformanceService,
)
from stock_platform.trading.order_strategy_provenance import UNATTRIBUTED


def _scalar_result(rows):
    result = MagicMock()
    result.__iter__ = lambda self: iter(rows)
    return result


@pytest.mark.unit
def test_summarize_paper_separates_strategy_and_unattributed() -> None:
    session = MagicMock()
    trades = [
        SimpleNamespace(
            strategy_id=10,
            quantity=Decimal("2"),
            side="BUY",
            realized_profit_loss=Decimal("0"),
            traded_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
        SimpleNamespace(
            strategy_id=10,
            quantity=Decimal("2"),
            side="SELL",
            realized_profit_loss=Decimal("100"),
            traded_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        ),
        SimpleNamespace(
            strategy_id=None,
            quantity=Decimal("1"),
            side="SELL",
            realized_profit_loss=Decimal("-50"),
            traded_at=datetime(2026, 1, 3, tzinfo=timezone.utc),
        ),
    ]
    orders = [
        SimpleNamespace(strategy_id=10),
        SimpleNamespace(strategy_id=None),
    ]

    # scalars(trade_stmt) then scalars(order_stmt) then strategy enrich
    def scalars(stmt):  # noqa: ARG001
        # 호출 순서로 trade → order → strategy select
        if not hasattr(scalars, "n"):
            scalars.n = 0
        scalars.n += 1
        if scalars.n == 1:
            return trades
        if scalars.n == 2:
            return orders
        return [
            SimpleNamespace(
                strategy_id=10, name="Alpha", strategy_code="ALPHA"
            )
        ]

    session.scalars.side_effect = scalars
    items = AccountStrategyPerformanceService(session).summarize_paper(
        paper_account_id=1
    )
    by_attr = {i["attribution"]: i for i in items}
    assert by_attr["strategy:10"]["order_count"] == 1
    assert by_attr["strategy:10"]["fill_count"] == 2
    assert by_attr["strategy:10"]["win_count"] == 1
    assert by_attr["strategy:10"]["strategy_name"] == "Alpha"
    assert by_attr["strategy:10"]["source"] == "ACCOUNT_LEDGER_NOT_BACKTEST"
    assert by_attr[UNATTRIBUTED]["order_count"] == 1
    assert by_attr[UNATTRIBUTED]["loss_count"] == 1
    assert by_attr[UNATTRIBUTED]["strategy_name"] == "전략 미식별"
    assert by_attr[UNATTRIBUTED]["strategy_id"] is None


@pytest.mark.unit
def test_unattributed_only_bucket_gets_korean_label() -> None:
    session = MagicMock()

    def scalars(stmt):  # noqa: ARG001
        if not hasattr(scalars, "n"):
            scalars.n = 0
        scalars.n += 1
        if scalars.n == 1:
            return [
                SimpleNamespace(
                    strategy_id=None,
                    quantity=Decimal("1"),
                    side="BUY",
                    realized_profit_loss=Decimal("0"),
                    traded_at=None,
                )
            ]
        return [SimpleNamespace(strategy_id=None)]

    session.scalars.side_effect = scalars
    items = AccountStrategyPerformanceService(session).summarize_paper(
        paper_account_id=99
    )
    assert len(items) == 1
    assert items[0]["strategy_name"] == "전략 미식별"
    assert items[0]["attribution"] == UNATTRIBUTED


@pytest.mark.unit
def test_member_cleanup_protects_exact_usernames() -> None:
    from stock_platform.api.v1.admin_member_cleanup import (
        PROTECTED_USERNAMES,
        _is_protected,
    )

    assert PROTECTED_USERNAMES == frozenset({"admin", "kikicom"})
    assert _is_protected("admin")
    assert _is_protected("Admin")
    assert _is_protected("kikicom")
    assert not _is_protected("admin_test")
    assert not _is_protected("kikicom2")
    assert not _is_protected("admin@example.com")
