"""Paper Shadow 생성 — ALLOW/REDUCE만, 실주문 0."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.common.settings import get_settings
from stock_platform.operation.upbit_opportunity_shadow.constants import (
    SHADOW_RECOMMENDATIONS,
    SHADOW_STATUS_ACTIVE,
    SHADOW_STATUS_COMPLETED,
)
from stock_platform.operation.upbit_opportunity_shadow.entities import (
    UpbitOpportunityShadowEntity,
)
from stock_platform.operation.upbit_opportunity_shadow.notify import (
    publish_shadow_opened,
)

logger = structlog.get_logger(__name__)


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception:  # noqa: BLE001
        return None


def _f(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class UpbitOpportunityShadowService:
    """Scanner 후보 → Paper Shadow Entry. TradingOrder 생성 금지."""

    def __init__(self, session: Session, *, now: datetime | None = None) -> None:
        self._session = session
        self._now = now or datetime.now(timezone.utc)

    def create_from_candidates(
        self,
        *,
        candidates: list[dict[str, Any]],
        scanner_run_id: str,
        notify: bool = True,
    ) -> dict[str, Any]:
        settings = get_settings()
        if not bool(getattr(settings, "upbit_scanner_shadow_enabled", True)):
            return {
                "created": 0,
                "skipped": len(candidates),
                "shadows": [],
                "reason": "SHADOW_DISABLED",
                "orders_created": 0,
            }

        base_amount = float(
            getattr(settings, "upbit_scanner_shadow_assumed_amount_krw", 5000)
            or 5000
        )
        reduce_ratio = float(
            getattr(settings, "upbit_scanner_shadow_reduce_ratio", 0.5) or 0.5
        )
        cooldown_sec = float(
            getattr(settings, "upbit_scanner_shadow_cooldown_seconds", 3600)
            or 3600
        )

        created: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []

        for cand in candidates:
            rec = str(cand.get("recommendation") or "").upper()
            symbol = str(cand.get("symbol") or "").upper()
            if not symbol or rec not in SHADOW_RECOMMENDATIONS:
                skipped.append(
                    {"symbol": symbol, "reason": "NOT_ALLOW_REDUCE", "rec": rec}
                )
                continue
            if cand.get("fail_closed") or cand.get("ai_error"):
                skipped.append(
                    {"symbol": symbol, "reason": "AI_FAIL_CLOSED"}
                )
                continue
            if cand.get("cooldown_suppressed"):
                skipped.append({"symbol": symbol, "reason": "ALERT_COOLDOWN"})
                continue

            entry_price = _dec(cand.get("price"))
            if entry_price is None or entry_price <= 0:
                skipped.append({"symbol": symbol, "reason": "NO_ENTRY_PRICE"})
                continue

            if self._has_active_shadow(symbol):
                skipped.append({"symbol": symbol, "reason": "ACTIVE_EXISTS"})
                continue

            if self._in_shadow_cooldown(symbol, cooldown_sec):
                skipped.append({"symbol": symbol, "reason": "SHADOW_COOLDOWN"})
                continue

            amount = base_amount
            if rec == "REDUCE":
                amount = base_amount * reduce_ratio

            row = UpbitOpportunityShadowEntity(
                scanner_run_id=str(scanner_run_id)[:64],
                symbol=symbol,
                recommendation=rec,
                status=SHADOW_STATUS_ACTIVE,
                scanner_rank=int(cand["rank"]) if cand.get("rank") else None,
                scanner_score=_f(cand.get("score")),
                entry_price=entry_price,
                assumed_amount_krw=Decimal(str(round(amount, 4))),
                confidence=_f(cand.get("confidence")),
                risk_level=(
                    str(cand.get("risk_level")) if cand.get("risk_level") else None
                ),
                trend=str(cand["trend"]) if cand.get("trend") else None,
                momentum=str(cand["momentum"]) if cand.get("momentum") else None,
                volatility=(
                    str(cand["volatility"]) if cand.get("volatility") else None
                ),
                ma5=_f(cand.get("ma5")),
                ma20=_f(cand.get("ma20")),
                rsi14=_f(cand.get("rsi14")),
                macd=_f(cand.get("macd")),
                atr14=_f(cand.get("atr14")),
                volume_surge=_f(cand.get("volume_surge")),
                trade_value_24h=_f(cand.get("trade_value_24h")),
                market_analysis_id=(
                    int(cand["analysis_id"])
                    if cand.get("analysis_id")
                    else None
                ),
                live_auto_start=False,
                detected_at=self._now,
                entry_snapshot={
                    "source": "upbit_opportunity_scanner_paper_shadow_v1",
                    "live_auto_start": False,
                    "paper_shadow": True,
                    "candidate": {
                        k: cand.get(k)
                        for k in (
                            "symbol",
                            "rank",
                            "score",
                            "recommendation",
                            "confidence",
                            "risk_level",
                            "price",
                            "ma_spread_pct",
                            "momentum_5m_pct",
                        )
                    },
                },
                evaluation_detail={"windows": {}, "prices_seen": []},
            )
            self._session.add(row)
            self._session.flush()
            public = self.to_public(row)
            created.append(public)
            if notify:
                try:
                    publish_shadow_opened(public)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "shadow_open_notify_failed",
                        symbol=symbol,
                        error=type(exc).__name__,
                    )

        if created:
            self._session.commit()
        else:
            self._session.flush()

        return {
            "created": len(created),
            "skipped": skipped,
            "shadows": created,
            "orders_created": 0,
            "live_auto_start": False,
            "paper_shadow": True,
        }

    def _has_active_shadow(self, symbol: str) -> bool:
        row = self._session.scalar(
            select(UpbitOpportunityShadowEntity).where(
                UpbitOpportunityShadowEntity.symbol == symbol,
                UpbitOpportunityShadowEntity.status == SHADOW_STATUS_ACTIVE,
                UpbitOpportunityShadowEntity.deleted_at.is_(None),
            )
        )
        return row is not None

    def _in_shadow_cooldown(self, symbol: str, cooldown_sec: float) -> bool:
        latest = self._session.scalar(
            select(UpbitOpportunityShadowEntity)
            .where(
                UpbitOpportunityShadowEntity.symbol == symbol,
                UpbitOpportunityShadowEntity.deleted_at.is_(None),
                UpbitOpportunityShadowEntity.status.in_(
                    [SHADOW_STATUS_COMPLETED, SHADOW_STATUS_ACTIVE]
                ),
            )
            .order_by(UpbitOpportunityShadowEntity.detected_at.desc())
            .limit(1)
        )
        if latest is None:
            return False
        if latest.status == SHADOW_STATUS_ACTIVE:
            return True
        completed = latest.completed_at or latest.detected_at
        if completed.tzinfo is None:
            completed = completed.replace(tzinfo=timezone.utc)
        return (self._now - completed) < timedelta(seconds=cooldown_sec)

    def list_shadows(
        self,
        *,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        q = select(UpbitOpportunityShadowEntity).where(
            UpbitOpportunityShadowEntity.deleted_at.is_(None)
        )
        if status:
            q = q.where(UpbitOpportunityShadowEntity.status == status.upper())
        q = q.order_by(UpbitOpportunityShadowEntity.detected_at.desc()).limit(
            max(1, min(200, limit))
        )
        return [self.to_public(r) for r in self._session.scalars(q)]

    @staticmethod
    def to_public(row: UpbitOpportunityShadowEntity) -> dict[str, Any]:
        return {
            "shadow_id": int(row.shadow_id) if row.shadow_id is not None else None,
            "scanner_run_id": row.scanner_run_id,
            "symbol": row.symbol,
            "recommendation": row.recommendation,
            "status": row.status,
            "scanner_rank": row.scanner_rank,
            "scanner_score": row.scanner_score,
            "entry_price": float(row.entry_price) if row.entry_price is not None else None,
            "assumed_amount_krw": float(row.assumed_amount_krw)
            if row.assumed_amount_krw is not None
            else None,
            "confidence": row.confidence,
            "risk_level": row.risk_level,
            "trend": row.trend,
            "momentum": row.momentum,
            "volatility": row.volatility,
            "detected_at": row.detected_at.isoformat() if row.detected_at else None,
            "return_5m_pct": row.return_5m_pct,
            "return_15m_pct": row.return_15m_pct,
            "return_30m_pct": row.return_30m_pct,
            "return_60m_pct": row.return_60m_pct,
            "price_5m": float(row.price_5m) if row.price_5m is not None else None,
            "price_15m": float(row.price_15m) if row.price_15m is not None else None,
            "price_30m": float(row.price_30m) if row.price_30m is not None else None,
            "price_60m": float(row.price_60m) if row.price_60m is not None else None,
            "mfe_pct": row.mfe_pct,
            "mae_pct": row.mae_pct,
            "sl_hit": row.sl_hit,
            "tp_hit": row.tp_hit,
            "completed_at": (
                row.completed_at.isoformat() if row.completed_at else None
            ),
            "live_auto_start": False,
            "paper_shadow": True,
            "orders_created": 0,
        }
