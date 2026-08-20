"""Scanner 완료 후 FULL_MARKET LIVE consume (주문 없음)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.operation.upbit_full_market.constants import (
    FULL_MARKET_ANY_MODES,
)
from stock_platform.operation.upbit_full_market.entities import (
    UpbitFullMarketAssignmentEntity,
)
from stock_platform.operation.upbit_full_market.portfolio_service import (
    UpbitPortfolioService,
)
from stock_platform.operation.upbit_full_market.service import (
    UpbitFullMarketAssignmentService,
)
from stock_platform.operation.upbit_full_market.constants import (
    is_full_market_portfolio,
    is_full_market_single,
)

logger = structlog.get_logger(__name__)


def consume_latest_scanner_for_full_market_accounts(
    session: Session,
    *,
    scanner_result: dict[str, Any],
    dry_run: bool = False,
) -> dict[str, Any]:
    """독립 LIVE consume layer — Scanner 자체는 주문하지 않음."""

    candidates = list(scanner_result.get("candidates") or [])
    run_id = str(scanner_result.get("scanner_run_id") or "").strip()
    if not run_id or not candidates:
        return {
            "ok": False,
            "reason": "NO_SCANNER_CANDIDATES",
            "accounts": [],
        }

    completed_at = None
    raw_ts = scanner_result.get("completed_at") or scanner_result.get(
        "finished_at"
    )
    if isinstance(raw_ts, datetime):
        completed_at = raw_ts
    elif isinstance(raw_ts, str) and raw_ts:
        try:
            completed_at = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
        except ValueError:
            completed_at = datetime.now(timezone.utc)
    else:
        completed_at = datetime.now(timezone.utc)

    rows = list(
        session.scalars(
            select(UpbitFullMarketAssignmentEntity).where(
                UpbitFullMarketAssignmentEntity.mode.in_(
                    list(FULL_MARKET_ANY_MODES)
                ),
                UpbitFullMarketAssignmentEntity.broker_code == "UPBIT",
            )
        )
    )
    svc = UpbitFullMarketAssignmentService(session)
    portfolio = UpbitPortfolioService(session)
    accounts: list[dict[str, Any]] = []
    for row in rows:
        try:
            svc.tick_cooldown_to_idle(int(row.user_broker_account_id))
            if is_full_market_portfolio(row.mode):
                result = portfolio.consume_top_k(
                    int(row.user_broker_account_id),
                    candidates=candidates,
                    scanner_run_id=run_id,
                    scanner_completed_at=completed_at,
                    dry_run=dry_run,
                )
            elif is_full_market_single(row.mode):
                result = svc.consume_scanner_candidates(
                    int(row.user_broker_account_id),
                    candidates=candidates,
                    scanner_run_id=run_id,
                    scanner_completed_at=completed_at,
                    dry_run=dry_run,
                )
            else:
                continue
            accounts.append(result)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "upbit_full_market_consume_failed",
                uba_id=row.user_broker_account_id,
                error=type(exc).__name__,
            )
            accounts.append(
                {
                    "ok": False,
                    "uba_id": int(row.user_broker_account_id),
                    "reason": type(exc).__name__,
                    "orders_created": 0,
                }
            )

    return {
        "ok": True,
        "scanner_run_id": run_id,
        "account_count": len(accounts),
        "accounts": accounts,
        "orders_created": 0,
    }
