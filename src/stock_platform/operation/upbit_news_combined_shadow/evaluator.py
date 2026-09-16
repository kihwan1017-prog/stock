"""STEP N6 — EXPERIMENT outcome evaluator (CONTROL Shadow write 금지).

DB candle only (allow_sync=False). Reuses candle_path helpers.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.common.logger import logger
from stock_platform.operation.upbit_news_combined_shadow.entities import (
    UpbitNewsCombinedShadowEntity,
)
from stock_platform.operation.upbit_news_combined_shadow.policy import (
    EVAL_ACTIVE,
    EVAL_COMPLETED,
    EVAL_FAILED,
    EVAL_INCOMPLETE,
    EVAL_PENDING,
)
from stock_platform.operation.upbit_opportunity_shadow.candle_loader import (
    list_minute_bars_db,
)
from stock_platform.operation.upbit_opportunity_shadow.candle_path import (
    DEFAULT_MAX_PRIOR_LAG_SECONDS,
    as_utc,
    compute_mfe_mae,
    observe_windows,
)
from stock_platform.operation.upbit_opportunity_shadow.constants import (
    EVALUATION_WINDOWS_MINUTES,
)


class UpbitNewsCombinedShadowEvaluator:
    """EXPERIMENT table만 갱신. CONTROL Shadow mutation 없음."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def evaluate_pending(self, *, limit: int = 50) -> dict[str, Any]:
        rows = list(
            self._session.scalars(
                select(UpbitNewsCombinedShadowEntity)
                .where(
                    UpbitNewsCombinedShadowEntity.evaluation_status.in_(
                        [EVAL_PENDING, EVAL_ACTIVE, EVAL_INCOMPLETE]
                    )
                )
                .order_by(UpbitNewsCombinedShadowEntity.created_at.asc())
                .limit(max(1, min(int(limit), 100)))
            )
        )
        updated = completed = failed = 0
        now = datetime.now(timezone.utc)
        for row in rows:
            try:
                self._evaluate_row(row, now=now)
                updated += 1
                if row.evaluation_status == EVAL_COMPLETED:
                    completed += 1
            except Exception as exc:  # noqa: BLE001
                failed += 1
                row.evaluation_status = EVAL_FAILED
                row.evaluation_detail = {
                    **(row.evaluation_detail or {}),
                    "error": f"{type(exc).__name__}: {exc}"[:500],
                }
                logger.warning(
                    "news_combined_shadow_eval_failed",
                    experiment_id=row.experiment_id,
                    error=str(exc)[:200],
                )
        self._session.commit()
        return {
            "scanned": len(rows),
            "updated": updated,
            "completed": completed,
            "failed": failed,
            "control_mutated": False,
            "llm_calls": 0,
        }

    def _evaluate_row(
        self,
        row: UpbitNewsCombinedShadowEntity,
        *,
        now: datetime,
    ) -> None:
        # 이미 CONTROL copy로 COMPLETED면 유지
        if (
            row.evaluation_status == EVAL_COMPLETED
            and row.return_60m_pct is not None
        ):
            return

        detected = as_utc(row.candidate_detected_at)
        entry = Decimal(str(row.entry_price))
        end = detected + timedelta(minutes=60)
        bars = list_minute_bars_db(
            self._session,
            symbol=row.symbol,
            start_at=detected - timedelta(minutes=2),
            end_at=min(end + timedelta(minutes=2), now),
        )
        observations = observe_windows(
            bars,
            detected_at=detected,
            entry=entry,
            now=now,
            windows_minutes=EVALUATION_WINDOWS_MINUTES,
            max_prior_lag_seconds=DEFAULT_MAX_PRIOR_LAG_SECONDS,
            absent_by_target={},
            source_unavailable_by_target={},
            candle_source="market.candle_minute",
        )
        windows: dict[str, Any] = {}
        ok_n = 0
        for obs in observations:
            windows[str(obs.minutes)] = {
                "status": obs.status,
                "price": float(obs.price) if obs.price is not None else None,
                "return_pct": (
                    float(obs.return_pct) if obs.return_pct is not None else None
                ),
                "selection_type": obs.selection_type,
                "final": obs.final,
            }
            if obs.status == "OK" and obs.return_pct is not None:
                ok_n += 1
                setattr(
                    row,
                    f"return_{obs.minutes}m_pct",
                    float(obs.return_pct),
                )

        mfe, mae, mfe_detail = compute_mfe_mae(
            bars,
            entry=entry,
            start_at=detected,
            end_at=end,
            now=now,
        )
        row.mfe_pct = float(mfe) if mfe is not None else None
        row.mae_pct = float(mae) if mae is not None else None
        row.evaluation_detail = {
            "source": "N6_DB_CANDLE_EVAL",
            "windows": windows,
            "mfe_mae_detail": mfe_detail,
            "candle_count": len(bars),
            "missing_candle_policy": "EXACT_TARGET_CANDLE|LAST_KNOWN_BEFORE_TARGET",
            "max_prior_lag_seconds": DEFAULT_MAX_PRIOR_LAG_SECONDS,
            "control_write": False,
        }

        if row.return_60m_pct is not None and ok_n >= 4:
            row.evaluation_status = EVAL_COMPLETED
            row.completed_at = now
        elif ok_n > 0:
            row.evaluation_status = EVAL_ACTIVE
        elif now < end:
            row.evaluation_status = EVAL_PENDING
        else:
            row.evaluation_status = EVAL_INCOMPLETE
