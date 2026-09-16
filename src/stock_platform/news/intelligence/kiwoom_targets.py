"""KIWOOM TOP10 monitor roster → news/DART target."""

from __future__ import annotations

from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from stock_platform.common.logger import logger
from stock_platform.operation.kiwoom_multi_symbol_universe.entities import (
    KiwoomMultiSymbolMonitorEntity,
)


def list_kiwoom_top10_targets(
    session: Session,
    *,
    user_broker_account_id: int | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """최신 monitor batch의 TOP-N. LIVE/ARM 토글 없음."""

    limit = max(1, min(int(limit), 20))
    uba_filter = (
        int(user_broker_account_id)
        if user_broker_account_id is not None
        else None
    )

    stmt = select(KiwoomMultiSymbolMonitorEntity)
    max_stmt = select(func.max(KiwoomMultiSymbolMonitorEntity.selected_at))
    if uba_filter is not None:
        stmt = stmt.where(
            KiwoomMultiSymbolMonitorEntity.user_broker_account_id == uba_filter
        )
        max_stmt = max_stmt.where(
            KiwoomMultiSymbolMonitorEntity.user_broker_account_id == uba_filter
        )
    # 최신 selected_at 배치 우선
    latest_selected = session.scalar(max_stmt)
    if latest_selected is not None:
        stmt = stmt.where(
            KiwoomMultiSymbolMonitorEntity.selected_at == latest_selected
        )
    rows = list(
        session.scalars(
            stmt.order_by(
                KiwoomMultiSymbolMonitorEntity.rank.asc(),
                desc(KiwoomMultiSymbolMonitorEntity.selected_at),
            ).limit(limit)
        )
    )
    if not rows and uba_filter is not None:
        # UBA 지정인데 없으면 전역 최신으로 fallback
        return list_kiwoom_top10_targets(
            session, user_broker_account_id=None, limit=limit
        )

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        sym = str(row.symbol or "").strip().upper()
        if not sym or sym in seen:
            continue
        seen.add(sym)
        name = str(row.name or "").strip() or sym
        out.append(
            {
                "symbol": sym,
                "name": name,
                "rank": int(row.rank or 0),
                "query": name,
                "user_broker_account_id": int(row.user_broker_account_id),
                "refresh_batch_id": str(row.refresh_batch_id or ""),
            }
        )
    return out


def resolve_default_kiwoom_uba(session: Session) -> int | None:
    try:
        return session.scalar(
            select(KiwoomMultiSymbolMonitorEntity.user_broker_account_id)
            .order_by(desc(KiwoomMultiSymbolMonitorEntity.selected_at))
            .limit(1)
        )
    except Exception as exc:  # noqa: BLE001
        logger.info(
            "kiwoom_top10_uba_resolve_failed",
            error=f"{type(exc).__name__}: {exc}"[:200],
        )
        return None
