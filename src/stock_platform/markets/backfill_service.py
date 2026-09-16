from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from stock_platform.common.settings import get_settings
from stock_platform.markets.collection_entities import MarketDataBackfillCheckpoint
from stock_platform.markets.gap_detection_service import MarketDataGapDetectionService


@dataclass(slots=True)
class BackfillBatchResult:
    exchange_code: str
    processed: int
    repaired: int
    failed: int
    remaining_pending: int
    items: list[dict]


class MarketDataBackfillService:
    """DB checkpoint 기반 bounded daily backfill."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._gaps = MarketDataGapDetectionService(session)
        self._settings = get_settings()

    def seed_gaps_from_detection(
        self,
        *,
        exchange_code: str,
        start_date: date,
        end_date: date,
        symbol_limit: int = 100,
    ) -> int:
        rows = self._gaps.detect_daily_gaps(
            exchange_code=exchange_code,
            start_date=start_date,
            end_date=end_date,
            symbol_limit=symbol_limit,
        )
        if not rows:
            return 0

        values = [
            {
                "exchange_code": exchange_code.upper(),
                "data_kind": "DAILY",
                "symbol": row["symbol"],
                "expected_date": row["expected_date"],
                "repair_status": "PENDING",
                "gap_reason": row["gap_reason"],
                "attempt_count": 0,
                "updated_at": datetime.now(timezone.utc),
            }
            for row in rows
        ]
        stmt = insert(MarketDataBackfillCheckpoint).values(values)
        stmt = stmt.on_conflict_do_nothing(
            index_elements=[
                "exchange_code",
                "data_kind",
                "symbol",
                "expected_date",
            ]
        )
        result = self._session.execute(stmt)
        self._session.commit()
        return result.rowcount or len(values)

    def pending_count(self, exchange_code: str) -> int:
        from sqlalchemy import func

        return int(
            self._session.scalar(
                select(func.count())
                .select_from(MarketDataBackfillCheckpoint)
                .where(
                    MarketDataBackfillCheckpoint.exchange_code
                    == exchange_code.upper(),
                    MarketDataBackfillCheckpoint.data_kind == "DAILY",
                    MarketDataBackfillCheckpoint.repair_status == "PENDING",
                )
            )
            or 0
        )

    async def run_bounded_batch(
        self,
        *,
        exchange_code: str,
        sync_symbol_fn,
    ) -> BackfillBatchResult:
        """sync_symbol_fn(symbol, start, end) -> saved_count coroutine."""

        batch_size = int(getattr(self._settings, "market_data_backfill_batch_size", 20))
        pending = list(
            self._session.scalars(
                select(MarketDataBackfillCheckpoint)
                .where(
                    MarketDataBackfillCheckpoint.exchange_code
                    == exchange_code.upper(),
                    MarketDataBackfillCheckpoint.repair_status == "PENDING",
                )
                .order_by(
                    MarketDataBackfillCheckpoint.symbol.asc(),
                    MarketDataBackfillCheckpoint.expected_date.asc(),
                )
                .limit(batch_size)
            ).all()
        )

        repaired = 0
        failed = 0
        items: list[dict] = []

        # symbol별로 묶어 API 호출 최소화
        by_symbol: dict[str, list[MarketDataBackfillCheckpoint]] = {}
        for row in pending:
            by_symbol.setdefault(row.symbol, []).append(row)

        for symbol, checkpoints in by_symbol.items():
            dates = [cp.expected_date for cp in checkpoints]
            start = min(dates)
            end = max(dates)
            try:
                saved = await sync_symbol_fn(symbol, start, end)
                for cp in checkpoints:
                    cp.repair_status = "REPAIRED"
                    cp.updated_at = datetime.now(timezone.utc)
                repaired += len(checkpoints)
                items.append({"symbol": symbol, "status": "REPAIRED", "saved": saved})
            except Exception as exc:  # noqa: BLE001
                for cp in checkpoints:
                    cp.attempt_count += 1
                    cp.last_error = str(exc)[:500]
                    if cp.attempt_count >= 3:
                        cp.repair_status = "FAILED"
                failed += len(checkpoints)
                items.append({"symbol": symbol, "status": "FAILED", "error": str(exc)[:200]})

        self._session.commit()

        remaining = self._session.execute(
            select(MarketDataBackfillCheckpoint.checkpoint_id).where(
                MarketDataBackfillCheckpoint.exchange_code == exchange_code.upper(),
                MarketDataBackfillCheckpoint.repair_status == "PENDING",
            )
        ).all()

        return BackfillBatchResult(
            exchange_code=exchange_code.upper(),
            processed=len(pending),
            repaired=repaired,
            failed=failed,
            remaining_pending=len(remaining),
            items=items,
        )

    def to_dict(self, result: BackfillBatchResult) -> dict:
        return asdict(result)
