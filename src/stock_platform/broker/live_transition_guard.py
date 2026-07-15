from __future__ import annotations

from sqlalchemy.orm import Session

from stock_platform.broker.live_transition_service import (
    LiveTradingTransitionService,
)


class LiveTradingTransitionGuard:
    """실거래 Adapter 사용 전 활성 승인 기록을 확인한다."""

    def __init__(self, session: Session) -> None:
        self._service = LiveTradingTransitionService(
            session
        )

    def require_active(self):
        entity = self._service.get_active()

        if entity is None:
            raise PermissionError(
                "No active live trading transition approval"
            )

        return entity
