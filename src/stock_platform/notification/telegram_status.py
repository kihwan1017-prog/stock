"""Telegram 운영 명령용 상태 집계 — 자동매매 로직 변경 없음."""

from __future__ import annotations

import os
import platform
import shutil
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stock_platform.common.settings import get_settings
from stock_platform.markets.repository import (
    PriceDailyRepository,
)
from stock_platform.markets.service import (
    InstrumentNotFoundError,
    PriceDailyService,
)
from stock_platform.operation.health_service import (
    SystemHealthService,
)
from stock_platform.order.entities import TradingOrderEntity
from stock_platform.order.models import OrderStatus
from stock_platform.risk_engine.kill_switch_service import (
    KillSwitchService,
)
from stock_platform.risk_engine.runtime import (
    realtime_risk_policy,
)
from stock_platform.trading.account_models import (
    PaperAccount,
    PaperPosition,
)


ZERO = Decimal("0")


class TelegramOpsStatusService:
    """/status /health /orders /positions 응답 텍스트 생성."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._settings = get_settings()
        self._prices = PriceDailyService(
            PriceDailyRepository(session)
        )

    async def build_status_text(self) -> str:
        kill = KillSwitchService(self._session).get_state()
        health = await SystemHealthService().build()
        components = health.get("components") or {}
        db = components.get("database") or {}
        broker = components.get("kiwoom_rest") or {}
        scheduler = components.get("scheduler") or {}

        open_orders = self._count_open_orders()
        open_positions = self._count_open_positions()
        pnl = self._today_pnl_summary()
        jobs = self._running_jobs_hint()

        lines = [
            "<b>📊 System Status</b>",
            f"Server: {self._settings.app_name}",
            f"Version: {getattr(self._settings, 'app_version', 'dev')}",
            f"Env: {self._settings.app_env}",
            f"DB: {db.get('status', 'UNKNOWN')}",
            (
                f"Broker: {broker.get('status', 'UNKNOWN')}"
                f" (mock={self._settings.kiwoom_use_mock})"
            ),
            f"Scheduler: {scheduler.get('status', 'UNKNOWN')}",
            f"Running Jobs: {jobs}",
            f"Kill Switch: {kill.status.value}",
            (
                "Daily Loss Limit: "
                f"{realtime_risk_policy.max_daily_loss}"
            ),
            f"Today's PnL: {pnl}",
            f"Open Orders: {open_orders}",
            f"Open Positions: {open_positions}",
        ]
        return "\n".join(lines)

    async def build_health_text(self) -> str:
        health = await SystemHealthService().build()
        components = health.get("components") or {}
        resources = self._resource_snapshot()

        lines = [
            "<b>🩺 Health</b>",
            f"Overall: {health.get('status', 'UNKNOWN')}",
            f"CPU: {resources['cpu']}",
            f"Memory: {resources['memory']}",
            f"Disk: {resources['disk']}",
            (
                "DB: "
                f"{(components.get('database') or {}).get('status', 'UNKNOWN')}"
            ),
            (
                "Broker: "
                f"{(components.get('kiwoom_rest') or {}).get('status', 'UNKNOWN')}"
            ),
            (
                "Ollama: "
                f"{(components.get('ollama') or {}).get('status', 'UNKNOWN')}"
            ),
            (
                "Scheduler: "
                f"{(components.get('scheduler') or {}).get('status', 'UNKNOWN')}"
            ),
        ]
        return "\n".join(lines)

    def build_orders_text(self) -> str:
        today_start = datetime.combine(
            date.today(),
            time.min,
            tzinfo=timezone.utc,
        )
        rows = list(
            self._session.scalars(
                select(TradingOrderEntity).where(
                    TradingOrderEntity.created_at
                    >= today_start
                )
            )
        )
        filled = 0
        open_count = 0
        cancelled = 0
        rejected = 0
        for row in rows:
            status = (row.status_code or "").upper()
            if status == OrderStatus.FILLED.value:
                filled += 1
            elif status == OrderStatus.CANCELLED.value:
                cancelled += 1
            elif status in {
                OrderStatus.REJECTED.value,
                OrderStatus.FAILED.value,
            }:
                rejected += 1
            elif status not in {
                OrderStatus.FILLED.value,
                OrderStatus.CANCELLED.value,
                OrderStatus.REJECTED.value,
                OrderStatus.FAILED.value,
            }:
                open_count += 1

        lines = [
            "<b>🧾 Orders (today)</b>",
            f"Total: {len(rows)}",
            f"Filled: {filled}",
            f"Open / Working: {open_count}",
            f"Cancelled: {cancelled}",
            f"Rejected/Failed: {rejected}",
        ]
        return "\n".join(lines)

    def build_positions_text(self) -> str:
        positions = list(
            self._session.scalars(
                select(PaperPosition).where(
                    PaperPosition.quantity > ZERO
                )
            )
        )
        total_cost = ZERO
        total_value = ZERO
        lines = [
            "<b>📦 Positions</b>",
            f"Count: {len(positions)}",
        ]
        for pos in positions[:20]:
            price = self._current_price(
                pos.exchange_code,
                pos.symbol,
                pos.average_entry_price,
            )
            cost = pos.quantity * pos.average_entry_price
            value = pos.quantity * price
            pnl = value - cost
            total_cost += cost
            total_value += value
            lines.append(
                f"- {pos.symbol} qty={pos.quantity} "
                f"pnl={pnl.quantize(Decimal('0.01'))}"
            )

        unrealized = total_value - total_cost
        roi = (
            (unrealized / total_cost * Decimal("100"))
            if total_cost > ZERO
            else ZERO
        )
        lines.extend(
            [
                f"Unrealized PnL: {unrealized.quantize(Decimal('0.01'))}",
                f"Total Return %: {roi.quantize(Decimal('0.01'))}",
            ]
        )
        return "\n".join(lines)

    def build_system_text(self) -> str:
        settings = self._settings
        return "\n".join(
            [
                "<b>🖥 System</b>",
                f"App: {settings.app_name}",
                f"Env: {settings.app_env}",
                f"Timezone: {settings.app_timezone}",
                f"Platform: {platform.platform()}",
                f"PID: {os.getpid()}",
                (
                    "Telegram enabled: "
                    f"{settings.telegram_enabled}"
                ),
                (
                    "Telegram ops: "
                    f"{getattr(settings, 'telegram_ops_enabled', False)}"
                ),
            ]
        )

    def build_help_text(self) -> str:
        return "\n".join(
            [
                "<b>🤖 Commands</b>",
                "/status — 시스템 상태",
                "/system — 프로세스·환경",
                "/health — 헬스·리소스",
                "/orders — 오늘 주문 요약",
                "/positions — 보유 포지션",
                "/kill — Kill Switch 활성화",
                "/resume — Kill Switch 해제",
                "/help — 이 도움말",
            ]
        )

    def _count_open_orders(self) -> int:
        terminal = {
            OrderStatus.FILLED.value,
            OrderStatus.CANCELLED.value,
            OrderStatus.REJECTED.value,
            OrderStatus.FAILED.value,
        }
        rows = list(
            self._session.scalars(select(TradingOrderEntity))
        )
        return sum(
            1
            for row in rows
            if (row.status_code or "").upper() not in terminal
        )

    def _count_open_positions(self) -> int:
        return int(
            self._session.scalar(
                select(func.count()).select_from(
                    PaperPosition
                ).where(PaperPosition.quantity > ZERO)
            )
            or 0
        )

    def _today_pnl_summary(self) -> str:
        accounts = list(
            self._session.scalars(select(PaperAccount))
        )
        if not accounts:
            return "0 (no paper account)"
        realized = sum(
            (
                Decimal(account.realized_profit_loss)
                for account in accounts
            ),
            ZERO,
        )
        return str(realized.quantize(Decimal("0.01")))

    def _running_jobs_hint(self) -> str:
        from stock_platform.position.exit_monitor_runtime import (
            position_exit_monitor_manager,
        )
        from stock_platform.risk_engine.daily_loss_runtime import (
            daily_loss_monitor_manager,
        )

        exit_status = position_exit_monitor_manager.status()
        daily_status = daily_loss_monitor_manager.status()
        parts = []
        if exit_status.get("enabled"):
            parts.append("exit_monitor")
        if daily_status.get("loss_limit"):
            parts.append("daily_loss")
        return ", ".join(parts) if parts else "none"

    def _current_price(
        self,
        exchange_code: str,
        symbol: str,
        fallback: Decimal,
    ) -> Decimal:
        try:
            latest = self._prices.get_latest(
                exchange_code,
                symbol,
            )
        except (InstrumentNotFoundError, Exception):
            return fallback
        if latest is None:
            return fallback
        price = Decimal(str(latest.close_price))
        return price if price > ZERO else fallback

    @staticmethod
    def _resource_snapshot() -> dict[str, str]:
        disk = shutil.disk_usage(".")
        disk_pct = (
            (disk.used / disk.total) * 100
            if disk.total
            else 0.0
        )
        memory = "N/A"
        cpu = "N/A"
        try:
            import psutil  # type: ignore

            memory = (
                f"{psutil.virtual_memory().percent:.1f}%"
            )
            cpu = f"{psutil.cpu_percent(interval=0.0):.1f}%"
        except Exception:
            # stdlib fallback
            try:
                load = os.getloadavg()  # type: ignore[attr-defined]
                cpu = f"load={load[0]:.2f}"
            except (AttributeError, OSError):
                cpu = "unavailable"
            memory = "unavailable"

        return {
            "cpu": cpu,
            "memory": memory,
            "disk": f"{disk_pct:.1f}% used",
        }
