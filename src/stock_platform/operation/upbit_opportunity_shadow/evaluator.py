"""Shadow 평가 — minute candle historical backfill (AI/주문 없음)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.common.settings import get_settings
from stock_platform.operation.upbit_opportunity_shadow.candle_loader import (
    ensure_shadow_minute_bars,
)
from stock_platform.operation.upbit_opportunity_shadow.candle_path import (
    as_utc,
    compute_mfe_mae,
    compute_tp_sl,
    observe_windows,
)
from stock_platform.operation.upbit_opportunity_shadow.constants import (
    EVALUATION_WINDOWS_MINUTES,
    SHADOW_STATUS_ACTIVE,
    SHADOW_STATUS_COMPLETED,
)
from stock_platform.operation.upbit_opportunity_shadow.entities import (
    UpbitOpportunityShadowEntity,
)
from stock_platform.operation.upbit_opportunity_shadow.notify import (
    publish_shadow_result,
)
from stock_platform.operation.upbit_opportunity_shadow.service import (
    UpbitOpportunityShadowService,
)

logger = structlog.get_logger(__name__)


def _dec(value: Any) -> Decimal:
    return Decimal(str(value))


def _round6(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 6)


class UpbitOpportunityShadowEvaluator:
    """ACTIVE Shadow를 historical 1m candle로 평가. 늦은 실행도 backfill."""

    def __init__(
        self,
        session: Session,
        *,
        now: datetime | None = None,
        allow_sync: bool = True,
    ) -> None:
        self._session = session
        self._now = now or datetime.now(timezone.utc)
        self._allow_sync = allow_sync

    async def evaluate_pending(self, *, notify: bool = True) -> dict[str, Any]:
        rows = list(
            self._session.scalars(
                select(UpbitOpportunityShadowEntity).where(
                    UpbitOpportunityShadowEntity.status == SHADOW_STATUS_ACTIVE,
                    UpbitOpportunityShadowEntity.deleted_at.is_(None),
                )
            )
        )
        if not rows:
            return {
                "evaluated": 0,
                "completed": 0,
                "orders_created": 0,
                "shadows": [],
                "mode": "historical_candles",
            }

        evaluated = 0
        completed_rows: list[UpbitOpportunityShadowEntity] = []
        for row in rows:
            result = await self._apply_timeseries(row, persist=True)
            if result.get("changed"):
                evaluated += 1
            if result.get("just_completed"):
                completed_rows.append(row)

        self._session.commit()

        if notify:
            for row in completed_rows:
                try:
                    publish_shadow_result(
                        UpbitOpportunityShadowService.to_public(row)
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "shadow_result_notify_failed",
                        shadow_id=row.shadow_id,
                        error=type(exc).__name__,
                    )

        return {
            "evaluated": evaluated,
            "completed": len(completed_rows),
            "orders_created": 0,
            "mode": "historical_candles",
            "shadows": [
                UpbitOpportunityShadowService.to_public(r) for r in rows
            ],
        }

    async def dry_recompute(
        self,
        shadow_id: int,
    ) -> dict[str, Any]:
        """COMPLETED 포함 — DB UPDATE 없이 historical 재계산만."""

        row = self._session.get(UpbitOpportunityShadowEntity, shadow_id)
        if row is None or row.deleted_at is not None:
            return {
                "ok": False,
                "error": "NOT_FOUND",
                "orders_created": 0,
            }
        computed = await self._compute_payload(row)
        stored = UpbitOpportunityShadowService.to_public(row)
        return {
            "ok": True,
            "shadow_id": int(shadow_id),
            "symbol": row.symbol,
            "persist": False,
            "orders_created": 0,
            "paper_shadow": True,
            "stored": stored,
            "recomputed": computed,
            "diff": self._diff_stored_vs_recomputed(stored, computed),
        }

    async def _apply_timeseries(
        self,
        row: UpbitOpportunityShadowEntity,
        *,
        persist: bool,
    ) -> dict[str, Any]:
        computed = await self._compute_payload(row)
        if not computed.get("ok"):
            return {"changed": False, "just_completed": False, "computed": computed}

        changed = False
        just_completed = False
        windows = computed.get("windows") or {}

        if persist:
            detail = dict(row.evaluation_detail or {})
            # detail.windows 와 return_* 컬럼을 동일 final 결과로만 갱신
            prev_windows = dict(detail.get("windows") or {})

            for minutes in EVALUATION_WINDOWS_MINUTES:
                key = str(minutes)
                obs = dict(windows.get(key) or {})
                attr_at = f"evaluated_{minutes}m_at"
                already_final = getattr(row, attr_at) is not None

                if already_final:
                    # idempotent — 이미 final stamp 된 window 는 덮어쓰지 않음
                    if obs.get("status") == "OK":
                        synced = {**obs, "final": True}
                        prev_windows[key] = synced
                        windows[key] = synced
                    continue

                if obs.get("status") != "OK":
                    # provisional / 미완료 — final column·evaluated_*_at 금지
                    prev_windows[key] = {
                        "target_at": obs.get("target_at"),
                        "target_candle_start": obs.get("target_candle_start"),
                        "target_candle_end": obs.get("target_candle_end"),
                        "observed_candle_at": None,
                        "price": None,
                        "return_pct": None,
                        "status": obs.get("status") or "NOT_MATURED",
                        "final": False,
                    }
                    windows[key] = dict(prev_windows[key])
                    continue

                # FINAL — column + detail 한 트랜잭션에서 동일 값
                price = obs.get("price")
                ret = obs.get("return_pct")
                if price is None or ret is None:
                    continue
                setattr(row, f"price_{minutes}m", _dec(price))
                setattr(row, f"return_{minutes}m_pct", float(ret))
                setattr(row, attr_at, self._now)
                final_obs = {**obs, "final": True}
                prev_windows[key] = final_obs
                windows[key] = final_obs
                changed = True

            if computed.get("mfe_pct") is not None:
                row.mfe_pct = float(computed["mfe_pct"])
                changed = True
            if computed.get("mae_pct") is not None:
                row.mae_pct = float(computed["mae_pct"])
                changed = True

            tp_sl = computed.get("tp_sl") or {}
            if tp_sl.get("tp_hit") and row.tp_hit is not True:
                row.tp_hit = True
                hit_at = tp_sl.get("tp_hit_at")
                row.tp_hit_at = (
                    datetime.fromisoformat(hit_at)
                    if isinstance(hit_at, str)
                    else hit_at
                )
                changed = True
            elif row.tp_hit is None:
                row.tp_hit = bool(tp_sl.get("tp_hit"))
            if tp_sl.get("sl_hit") and row.sl_hit is not True:
                row.sl_hit = True
                hit_at = tp_sl.get("sl_hit_at")
                row.sl_hit_at = (
                    datetime.fromisoformat(hit_at)
                    if isinstance(hit_at, str)
                    else hit_at
                )
                changed = True
            elif row.sl_hit is None:
                row.sl_hit = bool(tp_sl.get("sl_hit"))

            detail["windows"] = prev_windows
            detail["mfe_mae"] = computed.get("mfe_mae_detail")
            detail["tp_sl"] = tp_sl
            detail["source"] = "minute_candle_historical_v1"
            detail["sl_pct"] = computed.get("sl_pct")
            detail["tp_pct"] = computed.get("tp_pct")
            detail["window_finalization"] = "target_candle_close_v2"
            row.evaluation_detail = detail
            row.updated_at = self._now

            if (
                row.evaluated_60m_at is not None
                and row.status == SHADOW_STATUS_ACTIVE
            ):
                row.status = SHADOW_STATUS_COMPLETED
                row.completed_at = self._now
                just_completed = True
                changed = True

        return {
            "changed": changed,
            "just_completed": just_completed,
            "computed": computed,
        }

    async def _compute_payload(
        self,
        row: UpbitOpportunityShadowEntity,
    ) -> dict[str, Any]:
        settings = get_settings()
        sl_pct = float(
            getattr(settings, "upbit_scanner_shadow_sl_pct", 3.0) or 3.0
        )
        tp_pct = float(
            getattr(settings, "upbit_scanner_shadow_tp_pct", 6.0) or 6.0
        )
        detected = as_utc(row.detected_at)
        entry = _dec(row.entry_price)
        terminal = detected + timedelta(minutes=60)
        eval_end = min(as_utc(self._now), terminal)

        loaded = await ensure_shadow_minute_bars(
            self._session,
            symbol=str(row.symbol),
            start_at=detected,
            end_at=eval_end,
            timeframe=1,
            allow_sync=self._allow_sync,
        )
        bars = loaded.get("bars") or []

        observations = observe_windows(
            bars,
            detected_at=detected,
            entry=entry,
            now=self._now,
            windows_minutes=EVALUATION_WINDOWS_MINUTES,
        )
        windows: dict[str, Any] = {}
        for obs in observations:
            windows[str(obs.minutes)] = {
                "target_at": obs.target_at.isoformat(),
                "target_candle_start": (
                    obs.target_candle_start.isoformat()
                    if obs.target_candle_start
                    else None
                ),
                "target_candle_end": (
                    obs.target_candle_end.isoformat()
                    if obs.target_candle_end
                    else None
                ),
                "observed_candle_at": (
                    obs.observed_candle_at.isoformat()
                    if obs.observed_candle_at
                    else None
                ),
                "price": float(obs.price) if obs.price is not None else None,
                "return_pct": _round6(obs.return_pct),
                "status": obs.status,
                "final": bool(obs.final),
            }

        mfe, mae, mfe_detail = compute_mfe_mae(
            bars,
            entry=entry,
            start_at=detected,
            end_at=eval_end,
            now=self._now,
        )
        tp_sl = compute_tp_sl(
            bars,
            entry=entry,
            start_at=detected,
            end_at=eval_end,
            now=self._now,
            tp_pct=tp_pct,
            sl_pct=sl_pct,
        )

        # window별 가격이 서로 다른지 검증 메타
        ok_prices = [
            windows[str(m)]["price"]
            for m in EVALUATION_WINDOWS_MINUTES
            if windows.get(str(m), {}).get("status") == "OK"
        ]
        distinct_prices = len({p for p in ok_prices if p is not None})

        return {
            "ok": True,
            "symbol": row.symbol,
            "entry_price": float(entry),
            "detected_at": detected.isoformat(),
            "evaluated_at": as_utc(self._now).isoformat(),
            "candle_count": len(bars),
            "sync": loaded.get("sync"),
            "windows": windows,
            "mfe_pct": _round6(mfe),
            "mae_pct": _round6(mae),
            "mfe_mae_detail": mfe_detail,
            "tp_sl": {
                "tp_hit": tp_sl.tp_hit,
                "sl_hit": tp_sl.sl_hit,
                "tp_hit_at": (
                    tp_sl.tp_hit_at.isoformat() if tp_sl.tp_hit_at else None
                ),
                "sl_hit_at": (
                    tp_sl.sl_hit_at.isoformat() if tp_sl.sl_hit_at else None
                ),
                "first_hit": tp_sl.first_hit,
                "detail": tp_sl.detail,
            },
            "tp_pct": tp_pct,
            "sl_pct": sl_pct,
            "distinct_window_prices": distinct_prices,
            "orders_created": 0,
        }

    @staticmethod
    def _diff_stored_vs_recomputed(
        stored: dict[str, Any],
        recomputed: dict[str, Any],
    ) -> dict[str, Any]:
        windows = recomputed.get("windows") or {}
        out: dict[str, Any] = {}
        for minutes in EVALUATION_WINDOWS_MINUTES:
            sk = f"return_{minutes}m_pct"
            new = (windows.get(str(minutes)) or {}).get("return_pct")
            old = stored.get(sk)
            out[sk] = {"stored": old, "recomputed": new}
        out["mfe_pct"] = {
            "stored": stored.get("mfe_pct"),
            "recomputed": recomputed.get("mfe_pct"),
        }
        out["mae_pct"] = {
            "stored": stored.get("mae_pct"),
            "recomputed": recomputed.get("mae_pct"),
        }
        out["tp_hit"] = {
            "stored": stored.get("tp_hit"),
            "recomputed": (recomputed.get("tp_sl") or {}).get("tp_hit"),
        }
        out["sl_hit"] = {
            "stored": stored.get("sl_hit"),
            "recomputed": (recomputed.get("tp_sl") or {}).get("sl_hit"),
        }
        return out
