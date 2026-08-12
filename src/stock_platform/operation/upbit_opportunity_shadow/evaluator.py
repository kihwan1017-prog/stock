"""Shadow 평가 — 가격만 사용, AI 재호출 없음."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable, Awaitable

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.broker.upbit.market.client import UpbitQuotationClient
from stock_platform.common.settings import get_settings
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


def _return_pct(entry: Decimal, price: Decimal) -> float:
    if entry <= 0:
        return 0.0
    return round(float((price - entry) / entry * Decimal("100")), 6)


class UpbitOpportunityShadowEvaluator:
    """ACTIVE Shadow의 5/15/30/60분 창을 채우고 60분 후 COMPLETED."""

    def __init__(
        self,
        session: Session,
        *,
        quotation_client: UpbitQuotationClient | None = None,
        price_fetcher: Callable[[list[str]], Awaitable[dict[str, float]]]
        | None = None,
        now: datetime | None = None,
    ) -> None:
        self._session = session
        self._client = quotation_client
        self._price_fetcher = price_fetcher
        self._now = now or datetime.now(timezone.utc)

    async def evaluate_pending(self, *, notify: bool = True) -> dict[str, Any]:
        settings = get_settings()
        sl_pct = float(
            getattr(settings, "upbit_scanner_shadow_sl_pct", 3.0) or 3.0
        )
        tp_pct = float(
            getattr(settings, "upbit_scanner_shadow_tp_pct", 6.0) or 6.0
        )

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
            }

        symbols = sorted({r.symbol for r in rows})
        prices = await self._fetch_prices(symbols)
        evaluated = 0
        completed_rows: list[UpbitOpportunityShadowEntity] = []

        for row in rows:
            price = prices.get(row.symbol)
            if price is None or price <= 0:
                continue
            price_dec = Decimal(str(price))
            entry = Decimal(str(row.entry_price))
            ret = _return_pct(entry, price_dec)
            detected = row.detected_at
            if detected.tzinfo is None:
                detected = detected.replace(tzinfo=timezone.utc)
            age = self._now - detected

            detail = dict(row.evaluation_detail or {})
            windows = dict(detail.get("windows") or {})
            seen = list(detail.get("prices_seen") or [])
            seen.append(
                {
                    "at": self._now.isoformat(),
                    "price": float(price_dec),
                    "return_pct": ret,
                }
            )
            seen = seen[-200:]

            rets = [float(p.get("return_pct") or 0) for p in seen]
            mfe = max(rets) if rets else ret
            mae = min(rets) if rets else ret
            row.mfe_pct = round(mfe, 6)
            row.mae_pct = round(mae, 6)

            if row.sl_hit is not True and mae <= -abs(sl_pct):
                row.sl_hit = True
                row.sl_hit_at = self._now
            if row.tp_hit is not True and mfe >= abs(tp_pct):
                row.tp_hit = True
                row.tp_hit_at = self._now
            if row.sl_hit is None:
                row.sl_hit = False
            if row.tp_hit is None:
                row.tp_hit = False

            changed = False
            for minutes in EVALUATION_WINDOWS_MINUTES:
                attr_price = f"price_{minutes}m"
                attr_ret = f"return_{minutes}m_pct"
                attr_at = f"evaluated_{minutes}m_at"
                if getattr(row, attr_at) is not None:
                    continue
                if age < timedelta(minutes=minutes):
                    continue
                setattr(row, attr_price, price_dec)
                setattr(row, attr_ret, ret)
                setattr(row, attr_at, self._now)
                windows[str(minutes)] = {
                    "price": float(price_dec),
                    "return_pct": ret,
                    "at": self._now.isoformat(),
                }
                changed = True

            detail["windows"] = windows
            detail["prices_seen"] = seen
            detail["sl_pct"] = sl_pct
            detail["tp_pct"] = tp_pct
            row.evaluation_detail = detail
            row.updated_at = self._now

            if row.evaluated_60m_at is not None:
                row.status = SHADOW_STATUS_COMPLETED
                row.completed_at = self._now
                completed_rows.append(row)
                changed = True

            if changed:
                evaluated += 1

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
            "shadows": [
                UpbitOpportunityShadowService.to_public(r) for r in rows
            ],
        }

    async def _fetch_prices(self, symbols: list[str]) -> dict[str, float]:
        if self._price_fetcher is not None:
            return await self._price_fetcher(symbols)

        owns = self._client is None
        client = self._client or UpbitQuotationClient()
        out: dict[str, float] = {}
        try:
            batch = 100
            for i in range(0, len(symbols), batch):
                chunk = symbols[i : i + batch]
                try:
                    rows = await client.list_tickers(markets=chunk)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "shadow_price_fetch_failed",
                        error=type(exc).__name__,
                        size=len(chunk),
                    )
                    continue
                for row in rows:
                    market = str(row.get("market") or "").upper()
                    try:
                        px = float(row.get("trade_price"))
                    except (TypeError, ValueError):
                        continue
                    if market and px > 0:
                        out[market] = px
        finally:
            if owns:
                await client.aclose()
        return out
