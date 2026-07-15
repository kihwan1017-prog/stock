import asyncio

from stock_platform.broker.recovery_models import (
    RecoveryComponent,
    RecoveryStatus,
)
from stock_platform.broker.recovery_service import (
    BrokerRecoveryService,
)


def test_run_step_returns_success() -> None:
    service = BrokerRecoveryService.__new__(
        BrokerRecoveryService
    )

    async def success():
        return {"ok": True}

    result = asyncio.run(
        service._run_step(
            RecoveryComponent.KIWOOM_ACCOUNT,
            success,
        )
    )

    assert result.status == RecoveryStatus.SUCCESS
    assert result.detail == {"ok": True}


def test_run_step_returns_failed() -> None:
    service = BrokerRecoveryService.__new__(
        BrokerRecoveryService
    )

    async def failure():
        raise RuntimeError("failed")

    result = asyncio.run(
        service._run_step(
            RecoveryComponent
            .KIWOOM_PENDING_ORDERS,
            failure,
        )
    )

    assert result.status == RecoveryStatus.FAILED
    assert "failed" in result.message
