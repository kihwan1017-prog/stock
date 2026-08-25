"""Asset context list — SQL pagination (rank 필터 없을 때)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

from stock_platform.operation.upbit_market_context.research_detail_workspace import (
    list_asset_context,
)


def test_list_asset_context_without_rank_uses_count_and_page_query() -> None:
    session = MagicMock()
    session.scalar.return_value = 42

    row = MagicMock()
    row.snapshot_id = 1
    row.observed_at = datetime(2026, 8, 25, tzinfo=timezone.utc)
    row.symbol = "KRW-BTC"
    row.feature_key = "ticker"
    row.quality = "OK"
    row.source = "upbit"
    row.value_json = {"trade_price": 1, "turnover_rank": 3}

    session.scalars.return_value = [row]

    out = list_asset_context(session, page=2, page_size=20)
    assert out["schema"] == "upbit_research_asset_context_list_v1"
    assert out["total"] == 42
    assert out["page"] == 2
    assert out["page_size"] == 20
    assert len(out["items"]) == 1
    assert out["items"][0]["symbol"] == "KRW-BTC"
    assert session.scalar.call_count == 1
    assert session.scalars.call_count == 1


def test_list_asset_context_with_rank_uses_bounded_prefetch() -> None:
    session = MagicMock()
    row = MagicMock()
    row.snapshot_id = 9
    row.observed_at = datetime(2026, 8, 25, tzinfo=timezone.utc)
    row.symbol = "KRW-ETH"
    row.feature_key = "ticker"
    row.quality = "OK"
    row.source = "upbit"
    row.value_json = {"turnover_rank": 2}
    session.scalars.return_value = [row]

    out = list_asset_context(session, page=1, page_size=20, rank_max=5)
    assert out["total"] == 1
    # rank 경로는 count scalar 없이 prefetch
    assert session.scalar.call_count == 0
    assert session.scalars.call_count == 1
