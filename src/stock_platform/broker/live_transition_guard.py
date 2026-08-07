from __future__ import annotations

from sqlalchemy.orm import Session

from stock_platform.broker.live_transition_service import (
    LiveTradingTransitionService,
)


class LiveTradingTransitionGuard:
    """실거래 Adapter/Worker 사용 전 활성 승인 기록을 확인한다."""

    def __init__(self, session: Session) -> None:
        self._service = LiveTradingTransitionService(session)

    def require_active(
        self,
        *,
        broker_code: str | None = None,
        user_broker_account_id: int | None = None,
    ):
        entity = self._service.get_active(
            broker_code=broker_code,
            user_broker_account_id=user_broker_account_id,
        )

        if entity is None:
            raise PermissionError(
                "No active live trading transition approval"
            )

        # 이중 확인 — get_active 필터와 동일 규칙
        if broker_code is not None or user_broker_account_id is not None:
            if not LiveTradingTransitionService.transition_matches_dispatch(
                entity,
                broker_code=broker_code,
                user_broker_account_id=user_broker_account_id,
            ):
                raise PermissionError(
                    "Live trading transition scope mismatch "
                    f"(broker={broker_code} uba={user_broker_account_id})"
                )

        return entity
