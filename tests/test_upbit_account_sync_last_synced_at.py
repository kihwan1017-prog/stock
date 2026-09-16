"""Upbit account sync must refresh UBA.last_synced_at (ops BALANCE_SYNC SoT)."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from stock_platform.broker.upbit.account_sync_service import (
    UpbitAccountSyncService,
)


@pytest.mark.asyncio
async def test_upbit_account_sync_updates_uba_last_synced_at(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 9, 6, 0, 0, tzinfo=timezone.utc)
    session = MagicMock()
    # _resolve_uba_id용
    session.get.return_value = SimpleNamespace(
        id=1380,
        broker_code="UPBIT",
    )

    client = MagicMock()
    client.account_ref = "UBA:1380"
    client.use_mock = True
    client.list_accounts = AsyncMock(
        return_value=[
            {"currency": "KRW", "unit_currency": "KRW", "balance": "1"},
            {
                "currency": "BTC",
                "unit_currency": "KRW",
                "balance": "0.01",
                "avg_buy_price": "100",
            },
        ]
    )
    client.list_tickers = AsyncMock(
        return_value=[{"market": "KRW-BTC", "trade_price": 100.0}]
    )

    snap_entity = SimpleNamespace(
        broker_account_snapshot_id=99,
        snapshot_generation=1,
        snapshot_hash="h",
        snapshot_status="ACTIVE",
    )
    mapped = SimpleNamespace(
        broker_code="UPBIT",
        account_number="UBA:1380",
        deposit_amount=1,
        available_order_amount=1,
        total_evaluation_amount=1,
        total_profit_loss=0,
        positions=[],
        synchronized_at=now,
    )

    service = UpbitAccountSyncService(
        session=session,
        private_client=client,
        user_broker_account_id=1380,
    )
    service._repository = MagicMock()
    service._repository.save.return_value = snap_entity

    from stock_platform.broker.upbit import account_sync_service as mod

    monkeypatch.setattr(
        mod.UpbitAccountMapper,
        "map",
        staticmethod(lambda **_: mapped),
    )

    out = await service.synchronize(user_broker_account_id=1380)

    assert session.execute.called
    sql = str(session.execute.call_args.args[0])
    assert "last_synced_at" in sql
    assert session.commit.called
    assert out["user_broker_account_id"] == 1380
    assert out["last_synced_at"] == now.isoformat()
