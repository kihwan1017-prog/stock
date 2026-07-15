from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from stock_platform.performance.ranking_service import (
    StrategyPerformanceRankingService,
)
from stock_platform.performance.selector_llm import (
    OllamaStrategySelectorClient,
)
from stock_platform.performance.selector_models import (
    StrategySelectionCandidate,
    StrategySelectionDecision,
    StrategySelectionStatus,
)
from stock_platform.performance.selector_prompt import (
    StrategySelectorPromptBuilder,
)
from stock_platform.performance.selector_repository import (
    StrategySelectionRepository,
)


class LlmStrategySelectionService:
    def __init__(
        self,
        *,
        session: Session,
        llm_client: OllamaStrategySelectorClient,
    ) -> None:
        self._ranking = StrategyPerformanceRankingService(
            session
        )
        self._repository = StrategySelectionRepository(
            session
        )
        self._llm_client = llm_client

    async def select(
        self,
        *,
        market_code: str,
        symbol: str | None,
        run_type: str | None,
        minimum_trade_count: int,
        candidate_limit: int,
        market_context: dict[str, Any],
        risk_context: dict[str, Any],
    ):
        ranking = self._ranking.rank(
            run_type=run_type,
            market_code=market_code,
            symbol=symbol,
            minimum_trade_count=minimum_trade_count,
            limit=candidate_limit,
        )

        if not ranking:
            raise LookupError(
                "No eligible strategy performance candidates"
            )

        candidates = [
            StrategySelectionCandidate(
                rank=item.rank,
                strategy_code=item.strategy_code,
                strategy_performance_run_id=(
                    item.strategy_performance_run_id
                ),
                market_code=item.market_code,
                symbol=item.symbol,
                run_type=item.run_type,
                score=item.score,
                total_return_rate=(
                    item.total_return_rate
                ),
                maximum_drawdown_rate=(
                    item.maximum_drawdown_rate
                ),
                sharpe_ratio=item.sharpe_ratio,
                sortino_ratio=item.sortino_ratio,
                win_rate=item.win_rate,
                profit_factor=item.profit_factor,
                total_trade_count=(
                    item.total_trade_count
                ),
            )
            for item in ranking
        ]

        prompt = StrategySelectorPromptBuilder.build(
            candidates=candidates,
            market_context=market_context,
            risk_context=risk_context,
        )

        try:
            response = await self._llm_client.select(
                prompt=prompt
            )
            decision = self._parse_decision(
                response=response,
                candidates=candidates,
                model_name=self._llm_client.model_name,
            )
        except Exception as exc:
            decision = self._fallback(
                candidates=candidates,
                model_name=self._llm_client.model_name,
                error=str(exc),
            )

        return self._repository.save(
            market_code=market_code,
            symbol=symbol,
            run_type=run_type,
            decision=decision,
            candidates=candidates,
        )

    @staticmethod
    def _parse_decision(
        *,
        response: dict[str, Any],
        candidates: list[StrategySelectionCandidate],
        model_name: str,
    ) -> StrategySelectionDecision:
        selected_code = str(
            response.get(
                "selected_strategy_code",
                "",
            )
        ).strip()
        selected_run_id = int(
            response.get(
                "selected_performance_run_id",
                0,
            )
        )

        candidate = next(
            (
                item
                for item in candidates
                if item.strategy_code == selected_code
                and item.strategy_performance_run_id
                == selected_run_id
            ),
            None,
        )

        if candidate is None:
            raise ValueError(
                "LLM selected a strategy outside the candidate set"
            )

        confidence = Decimal(
            str(
                response.get(
                    "confidence_score",
                    "0",
                )
            )
        )

        if confidence < 0 or confidence > 1:
            raise ValueError(
                "confidence_score must be between 0 and 1"
            )

        reason = str(
            response.get("reason", "")
        ).strip()

        if not reason:
            raise ValueError(
                "LLM decision reason is required"
            )

        risk_notes = response.get("risk_notes", [])
        alternatives = response.get(
            "alternatives",
            [],
        )

        return StrategySelectionDecision(
            status=StrategySelectionStatus.SELECTED,
            selected_strategy_code=selected_code,
            selected_performance_run_id=selected_run_id,
            confidence_score=confidence,
            reason=reason,
            risk_notes=[
                str(item)
                for item in risk_notes
            ],
            alternatives=[
                str(item)
                for item in alternatives
                if str(item) != selected_code
            ],
            model_name=model_name,
            selected_at=datetime.now(timezone.utc),
            raw_response=response,
        )

    @staticmethod
    def _fallback(
        *,
        candidates: list[StrategySelectionCandidate],
        model_name: str,
        error: str,
    ) -> StrategySelectionDecision:
        top = candidates[0]

        return StrategySelectionDecision(
            status=StrategySelectionStatus.FALLBACK,
            selected_strategy_code=(
                top.strategy_code
            ),
            selected_performance_run_id=(
                top.strategy_performance_run_id
            ),
            confidence_score=Decimal("0.50"),
            reason=(
                "LLM selection failed; selected the "
                "highest-ranked deterministic candidate"
            ),
            risk_notes=[
                f"LLM error: {error}",
                "Operator review is recommended",
            ],
            alternatives=[
                item.strategy_code
                for item in candidates[1:4]
            ],
            model_name=model_name,
            selected_at=datetime.now(timezone.utc),
            raw_response={
                "fallback": True,
                "error": error,
            },
        )
