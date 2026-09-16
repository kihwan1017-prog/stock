# -*- coding: utf-8 -*-
"""Background tick — counterfactual + candle enrichment (parent shadow scheduler).

Observation-only. No broker calls. No trading mutations.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory
from stock_platform.operation.upbit_strategy_observability.constants import (
    CF_BATCH_INTERVAL_SECONDS,
    CF_BATCH_LIMIT_SYMBOLS,
    ENRICH_BATCH_LIMIT_EVENTS,
    EVENT_SIGNAL_BUY,
)

logger = logging.getLogger(__name__)

JOB_ID = "upbit_strategy_obs_counterfactual_batch"
LOOKAHEAD_ANALYTICS_ONLY = True
MUST_NOT_DRIVE_TRADING = True
NO_BROKER_API = True


def run_observability_batch_tick(
    *,
    limit_symbols: int = CF_BATCH_LIMIT_SYMBOLS,
    enrich_limit: int = ENRICH_BATCH_LIMIT_EVENTS,
) -> dict[str, Any]:
    """Mature CF forwards + enrich recent BUY signals from candle DB."""

    from stock_platform.operation.upbit_strategy_observability.counterfactual import (
        process_counterfactual_batch,
    )
    from stock_platform.operation.upbit_strategy_observability.enrichment import (
        build_chasing_metrics,
        build_regime_from_candles,
    )
    from stock_platform.operation.upbit_strategy_observability.entities import (
        UpbitStrategyObsEventEntity,
    )
    from sqlalchemy import select

    settings = get_settings()
    if not bool(getattr(settings, "upbit_strategy_obs_batch_enabled", True)):
        return {"ok": False, "reason": "DISABLED", "broker_api_calls": 0}

    factory = get_session_factory()
    with factory() as session:
        cf = process_counterfactual_batch(session, limit_symbols=limit_symbols)
        # Enrich SIGNAL_BUY payloads missing chasing block
        events = list(
            session.scalars(
                select(UpbitStrategyObsEventEntity)
                .where(UpbitStrategyObsEventEntity.event_type == EVENT_SIGNAL_BUY)
                .order_by(UpbitStrategyObsEventEntity.id.desc())
                .limit(int(enrich_limit))
            )
        )
        enriched = 0
        for ev in events:
            payload = dict(ev.payload_json or {})
            if payload.get("chasing_metrics") and payload.get("regime_snapshot"):
                continue
            if not ev.symbol:
                continue
            chasing = build_chasing_metrics(
                session,
                symbol=str(ev.symbol),
                at=ev.observed_at,
                price=None,
            )
            regime = build_regime_from_candles(session, at=ev.observed_at)
            payload["chasing_metrics"] = chasing
            payload["regime_snapshot"] = regime
            payload["enrichment_source"] = "candle_minute_batch"
            payload["observation_only"] = True
            payload["used_in_trading_decision"] = False
            # Strip accidental look-ahead if any
            from stock_platform.operation.upbit_strategy_observability.leakage import (
                assert_no_lookahead_in_trading_payload,
            )

            try:
                # chasing/regime are past-looking; ensure no fwd_* keys
                assert_no_lookahead_in_trading_payload(
                    {
                        k: v
                        for k, v in payload.items()
                        if k not in {"chasing_metrics", "regime_snapshot"}
                    }
                )
            except AssertionError:
                continue
            ev.payload_json = payload
            enriched += 1
        session.commit()
        return {
            "ok": True,
            **cf,
            "signals_enriched": enriched,
            "broker_api_calls": 0,
            "ran_at": datetime.now(timezone.utc).isoformat(),
        }


class UpbitStrategyObsCounterfactualScheduler:
    """Reuse parent AsyncIOScheduler — no new heavy process scheduler."""

    def configure(self, scheduler: Any) -> None:
        settings = get_settings()
        if not bool(getattr(settings, "upbit_strategy_obs_batch_enabled", True)):
            return
        interval = int(
            getattr(
                settings,
                "upbit_strategy_obs_batch_interval_seconds",
                CF_BATCH_INTERVAL_SECONDS,
            )
            or CF_BATCH_INTERVAL_SECONDS
        )
        interval = max(30, min(300, interval))
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
            logger.exception("upbit_strategy_obs_batch_scheduler_configure_failed")

    def tick(self) -> None:
        try:
            run_observability_batch_tick()
        except Exception:  # noqa: BLE001
            logger.exception("upbit_strategy_obs_batch_tick_failed")
