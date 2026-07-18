import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from stock_platform.broker.kiwoom.account_state_sync_service import (
    KiwoomAccountStateSyncService,
)


def test_account_state_sync_orchestrates_account_and_pending() -> None:
    account_sync = SimpleNamespace(
        synchronize=AsyncMock(
            return_value={
                "account_number": "12345678",
                "deposit_amount": "1000000",
                "available_order_amount": "900000",
                "total_profit_loss": "12000",
                "position_count": 1,
            }
        )
    )
    pending_sync = SimpleNamespace(
        synchronize=AsyncMock(
            return_value={
                "broker_code": "KIWOOM",
                "account_number": "12345678",
                "pending_order_count": 2,
            }
        )
    )

    service = KiwoomAccountStateSyncService(
        session=object(),
        account_sync_service=account_sync,
        pending_order_service=pending_sync,
    )
    result = asyncio.run(service.synchronize())

    assert result.account["account_number"] == "12345678"
    assert result.account["evaluation_profit_loss"] == "12000"
    assert result.account["realized_profit_loss"] is None
    assert result.account["realized_profit_loss_supported"] is False
    assert result.pending_orders["pending_order_count"] == 2
    assert "deposit_amount" in result.fields
    pending_sync.synchronize.assert_awaited_once_with("12345678")
