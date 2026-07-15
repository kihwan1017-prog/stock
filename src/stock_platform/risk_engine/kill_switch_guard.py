from __future__ import annotations

from stock_platform.risk_engine.kill_switch_service import (
    KillSwitchService,
)


class PersistentKillSwitchGuard:
    """DB에 저장된 GLOBAL Kill Switch 상태를 검사한다."""

    def __init__(self, session) -> None:
        self._service = KillSwitchService(session)

    def require_order_allowed(
        self,
        *,
        side: str,
        allow_sell: bool = True,
    ) -> None:
        if not self._service.is_active():
            return

        if side.upper() == "SELL" and allow_sell:
            return

        raise PermissionError(
            "Global kill switch is active"
        )
