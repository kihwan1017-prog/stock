from __future__ import annotations

from stock_platform.risk_engine.kill_switch_service import (
    KillSwitchService,
)


class KillSwitchUnavailableError(PermissionError):
    """Kill Switch 조회 실패 — fail-closed로 신규 주문 차단."""


class PersistentKillSwitchGuard:
    """DB에 저장된 GLOBAL Kill Switch 상태를 검사한다.

    exchange_code가 주어지고 활성 스코프가 설정돼 있으면
    해당 거래소만 차단할 수 있다 (미설정 시 전역).

    DB/서비스 예외 시 BUY는 차단한다 (fail-closed).
    SELL은 allow_sell=True면 예외 시에도 허용(리스크 축소).
    """

    def __init__(self, session) -> None:
        self._service = KillSwitchService(session)

    def require_order_allowed(
        self,
        *,
        side: str,
        allow_sell: bool = True,
        exchange_code: str | None = None,
        user_broker_account_id: int | None = None,
        paper_account_id: int | None = None,
    ) -> None:
        from stock_platform.trading.account_identity import (
            paper_kill_switch_scope,
            uba_kill_switch_scope,
        )

        try:
            scopes = [KillSwitchService.GLOBAL_SCOPE]
            if user_broker_account_id is not None:
                scopes.append(
                    uba_kill_switch_scope(int(user_broker_account_id))
                )
            if paper_account_id is not None:
                scopes.append(
                    paper_kill_switch_scope(int(paper_account_id))
                )
            active = self._service.is_active_for_scopes(scopes)
        except Exception as exc:
            if side.upper() == "SELL" and allow_sell:
                return
            raise KillSwitchUnavailableError(
                "Kill switch check failed (fail-closed)"
            ) from exc

        if not active:
            return

        if side.upper() == "SELL" and allow_sell:
            return

        try:
            # GLOBAL 활성 시에만 거래소 스코프 파싱 (레거시 호환)
            exchange_scope = (
                self._service.active_exchange_scope()
                if self._service.is_active()
                else set()
            )
        except Exception as exc:
            raise KillSwitchUnavailableError(
                "Kill switch check failed (fail-closed)"
            ) from exc

        # 거래소 스코프: GLOBAL+EXCHANGES 매칭될 때만 차단, 미매칭이면 통과
        if (
            self._service.is_active()
            and exchange_scope
            and exchange_code
        ):
            if exchange_code.upper() not in exchange_scope:
                # UBA/PAPER scope 가 활성이면 여전히 차단
                uba_paper_active = False
                if user_broker_account_id is not None:
                    uba_paper_active = self._service.is_active_for_scopes(
                        [uba_kill_switch_scope(int(user_broker_account_id))]
                    )
                if paper_account_id is not None and not uba_paper_active:
                    uba_paper_active = self._service.is_active_for_scopes(
                        [paper_kill_switch_scope(int(paper_account_id))]
                    )
                if not uba_paper_active:
                    return

        raise PermissionError(
            "Kill switch is active for account scope"
            if (user_broker_account_id or paper_account_id)
            else (
                "Global kill switch is active"
                if not exchange_scope
                else f"Kill switch active for {sorted(exchange_scope)}"
            )
        )
