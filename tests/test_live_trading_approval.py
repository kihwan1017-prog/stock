from stock_platform.broker.live_approval import (
    LiveTradingApprovalService,
)


def test_approval_token_is_single_use() -> None:
    service = LiveTradingApprovalService(
        ttl_seconds=60
    )

    issued = service.issue()

    assert service.consume(
        approval_id=issued["approval_id"],
        approval_token=issued["approval_token"],
    )

    assert not service.consume(
        approval_id=issued["approval_id"],
        approval_token=issued["approval_token"],
    )


def test_invalid_token_is_rejected() -> None:
    service = LiveTradingApprovalService(
        ttl_seconds=60
    )

    issued = service.issue()

    assert not service.consume(
        approval_id=issued["approval_id"],
        approval_token="invalid",
    )
