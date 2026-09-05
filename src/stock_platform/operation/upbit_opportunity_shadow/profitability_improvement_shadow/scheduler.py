"""Scheduler — candidate outcomes + exit V4 + MA-DC + reentry price paths (research only)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory
from stock_platform.operation.upbit_opportunity_shadow.profitability_improvement_shadow.constants import (
    STATUS_ACTIVE,
)
from stock_platform.operation.upbit_opportunity_shadow.profitability_improvement_shadow.entities import (
    UpbitProfitabilityExitEnrollmentEntity,
    UpbitProfitabilityMaDcEventEntity,
)

logger = logging.getLogger(__name__)
JOB_ID = "upbit_profitability_improvement_shadow"


def run_profitability_lab_tick() -> dict[str, Any]:
    from stock_platform.operation.upbit_opportunity_shadow.profitability_improvement_shadow.service import (
        fill_candidate_outcomes,
        fill_pending_reentry_price_paths,
        observe_exit_price,
        observe_ma_dc_price,
        shadow_enabled,
    )
    from stock_platform.position.exit_monitor_live import resolve_upbit_live_price

    if not shadow_enabled():
        return {"ok": False, "reason": "DISABLED"}

    observed = 0
    madc_observed = 0
    filled = 0
    price_path_filled = 0
    with get_session_factory() as session:
        r = fill_candidate_outcomes(session, limit=40)
        filled = int(r.get("filled") or 0)
        rows = list(
            session.scalars(
                select(UpbitProfitabilityExitEnrollmentEntity).where(
                    UpbitProfitabilityExitEnrollmentEntity.status == STATUS_ACTIVE
                )
            )
        )
        for row in rows:
            px = resolve_upbit_live_price(
                session, symbol=str(row.symbol), stale_seconds=30.0
            )
            if px is None or px <= Decimal("0"):
                continue
            observe_exit_price(
                session,
                binding_id=int(row.binding_id),
                price=px,
                observed_at=datetime.now(timezone.utc),
            )
            observed += 1

        # Lab D forward ticks (REAL SELL unchanged)
        madc_rows = list(
            session.scalars(
                select(UpbitProfitabilityMaDcEventEntity).where(
                    UpbitProfitabilityMaDcEventEntity.status == STATUS_ACTIVE
                )
            )
        )
        for row in madc_rows:
            px = resolve_upbit_live_price(
                session, symbol=str(row.symbol), stale_seconds=30.0
            )
            if px is None or px <= Decimal("0"):
                continue
            observe_ma_dc_price(
                session,
                event_id=int(row.event_id),
                price=px,
                observed_at=datetime.now(timezone.utc),
            )
            madc_observed += 1

        pp = fill_pending_reentry_price_paths(session, limit=40)
        price_path_filled = int(pp.get("filled") or 0)
        session.commit()
    return {
        "ok": True,
        "candidate_filled": filled,
        "exit_observed": observed,
        "ma_dc_observed": madc_observed,
        "reentry_price_path_filled": price_path_filled,
    }


class UpbitProfitabilityImprovementShadowScheduler:
    def configure(self, scheduler: Any) -> None:
        settings = get_settings()
        if not bool(
            getattr(settings, "upbit_profitability_improvement_shadow_enabled", True)
        ):
            return
        interval = float(
            getattr(
                settings,
                "upbit_profitability_improvement_shadow_interval_seconds",
                60.0,
            )
        )
        interval = max(30.0, min(300.0, interval))
        try:
            scheduler.add_job(
                self.tick,
                "interval",
                seconds=interval,
                id=JOB_ID,
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )
        except Exception:  # noqa: BLE001
            logger.exception("profitability_improvement_shadow_scheduler_configure_failed")

    def tick(self) -> None:
        try:
            run_profitability_lab_tick()
        except Exception:  # noqa: BLE001
            logger.exception("profitability_improvement_shadow_scheduler_error")
