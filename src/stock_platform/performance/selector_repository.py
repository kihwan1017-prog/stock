from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.performance.selector_entities import (
    StrategySelectionRunEntity,
)
from stock_platform.performance.selector_models import (
    StrategySelectionCandidate,
    StrategySelectionDecision,
)


class StrategySelectionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def save(
        self,
        *,
        market_code: str,
        symbol: str | None,
        run_type: str | None,
        decision: StrategySelectionDecision,
        candidates: list[StrategySelectionCandidate],
    ) -> StrategySelectionRunEntity:
        entity = StrategySelectionRunEntity(
            market_code=market_code.upper(),
            symbol=(
                symbol.upper()
                if symbol
                else None
            ),
            run_type=(
                run_type.upper()
                if run_type
                else None
            ),
            model_name=decision.model_name,
            status_code=decision.status.value,
            selected_strategy_code=(
                decision.selected_strategy_code
            ),
            selected_performance_run_id=(
                decision.selected_performance_run_id
            ),
            confidence_score=(
                decision.confidence_score
            ),
            reason=decision.reason,
            risk_notes=decision.risk_notes,
            alternatives=decision.alternatives,
            candidate_payload=[
                {
                    "rank": item.rank,
                    "strategy_code": item.strategy_code,
                    "strategy_performance_run_id": (
                        item.strategy_performance_run_id
                    ),
                    "score": str(item.score),
                    "total_return_rate": str(
                        item.total_return_rate
                    ),
                    "maximum_drawdown_rate": str(
                        item.maximum_drawdown_rate
                    ),
                    "sharpe_ratio": (
                        str(item.sharpe_ratio)
                        if item.sharpe_ratio is not None
                        else None
                    ),
                    "win_rate": str(item.win_rate),
                    "total_trade_count": (
                        item.total_trade_count
                    ),
                }
                for item in candidates
            ],
            response_payload=decision.raw_response,
        )
        self._session.add(entity)
        self._session.commit()
        self._session.refresh(entity)
        return entity

    def latest(
        self,
        *,
        market_code: str | None = None,
        symbol: str | None = None,
    ):
        statement = select(
            StrategySelectionRunEntity
        )

        if market_code:
            statement = statement.where(
                StrategySelectionRunEntity.market_code
                == market_code.upper()
            )

        if symbol:
            statement = statement.where(
                StrategySelectionRunEntity.symbol
                == symbol.upper()
            )

        return self._session.scalar(
            statement.order_by(
                StrategySelectionRunEntity.created_at.desc(),
                StrategySelectionRunEntity
                .strategy_selection_run_id.desc(),
            ).limit(1)
        )
