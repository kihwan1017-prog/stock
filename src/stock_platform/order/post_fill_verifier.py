"""STEP 8-8 — 체결 후 Position/Cash 검증."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from stock_platform.order.live_safety_audit import (
    CASH_MISMATCH,
    POSITION_MISMATCH,
    emit_live_order_telegram,
    emit_live_safety_audit,
)


@dataclass(frozen=True, slots=True)
class PostFillVerifyResult:
    ok: bool
    reason_code: str
    detail: dict[str, Any]


class PostFillBalanceVerifier:
    """Broker 잔고/포지션과 DB 비교. 불일치 시 Kill Switch."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def verify(
        self,
        *,
        user_broker_account_id: int,
        user_id: int | None,
        broker_code: str,
        broker_positions: list[dict[str, Any]] | None,
        broker_cash: Decimal | None,
        db_positions: list[dict[str, Any]] | None,
        db_cash: Decimal | None,
        tolerance: Decimal = Decimal("0.01"),
        actor: str = "POST_FILL_VERIFY",
        activate_kill_on_mismatch: bool = True,
    ) -> PostFillVerifyResult:
        detail: dict[str, Any] = {
            "user_broker_account_id": int(user_broker_account_id),
            "broker_code": broker_code.upper(),
        }

        if broker_positions is not None and db_positions is not None:
            broker_map = {
                str(p.get("symbol", "")).upper(): Decimal(
                    str(p.get("quantity") or 0)
                )
                for p in broker_positions
            }
            db_map = {
                str(p.get("symbol", "")).upper(): Decimal(
                    str(p.get("quantity") or 0)
                )
                for p in db_positions
            }
            symbols = set(broker_map) | set(db_map)
            for sym in symbols:
                bq = broker_map.get(sym, Decimal("0"))
                dq = db_map.get(sym, Decimal("0"))
                if abs(bq - dq) > tolerance:
                    detail.update(
                        {
                            "symbol": sym,
                            "broker_qty": str(bq),
                            "db_qty": str(dq),
                        }
                    )
                    self._on_mismatch(
                        event_type=POSITION_MISMATCH,
                        user_id=user_id,
                        account_id=user_broker_account_id,
                        detail=detail,
                        actor=actor,
                        activate_kill=activate_kill_on_mismatch,
                    )
                    return PostFillVerifyResult(
                        ok=False,
                        reason_code="POSITION_MISMATCH",
                        detail=detail,
                    )

        if broker_cash is not None and db_cash is not None:
            if abs(Decimal(str(broker_cash)) - Decimal(str(db_cash))) > tolerance:
                detail.update(
                    {
                        "broker_cash": str(broker_cash),
                        "db_cash": str(db_cash),
                    }
                )
                self._on_mismatch(
                    event_type=CASH_MISMATCH,
                    user_id=user_id,
                    account_id=user_broker_account_id,
                    detail=detail,
                    actor=actor,
                    activate_kill=activate_kill_on_mismatch,
                )
                return PostFillVerifyResult(
                    ok=False,
                    reason_code="CASH_MISMATCH",
                    detail=detail,
                )

        return PostFillVerifyResult(
            ok=True, reason_code="VERIFY_OK", detail=detail
        )

    def _on_mismatch(
        self,
        *,
        event_type: str,
        user_id: int | None,
        account_id: int,
        detail: dict[str, Any],
        actor: str,
        activate_kill: bool,
    ) -> None:
        emit_live_safety_audit(
            self._session,
            event_type=event_type,
            actor=actor,
            run_id=None,
            user_id=user_id,
            account_id=account_id,
            strategy_id=None,
            detail=detail,
            commit=False,
        )
        emit_live_order_telegram(
            event_type=event_type,
            title=f"LIVE {event_type}",
            message=f"{event_type} on UBA {account_id}",
            detail=detail,
        )
        if activate_kill:
            try:
                from stock_platform.risk_engine.kill_switch_service import (
                    KillSwitchService,
                )

                KillSwitchService(self._session).activate(
                    actor=actor,
                    reason=event_type,
                )
            except Exception:  # noqa: BLE001
                pass
            try:
                from stock_platform.trading.live_arm_service import (
                    LiveArmService,
                )

                LiveArmService(self._session).disarm(
                    account_id,
                    actor=actor,
                    reason=event_type,
                    turn_live_off=True,
                )
            except Exception:  # noqa: BLE001
                pass
            self._pause_scheduler(actor=actor, reason=event_type)

    def _pause_scheduler(self, *, actor: str, reason: str) -> None:
        try:
            from stock_platform.common.settings import get_settings

            settings = get_settings()
            if hasattr(settings, "scheduler_enabled"):
                # 런타임 플래그 — 영속 설정 덮어쓰기 대신 감사만
                pass
            emit_live_safety_audit(
                self._session,
                event_type="SCHEDULER_PAUSE",
                actor=actor,
                run_id=None,
                user_id=None,
                account_id=None,
                strategy_id=None,
                detail={"reason": reason},
                commit=False,
            )
            emit_live_order_telegram(
                event_type="SCHEDULER_PAUSE",
                title="Scheduler Pause",
                message=f"Scheduler pause requested ({reason})",
                detail={"reason": reason, "actor": actor},
            )
            try:
                import asyncio

                from stock_platform.strategy_deployment.runtime_manager import (
                    dynamic_strategy_runtime_manager,
                )

                coro = dynamic_strategy_runtime_manager.pause_all(
                    reason=reason
                )
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(coro)
                except RuntimeError:
                    asyncio.run(coro)
            except Exception:  # noqa: BLE001
                pass
        except Exception:  # noqa: BLE001
            pass
