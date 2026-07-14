from __future__ import annotations

from decimal import Decimal

from stock_platform.ai.ollama_client import OllamaClient
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory
from stock_platform.realtime.ai_models import (
    RealtimeAiReviewRequest,
)
from stock_platform.realtime.ai_service import (
    RealtimeAiReviewService,
)
from stock_platform.realtime.runtime import (
    realtime_strategy_runner,
)


class RealtimeAiReviewRunner:
    """현재 실시간 보유 상태를 AI로 재평가하고 전략 상태에 반영한다."""

    async def review_symbol(
        self,
        *,
        exchange_code: str,
        symbol: str,
        current_price: Decimal,
        news_limit: int = 10,
        disclosure_limit: int = 10,
        lookback_days: int = 30,
    ):
        position = realtime_strategy_runner.get_position(
            exchange_code=exchange_code,
            symbol=symbol,
        )

        settings = get_settings()
        session = get_session_factory()()

        try:
            async with OllamaClient(
                settings=settings
            ) as client:
                result = await RealtimeAiReviewService(
                    session=session,
                    ollama_client=client,
                ).review(
                    RealtimeAiReviewRequest(
                        exchange_code=exchange_code,
                        symbol=symbol,
                        current_price=current_price,
                        current_quantity=position.quantity,
                        average_entry_price=(
                            position.average_entry_price
                        ),
                        news_limit=news_limit,
                        disclosure_limit=(
                            disclosure_limit
                        ),
                        lookback_days=lookback_days,
                    )
                )

            return result
        finally:
            session.close()


realtime_ai_review_runner = RealtimeAiReviewRunner()
