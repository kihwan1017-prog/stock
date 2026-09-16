"""UPBIT dynamic news target — active portfolio + recent scanner candidates."""

from __future__ import annotations

from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from stock_platform.common.logger import logger


def list_upbit_dynamic_news_targets(
    session: Session,
    *,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """bounded dynamic targets. REAL entry/exit 비연동."""

    limit = max(0, min(int(limit), 15))
    if limit <= 0:
        return []

    symbols: list[str] = []
    # 1) 활성 포트폴리오 슬롯 심볼
    try:
        from stock_platform.operation.upbit_full_market.entities import (
            UpbitPositionSlotEntity,
        )
        from stock_platform.operation.upbit_full_market.constants import (
            SLOT_ACTIVE_SYMBOL_STATUSES,
        )

        rows = list(
            session.scalars(
                select(UpbitPositionSlotEntity.symbol)
                .where(
                    UpbitPositionSlotEntity.status.in_(
                        list(SLOT_ACTIVE_SYMBOL_STATUSES)
                    )
                )
                .order_by(desc(UpbitPositionSlotEntity.updated_at))
                .limit(limit * 3)
            )
        )
        for raw in rows:
            sym = str(raw or "").strip().upper()
            if sym.startswith("KRW-") and sym not in symbols:
                symbols.append(sym)
    except Exception as exc:  # noqa: BLE001
        logger.info(
            "upbit_dynamic_target_portfolio_failed",
            error=f"{type(exc).__name__}: {exc}"[:200],
        )

    # 2) 최근 opportunity shadow 심볼 (있으면)
    if len(symbols) < limit:
        try:
            from stock_platform.operation.upbit_opportunity_shadow.entities import (
                UpbitOpportunityShadowEntity,
            )

            cand_rows = list(
                session.scalars(
                    select(UpbitOpportunityShadowEntity.symbol)
                    .order_by(desc(UpbitOpportunityShadowEntity.created_at))
                    .limit(limit * 2)
                )
            )
            for raw in cand_rows:
                sym = str(raw or "").strip().upper()
                if sym.startswith("KRW-") and sym not in symbols:
                    symbols.append(sym)
                if len(symbols) >= limit:
                    break
        except Exception as exc:  # noqa: BLE001
            logger.info(
                "upbit_dynamic_target_scanner_failed",
                error=f"{type(exc).__name__}: {exc}"[:200],
            )

    out: list[dict[str, Any]] = []
    for sym in symbols[:limit]:
        base = sym.split("-", 1)[-1] if "-" in sym else sym
        # Naver 검색용: 업비트 + base ticker
        out.append(
            {
                "symbol": sym,
                "query": f"업비트 {base}",
                "source": "DYNAMIC_CANDIDATE",
            }
        )
    return out
