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
    resolve_missing_target_minutes,
)
from stock_platform.operation.upbit_opportunity_shadow.candle_path import (
    DEFAULT_MAX_PRIOR_LAG_SECONDS,
    as_utc,
    compute_mfe_mae,
    compute_tp_sl,
    observe_windows,
    target_candle_bounds,
)
from stock_platform.operation.upbit_opportunity_shadow.constants import (
    EVALUATION_WINDOWS_MINUTES,
    SHADOW_STATUS_ACTIVE,
    SHADOW_STATUS_COMPLETED,
)
from stock_platform.operation.upbit_opportunity_shadow.termination import (
    apply_permanent_absence_termination,
)
from stock_platform.operation.upbit_opportunity_shadow.entities import (
    UpbitOpportunityShadowEntity,
)
from stock_platform.operation.upbit_opportunity_shadow.notify import (
    publish_shadow_result,
)
from stock_platform.operation.upbit_opportunity_shadow.path_quality import (
    absent_ats_from_target_map,
    build_path_defer_detail,
    compute_path_quality,
    path_completeness_pass,
    source_unavailable_from_maps,
)
from stock_platform.operation.upbit_opportunity_shadow.source_range_reconcile import (
    reconcile_observation_source,
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


def _window_dict(obs: Any) -> dict[str, Any]:
    """WindowObservation → evaluation_detail.windows[N] 공통 스키마."""

    return {
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
        "selection_type": obs.selection_type,
        "lag_seconds": obs.lag_seconds,
        "fallback_reason": obs.fallback_reason,
        "source": obs.source,
    }


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
        deferred = False
        windows = computed.get("windows") or {}
        path_quality = computed.get("path_quality")
        # COV-B: path completeness gate — COMPLETED / 60m final write 직전
        path_pass = path_completeness_pass(path_quality)

        if persist:
            detail = dict(row.evaluation_detail or {})
            prev_windows = dict(detail.get("windows") or {})

            if not path_pass:
                # DEFER: ACTIVE 유지 · final column/COMPLETED 금지 · evidence만
                deferred = True
                for minutes in EVALUATION_WINDOWS_MINUTES:
                    key = str(minutes)
                    obs = dict(windows.get(key) or {})
                    attr_at = f"evaluated_{minutes}m_at"
                    if getattr(row, attr_at) is not None:
                        # 이미 확정된 window는 유지 (idempotent detail sync)
                        if obs.get("status") == "OK":
                            prev_windows[key] = {**obs, "final": True}
                        continue
                    prev_windows[key] = {
                        **obs,
                        "observed_candle_at": None,
                        "price": None,
                        "return_pct": None,
                        "final": False,
                    }
                    windows[key] = dict(prev_windows[key])

                detail["windows"] = prev_windows
                detail["source"] = "minute_candle_historical_v1"
                detail["sl_pct"] = computed.get("sl_pct")
                detail["tp_pct"] = computed.get("tp_pct")
                detail["window_finalization"] = "last_known_price_at_target_v1"
                detail["max_prior_lag_seconds"] = DEFAULT_MAX_PRIOR_LAG_SECONDS
                detail["target_resolve"] = computed.get("target_resolve")
                if path_quality is not None:
                    detail["path_quality"] = path_quality
                detail["path_defer"] = build_path_defer_detail(
                    path_quality=path_quality
                    if isinstance(path_quality, dict)
                    else None,
                    previous=detail.get("path_defer")
                    if isinstance(detail.get("path_defer"), dict)
                    else None,
                    now=self._now,
                )
                if computed.get("source_reconcile") is not None:
                    detail["source_reconcile"] = computed.get("source_reconcile")
                row.evaluation_detail = detail
                row.updated_at = self._now
                changed = True
                # evaluated_60m_at / COMPLETED / mfe·tp columns — 미기록
                return {
                    "changed": changed,
                    "just_completed": False,
                    "deferred": True,
                    "computed": computed,
                }

            # PATH PASS — TARGET_ONLY permanent absence → CANCELLED (fake metric 금지)
            term_result = apply_permanent_absence_termination(
                row,
                computed=computed,
                now=self._now,
            )
            if term_result.get("terminated"):
                detail = dict(row.evaluation_detail or {})
                for minutes in EVALUATION_WINDOWS_MINUTES:
                    key = str(minutes)
                    obs = dict(windows.get(key) or {})
                    attr_at = f"evaluated_{minutes}m_at"
                    if getattr(row, attr_at) is not None:
                        if obs.get("status") == "OK":
                            prev_windows[key] = {**obs, "final": True}
                        continue
                    # MISSING 창은 final 금지 · price/return 미기록
                    prev_windows[key] = {
                        **obs,
                        "observed_candle_at": None,
                        "price": None,
                        "return_pct": None,
                        "final": False,
                    }
                detail["windows"] = prev_windows
                detail["source"] = "minute_candle_historical_v1"
                detail["sl_pct"] = computed.get("sl_pct")
                detail["tp_pct"] = computed.get("tp_pct")
                detail["window_finalization"] = "last_known_price_at_target_v1"
                detail["max_prior_lag_seconds"] = DEFAULT_MAX_PRIOR_LAG_SECONDS
                detail["target_resolve"] = computed.get("target_resolve")
                if path_quality is not None:
                    detail["path_quality"] = path_quality
                if computed.get("source_reconcile") is not None:
                    detail["source_reconcile"] = computed.get("source_reconcile")
                row.evaluation_detail = detail
                row.updated_at = self._now
                return {
                    "changed": True,
                    "just_completed": False,
                    "terminated": True,
                    "computed": computed,
                }

            # grace 대기 중 first_blocked_at 스탬프 유지
            if term_result.get("changed") or term_result.get("deferred_grace"):
                detail = dict(row.evaluation_detail or {})
                prev_windows = dict(detail.get("windows") or {})

            # PATH PASS — 기존 finalization
            for minutes in EVALUATION_WINDOWS_MINUTES:
                key = str(minutes)
                obs = dict(windows.get(key) or {})
                attr_at = f"evaluated_{minutes}m_at"
                already_final = getattr(row, attr_at) is not None

                if already_final:
                    if obs.get("status") == "OK":
                        synced = {**obs, "final": True}
                        prev_windows[key] = synced
                        windows[key] = synced
                    continue

                if obs.get("status") != "OK":
                    prev_windows[key] = {
                        **obs,
                        "observed_candle_at": None,
                        "price": None,
                        "return_pct": None,
                        "final": False,
                    }
                    windows[key] = dict(prev_windows[key])
                    continue

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
            detail["window_finalization"] = "last_known_price_at_target_v1"
            detail["max_prior_lag_seconds"] = DEFAULT_MAX_PRIOR_LAG_SECONDS
            detail["target_resolve"] = computed.get("target_resolve")
            if path_quality is not None:
                detail["path_quality"] = path_quality
            # PASS 시 path_defer 정리(남아 있으면 해소 표시)
            if detail.get("path_defer"):
                cleared = dict(detail["path_defer"])
                cleared["resolved_at"] = as_utc(self._now).isoformat()
                cleared["resolved"] = True
                detail["path_defer"] = cleared
            if computed.get("source_reconcile") is not None:
                detail["source_reconcile"] = computed.get("source_reconcile")
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
            "deferred": deferred,
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
        now_utc = as_utc(self._now)

        loaded = await ensure_shadow_minute_bars(
            self._session,
            symbol=str(row.symbol),
            start_at=detected,
            end_at=eval_end,
            timeframe=1,
            allow_sync=self._allow_sync,
        )
        bars = list(loaded.get("bars") or [])

        # 완료 gate 지난 window의 exact 부재분만 원천 재확인
        matured_missing_starts: list[datetime] = []
        bar_ats = {as_utc(b.candle_at) for b in bars}
        for minutes in EVALUATION_WINDOWS_MINUTES:
            target = detected + timedelta(minutes=int(minutes))
            candle_start, candle_end = target_candle_bounds(target)
            if now_utc < candle_end:
                continue
            if candle_start not in bar_ats:
                matured_missing_starts.append(candle_start)

        resolved = await resolve_missing_target_minutes(
            self._session,
            symbol=str(row.symbol),
            bars=bars,
            candle_starts=matured_missing_starts,
            timeframe=1,
            allow_sync=self._allow_sync,
        )
        bars = list(resolved.get("bars") or bars)
        absent_by_target = dict(resolved.get("absent_by_target") or {})
        source_unavailable_by_target = dict(
            resolved.get("source_unavailable_by_target") or {}
        )

        # COV-C: 60m observation window source range reconcile (evidence)
        # COV-B gate는 _apply_timeseries에서 path_quality 기준 적용
        bars, source_evidence = await reconcile_observation_source(
            self._session,
            symbol=str(row.symbol),
            detected_at=detected,
            terminal_at=terminal,
            now=now_utc,
            bars=bars,
            timeframe=1,
            allow_sync=self._allow_sync,
            persist_upsert=bool(self._allow_sync),
        )

        observations = observe_windows(
            bars,
            detected_at=detected,
            entry=entry,
            now=self._now,
            windows_minutes=EVALUATION_WINDOWS_MINUTES,
            max_prior_lag_seconds=DEFAULT_MAX_PRIOR_LAG_SECONDS,
            absent_by_target=absent_by_target,
            source_unavailable_by_target=source_unavailable_by_target,
            candle_source="market.candle_minute",
        )
        windows: dict[str, Any] = {
            str(obs.minutes): _window_dict(obs) for obs in observations
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

        # COV-A/C path quality — source evidence 반영 (COMPLETED gate는 _apply_timeseries).
        sync_payload = loaded.get("sync")
        source_unavail, sync_last = source_unavailable_from_maps(
            source_unavailable_by_target=source_unavailable_by_target,
            sync_payload=sync_payload,
        )
        if source_evidence.source_unavailable:
            source_unavail = True
            sync_last = (
                source_evidence.source_check_result or sync_last or "SOURCE_RANGE_UNAVAILABLE"
            )
        sync_attempts = 0
        if sync_payload is not None:
            sync_attempts += 1
        if source_evidence.source_check_performed:
            sync_attempts += 1

        absent_ats = absent_ats_from_target_map(absent_by_target)
        absent_ats |= source_evidence.absent_ats()

        path_quality = compute_path_quality(
            detected_at=detected,
            end_at=terminal,
            now=now_utc,
            bars=bars,
            source_absent_confirmed_ats=absent_ats,
            source_unavailable=source_unavail,
            sync_attempts=sync_attempts,
            sync_last_result=sync_last,
            defer_reason=None,
            source_check_performed=source_evidence.source_check_performed,
            source_check_result=source_evidence.source_check_result,
            source_candle_count=source_evidence.source_candle_count,
            db_missing_source_present=len(
                source_evidence.db_missing_source_present_ats
            ),
            source_reconcile_requests=source_evidence.requests,
        ).to_detail_dict()
        # provenance blob (migration 없이 detail에 첨부)
        path_quality["source_reconcile"] = source_evidence.to_detail_dict()

        return {
            "ok": True,
            "symbol": row.symbol,
            "entry_price": float(entry),
            "detected_at": detected.isoformat(),
            "evaluated_at": now_utc.isoformat(),
            "candle_count": len(bars),
            "sync": loaded.get("sync"),
            "source_reconcile": source_evidence.to_detail_dict(),
            "target_resolve": resolved.get("resolve_detail"),
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
            "max_prior_lag_seconds": DEFAULT_MAX_PRIOR_LAG_SECONDS,
            "path_quality": path_quality,
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
            w = windows.get(str(minutes)) or {}
            new = w.get("return_pct")
            old = stored.get(sk)
            out[sk] = {
                "stored": old,
                "recomputed": new,
                "selection_type": w.get("selection_type"),
                "fallback_reason": w.get("fallback_reason"),
                "lag_seconds": w.get("lag_seconds"),
            }
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
