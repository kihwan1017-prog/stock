from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.markets.models import Instrument
from stock_platform.markets.repository import PriceDailyRepository
from stock_platform.markets.service import (
    InstrumentNotFoundError,
    PriceDailyService,
)
from stock_platform.screener.models import CandidateScore
from stock_platform.screener.service import ScreenerService


logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class BatchScreeningResult:
    exchange_code: str
    as_of_date: date
    requested_count: int
    evaluated_count: int
    skipped_count: int
    selected: list[CandidateScore]


class CandidateBatchService:
    """?쒖꽦 醫낅ぉ???쇨큵 ?됯????먯닔???꾨낫瑜?諛섑솚?쒕떎."""

    def __init__(self, session: Session) -> None:
        self._session = session
        price_service = PriceDailyService(
            PriceDailyRepository(session)
        )
        self._candidate_service = ScreenerService(price_service)

    def screen(
        self,
        *,
        exchange_code: str,
        as_of_date: date,
        limit: int = 30,
        minimum_score: float = 0,
        require_all_rules: bool = False,
    ) -> BatchScreeningResult:
        if limit <= 0:
            raise ValueError("limit must be greater than zero")

        if not 0 <= minimum_score <= 100:
            raise ValueError(
                "minimum_score must be between 0 and 100"
            )

        normalized_exchange = exchange_code.strip().upper()

        stmt = (
            select(Instrument)
            .where(
                Instrument.exchange_code == normalized_exchange,
                Instrument.is_active.is_(True),
            )
            .order_by(Instrument.symbol.asc())
        )

        instruments = list(self._session.scalars(stmt))
        scored: list[CandidateScore] = []
        skipped_count = 0

        for instrument in instruments:
            try:
                score = self._candidate_service.evaluate(
                    exchange_code=normalized_exchange,
                    symbol=instrument.symbol,
                    as_of_date=as_of_date,
                )
            except (InstrumentNotFoundError, ValueError) as exc:
                skipped_count += 1
                logger.warning(
                    "candidate_screening_skipped",
                    exchange_code=normalized_exchange,
                    symbol=instrument.symbol,
                    reason=str(exc),
                )
                continue

            if score.total_score < minimum_score:
                continue

            if require_all_rules and not score.rules.passed:
                continue

            scored.append(score)

        scored.sort(
            key=lambda item: (
                item.total_score,
                item.rules.passed_count,
                item.symbol,
            ),
            reverse=True,
        )

        selected = scored[:limit]

        logger.info(
            "candidate_batch_screening_completed",
            exchange_code=normalized_exchange,
            as_of_date=as_of_date.isoformat(),
            requested_count=len(instruments),
            evaluated_count=len(scored),
            skipped_count=skipped_count,
            selected_count=len(selected),
        )

        return BatchScreeningResult(
            exchange_code=normalized_exchange,
            as_of_date=as_of_date,
            requested_count=len(instruments),
            evaluated_count=len(scored),
            skipped_count=skipped_count,
            selected=selected,
        )

