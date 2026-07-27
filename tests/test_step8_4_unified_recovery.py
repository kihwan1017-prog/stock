"""STEP 8-4 — 통합 Recovery Runtime 단위 테스트."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from stock_platform.broker.recovery_adapter import (
    AccountRecoveryContext,
    AdapterRecoveryResult,
)
from stock_platform.broker.recovery_adapters.kiwoom import (
    KiwoomRecoveryAdapter,
)
from stock_platform.broker.recovery_adapters.paper import (
    CryptoPaperRecoveryAdapter,
    StockPaperRecoveryAdapter,
)
from stock_platform.broker.recovery_adapters.upbit import (
    UpbitRecoveryAdapter,
)
from stock_platform.broker.recovery_lock import RecoveryLockError
from stock_platform.broker.recovery_models import (
    RecoveryComponent,
    RecoveryStatus,
)
from stock_platform.broker.recovery_runtime import BrokerRecoveryManager
from stock_platform.broker.recovery_service import BrokerRecoveryService


def test_adapter_selection() -> None:
    manager = BrokerRecoveryManager()
    kiwoom = manager._select_adapter(
        AccountRecoveryContext(
            user_id=1, broker_code="KIWOOM", market_type="STOCK"
        )
    )
    upbit = manager._select_adapter(
        AccountRecoveryContext(
            user_id=1, broker_code="UPBIT", market_type="CRYPTO"
        )
    )
    paper_s = manager._select_adapter(
        AccountRecoveryContext(
            user_id=1,
            broker_code="PAPER_STOCK",
            market_type="STOCK",
            paper_account_id=1,
        )
    )
    paper_c = manager._select_adapter(
        AccountRecoveryContext(
            user_id=1,
            broker_code="PAPER_CRYPTO",
            market_type="CRYPTO",
            paper_account_id=2,
        )
    )
    assert isinstance(kiwoom, KiwoomRecoveryAdapter)
    assert isinstance(upbit, UpbitRecoveryAdapter)
    assert isinstance(paper_s, StockPaperRecoveryAdapter)
    assert isinstance(paper_c, CryptoPaperRecoveryAdapter)
    assert (
        manager._select_adapter(
            AccountRecoveryContext(
                user_id=1, broker_code="UNKNOWN", market_type="STOCK"
            )
        )
        is None
    )


def test_scope_keys_isolated() -> None:
    a = AccountRecoveryContext(
        user_id=1,
        broker_code="UPBIT",
        market_type="CRYPTO",
        user_broker_account_id=10,
    )
    b = AccountRecoveryContext(
        user_id=2,
        broker_code="UPBIT",
        market_type="CRYPTO",
        user_broker_account_id=20,
    )
    assert a.scope_key != b.scope_key


def test_legacy_run_step_still_works() -> None:
    service = BrokerRecoveryService.__new__(BrokerRecoveryService)

    async def success():
        return {"ok": True}

    result = asyncio.run(
        service._run_step(RecoveryComponent.KIWOOM_ACCOUNT, success)
    )
    assert result.status == RecoveryStatus.SUCCESS


def test_account_failure_isolated() -> None:
    manager = BrokerRecoveryManager()
    failed = AdapterRecoveryResult(
        status="FAILED",
        broker_code="PAPER_STOCK",
        errors=["boom"],
        trading_should_remain_paused=True,
    ).finish()
    ok = AdapterRecoveryResult(
        status="SUCCESS", broker_code="PAPER_STOCK"
    ).finish()

    with patch.object(
        manager,
        "recover_account",
        new=AsyncMock(side_effect=[failed, ok]),
    ):
        with patch.object(
            manager,
            "discover_accounts",
            return_value=[
                AccountRecoveryContext(
                    user_id=1,
                    broker_code="PAPER_STOCK",
                    market_type="STOCK",
                    paper_account_id=1,
                ),
                AccountRecoveryContext(
                    user_id=2,
                    broker_code="PAPER_STOCK",
                    market_type="STOCK",
                    paper_account_id=2,
                ),
            ],
        ):
            with patch(
                "stock_platform.broker.recovery_runtime.get_session_factory"
            ) as sf:
                sf.return_value = MagicMock(return_value=MagicMock())
                result = asyncio.run(
                    manager.recover_all(trigger_type="TEST")
                )
    assert result["account_count"] == 2
    assert result["accounts"][0]["status"] == "FAILED"
    assert result["accounts"][1]["status"] == "SUCCESS"
    assert result["success"] is False


def test_duplicate_global_run_blocked() -> None:
    manager = BrokerRecoveryManager()
    manager._running = True
    with pytest.raises(ValueError, match="already running"):
        asyncio.run(manager.recover_all())


def test_adapter_result_to_dict() -> None:
    result = AdapterRecoveryResult(
        status="MANUAL_REVIEW",
        broker_code="UPBIT",
        conflicts_found=2,
        trading_should_remain_paused=True,
    ).finish()
    payload = result.to_dict()
    assert payload["conflicts_found"] == 2
    assert payload["trading_should_remain_paused"] is True
