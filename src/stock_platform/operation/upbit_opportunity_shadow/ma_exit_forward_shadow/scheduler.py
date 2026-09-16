"""SHADOW_TRACKING row — 완성 1m bar 기반 후속 평가 (no lookahead)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import select

from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory
from stock_platform.markets.models import CandleMinute, Instrument
from stock_platform.operation.upbit_opportunity_shadow.candle_path import (
    bars_from_rows,
    floor_minute,
)
from stock_platform.operation.upbit_opportunity_shadow.exit_policy_ab import (
    MA_LONG,
    MA_SHORT,
    _sma,
)
from stock_platform.operation.upbit_opportunity_shadow.ma_exit_forward_shadow.constants import (
    STATUS_SHADOW_TRACKING,
)
from stock_platform.operation.upbit_opportunity_shadow.ma_exit_forward_shadow.entities import (
    UpbitMaExitForwardShadowEntity,
)
from stock_platform.operation.upbit_opportunity_shadow.ma_exit_forward_shadow.service import (
    advance_shadow_tracking_bar,
    shadow_enabled,
)
from stock_platform.realtime.ma_exit_policy import MaExitThresholds, load_ma_exit_thresholds_from_settings

logger = structlog.get_logger(__name__)


def run_shadow_tracking_tick(settings: Any | None = None) -> dict[str, Any]:
    """주기적으로 SHADOW_TRACKING row에 새 1m bar 반영."""

    settings = settings or get_settings()
    if not shadow_enabled(settings):
        return {"ok": False, "reason": "DISABLED"}

    sl = Decimal(str(getattr(settings, "position_exit_stop_loss_ratio", 0.05)))
    tp = Decimal(str(getattr(settings, "position_exit_take_profit_ratio", 0.10)))
    trail = Decimal(
        str(getattr(settings, "position_exit_trailing_stop_ratio", 0.03) or 0.03)
    )
    th = load_ma_exit_thresholds_from_settings(settings)
    processed = 0
    completed = 0

    factory = get_session_factory()
    with factory() as session:
        rows = list(
            session.scalars(
                select(UpbitMaExitForwardShadowEntity).where(
                    UpbitMaExitForwardShadowEntity.status == STATUS_SHADOW_TRACKING,
                    UpbitMaExitForwardShadowEntity.shadow_exit_at.is_(None),
                )
            )
        )
        now = datetime.now(timezone.utc)
        for row in rows:
            state = dict(row.shadow_state_json or {})
            last_at_raw = state.get("last_bar_at")
            start = row.baseline_exit_at or row.entry_at
            stmt = (
                select(CandleMinute)
                .join(Instrument, Instrument.instrument_id == CandleMinute.instrument_id)
                .where(
                    Instrument.exchange_code == "UPBIT",
                    Instrument.symbol == row.symbol.upper(),
                    CandleMinute.timeframe == 1,
                    CandleMinute.candle_at >= start,
                    CandleMinute.candle_at <= now,
                )
                .order_by(CandleMinute.candle_at.asc())
            )
            bars = bars_from_rows(list(session.scalars(stmt)))
            if not bars:
                continue
            closes = [b.close for b in bars]
            last_idx = len(bars) - 1
            for idx, bar in enumerate(bars):
                at = bar.candle_at
                if at.tzinfo is None:
                    at = at.replace(tzinfo=timezone.utc)
                if last_at_raw and at.isoformat() <= str(last_at_raw):
                    continue
                if not bar.is_completed(now=now, timeframe_minutes=1):
                    continue
                short_ma = _sma(closes, idx, MA_SHORT)
                long_ma = _sma(closes, idx, MA_LONG)
                prev_s = _sma(closes, idx - 1, MA_SHORT) if idx > 0 else None
                prev_l = _sma(closes, idx - 1, MA_LONG) if idx > 0 else None
                res = advance_shadow_tracking_bar(
                    session,
                    row,
                    bar_close=bar.close,
                    bar_at=at,
                    short_ma=short_ma,
                    long_ma=long_ma,
                    prev_short=prev_s,
                    prev_long=prev_l,
                    thresholds=th,
                    stop_loss_ratio=sl,
                    take_profit_ratio=tp,
                    trail_distance_ratio=trail,
                )
                state["last_bar_at"] = at.isoformat()
                row.shadow_state_json = state
                processed += 1
                if row.shadow_exit_at is not None:
                    completed += 1
                    break
                if idx == last_idx:
                    break
        session.commit()

    return {"ok": True, "processed_bars": processed, "completed": completed}


class UpbitMaExitForwardShadowScheduler:
    """경량 interval job — scanner shadow evaluator 패턴."""

    JOB_ID = "upbit_ma_exit_forward_shadow_tracker"

    def __init__(self) -> None:
        self._configured = False

    def configure(self, scheduler: Any) -> None:
        if self._configured:
            return
        settings = get_settings()
        if not shadow_enabled(settings):
            self._configured = True
            return
        interval = int(
            getattr(settings, "upbit_ma_exit_forward_shadow_interval_seconds", 60) or 60
        )
        interval = max(30, min(300, interval))

        def _job() -> None:
            try:
                run_shadow_tracking_tick(settings)
            except Exception as exc:  # noqa: BLE001
                logger.warning("ma_exit_forward_shadow_scheduler_error", error=str(exc)[:200])

        scheduler.add_job(
            _job,
            "interval",
            seconds=interval,
            id=self.JOB_ID,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        self._configured = True
