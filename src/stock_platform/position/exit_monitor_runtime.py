"""Position Exit Monitor 런타임 — 주기적 폴링 실행 본체."""

from __future__ import annotations

import asyncio

import structlog

from stock_platform.common.settings import get_settings
from stock_platform.database.session import (
    get_session_factory,
)
from stock_platform.position.exit_monitor import (
    PositionExitAction,
    PositionExitMonitorService,
)
from stock_platform.position.exit_monitor_loader import (
    PositionExitMonitorLoader,
)


logger = structlog.get_logger(__name__)


class PositionExitMonitorManager:
    def __init__(self) -> None:
        self._last_actions: list[PositionExitAction] = []
        self._last_error: str | None = None
        self._scan_count = 0
        self._last_skipped: list[str] = []
        self._last_managed_symbols: list[str] = []
        self._last_evaluated_at: str | None = None
        self._symbol_eval: dict[str, dict] = {}

    async def check_now(
        self,
    ) -> list[PositionExitAction] | None:
        # 동기 ORM을 이벤트 루프 밖으로 이동 (API 블로킹 방지)
        return await asyncio.to_thread(self._check_now_sync)

    def _check_now_sync(
        self,
    ) -> list[PositionExitAction] | None:
        settings = get_settings()
        if not settings.position_exit_monitor_enabled:
            return None

        session = get_session_factory()()
        try:
            context = PositionExitMonitorLoader(
                session
            ).load()
            if context.skipped_symbols:
                logger.debug(
                    "position_exit_positions_skipped",
                    symbols=context.skipped_symbols,
                )

            monitor = PositionExitMonitorService(session)
            # STEP8-2: 청산도 Risk Engine 통과 (is_risk_reducing 으로 매수제한 우회)
            actions = monitor.evaluate_and_exit(
                context.positions,
                skip_risk_checks=False,
            )
            session.commit()
            self._last_actions = actions
            self._last_error = None
            self._scan_count += 1
            self._last_skipped = list(context.skipped_symbols or [])
            self._last_managed_symbols = [
                str(p.symbol).upper() for p in context.positions
            ]
            from datetime import datetime, timezone

            now_iso = datetime.now(timezone.utc).isoformat()
            self._last_evaluated_at = now_iso
            for pos in context.positions:
                sym = str(pos.symbol).upper()
                prev = self._symbol_eval.get(sym) or {}
                count = int(prev.get("evaluation_count") or 0) + 1
                act = next(
                    (
                        a
                        for a in actions
                        if str(a.symbol).upper() == sym
                    ),
                    None,
                )
                self._symbol_eval[sym] = {
                    "symbol": sym,
                    "managed": True,
                    "last_evaluated_at": now_iso,
                    "evaluation_count": count,
                    "decision": (
                        act.reason if act is not None else "HOLD"
                    ),
                    "reason": (
                        act.reason if act is not None else "HOLD"
                    ),
                    "current_price": str(pos.current_price),
                    "sl_trigger": str(pos.stop_loss_price),
                    "tp_trigger": str(pos.take_profit_price),
                    "highest": str(pos.highest_price),
                    "trailing_ratio": (
                        str(pos.trailing_stop_ratio)
                        if pos.trailing_stop_ratio is not None
                        else None
                    ),
                    "submitted": bool(
                        act.submitted if act is not None else False
                    ),
                }
            for skip in self._last_skipped:
                # stale_or_missing:LIVE:1380/KRW-GEOD
                if "stale_or_missing" in skip and "/" in skip:
                    sym = skip.rsplit("/", 1)[-1].upper()
                    prev = self._symbol_eval.get(sym) or {}
                    self._symbol_eval[sym] = {
                        **prev,
                        "symbol": sym,
                        "managed": False,
                        "decision": "EXIT_QUOTE_STALE",
                        "reason": "EXIT_QUOTE_STALE",
                        "skip": skip,
                        "last_skipped_at": now_iso,
                    }
            return actions
        except Exception as exc:
            session.rollback()
            self._last_error = str(exc)
            logger.exception(
                "position_exit_monitor_tick_failed",
                error=str(exc),
            )
            raise
        finally:
            session.close()

    def status(self) -> dict:
        settings = get_settings()
        st = {
            "enabled": (
                settings.position_exit_monitor_enabled
            ),
            "interval_seconds": (
                settings.position_exit_monitor_interval_seconds
            ),
            "live_upbit_enabled": bool(
                getattr(
                    settings,
                    "position_exit_monitor_live_upbit_enabled",
                    False,
                )
            ),
            "scan_count": self._scan_count,
            "last_error": self._last_error,
            "last_evaluated_at": self._last_evaluated_at,
            "last_managed_symbols": list(self._last_managed_symbols),
            "last_skipped": list(self._last_skipped),
            "symbol_telemetry": dict(self._symbol_eval),
            "last_exit_count": sum(
                1
                for item in self._last_actions
                if item.submitted
            ),
            "last_actions": [
                {
                    "symbol": item.symbol,
                    "reason": item.reason,
                    "submitted": item.submitted,
                    "order_id": item.order_id,
                }
                for item in self._last_actions
            ],
        }
        try:
            from stock_platform.position.exit_submission_suppression import (
                exit_suppression_status,
            )

            st.update(exit_suppression_status())
        except Exception:  # noqa: BLE001
            pass
        return st


position_exit_monitor_manager = (
    PositionExitMonitorManager()
)
