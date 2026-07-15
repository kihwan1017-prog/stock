from datetime import datetime, timezone
from typing import Any
from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.performance.dashboard_models import StrategyPerformanceDashboardSnapshot
from stock_platform.performance.entities import StrategyPerformanceMetricEntity, StrategyPerformanceRunEntity
from stock_platform.performance.leaderboard_repository import StrategyLeaderboardRepository
from stock_platform.performance.ranking_service import StrategyPerformanceRankingService
from stock_platform.performance.selector_repository import StrategySelectionRepository
from stock_platform.performance.summary_service import StrategyPerformanceSummaryService
from stock_platform.performance.walk_forward_repository import WalkForwardWindowMetricRepository
from stock_platform.performance.walk_forward_stability import WalkForwardStabilityAnalyzer

class StrategyPerformanceDashboardService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def build(self, *, run_type=None, market_code=None, symbol=None,
              minimum_trade_count=1, ranking_limit=20,
              history_limit=20, recent_run_limit=20):
        ranking_items = StrategyPerformanceRankingService(self._session).rank(
            run_type=run_type, market_code=market_code, symbol=symbol,
            minimum_trade_count=minimum_trade_count, limit=ranking_limit,
        )
        summary = StrategyPerformanceSummaryService(self._session).summarize(
            strategy_code=None, run_type=run_type, market_code=market_code,
        )
        latest_selection = StrategySelectionRepository(self._session).latest(
            market_code=market_code, symbol=symbol,
        )
        leaderboard_history = StrategyLeaderboardRepository(self._session).list_history(
            run_type=run_type, market_code=market_code, symbol=symbol, limit=history_limit,
        )
        return StrategyPerformanceDashboardSnapshot(
            generated_at=datetime.now(timezone.utc),
            filters={
                "run_type": run_type, "market_code": market_code, "symbol": symbol,
                "minimum_trade_count": minimum_trade_count,
                "ranking_limit": ranking_limit, "history_limit": history_limit,
                "recent_run_limit": recent_run_limit,
            },
            summary=summary,
            ranking=[{
                "rank": x.rank, "strategy_code": x.strategy_code,
                "market_code": x.market_code, "symbol": x.symbol,
                "run_type": x.run_type, "score": str(x.score),
                "total_return_rate": str(x.total_return_rate),
                "maximum_drawdown_rate": str(x.maximum_drawdown_rate),
                "sharpe_ratio": str(x.sharpe_ratio) if x.sharpe_ratio is not None else None,
                "sortino_ratio": str(x.sortino_ratio) if x.sortino_ratio is not None else None,
                "win_rate": str(x.win_rate),
                "profit_factor": str(x.profit_factor) if x.profit_factor is not None else None,
                "total_trade_count": x.total_trade_count,
                "strategy_performance_run_id": x.strategy_performance_run_id,
            } for x in ranking_items],
            latest_selection=self._selection_to_dict(latest_selection) if latest_selection else None,
            leaderboard_history=[{
                "strategy_leaderboard_snapshot_id": x.strategy_leaderboard_snapshot_id,
                "snapshot_date": x.snapshot_date, "run_type": x.run_type,
                "market_code": x.market_code, "symbol": x.symbol,
                "minimum_trade_count": x.minimum_trade_count,
                "strategy_count": x.strategy_count, "generated_at": x.generated_at,
            } for x in leaderboard_history],
            recent_runs=self._recent_runs(
                run_type=run_type, market_code=market_code,
                symbol=symbol, limit=recent_run_limit,
            ),
            walk_forward_stability=self._walk_forward_stability(ranking_items),
        )

    def _recent_runs(self, *, run_type, market_code, symbol, limit):
        stmt = select(
            StrategyPerformanceRunEntity,
            StrategyPerformanceMetricEntity,
        ).outerjoin(
            StrategyPerformanceMetricEntity,
            StrategyPerformanceMetricEntity.strategy_performance_run_id
            == StrategyPerformanceRunEntity.strategy_performance_run_id,
        )
        if run_type:
            stmt = stmt.where(StrategyPerformanceRunEntity.run_type == run_type.upper())
        if market_code:
            stmt = stmt.where(StrategyPerformanceRunEntity.market_code == market_code.upper())
        if symbol:
            stmt = stmt.where(StrategyPerformanceRunEntity.symbol == symbol.upper())
        rows = self._session.execute(
            stmt.order_by(
                StrategyPerformanceRunEntity.started_at.desc(),
                StrategyPerformanceRunEntity.strategy_performance_run_id.desc(),
            ).limit(limit)
        ).all()
        return [{
            "strategy_performance_run_id": run.strategy_performance_run_id,
            "strategy_code": run.strategy_code, "run_type": run.run_type,
            "status_code": run.status_code, "market_code": run.market_code,
            "symbol": run.symbol, "period_start_date": run.period_start_date,
            "period_end_date": run.period_end_date, "started_at": run.started_at,
            "completed_at": run.completed_at,
            "total_return_rate": str(metric.total_return_rate) if metric else None,
            "maximum_drawdown_rate": str(metric.maximum_drawdown_rate) if metric else None,
            "win_rate": str(metric.win_rate) if metric else None,
            "sharpe_ratio": str(metric.sharpe_ratio) if metric and metric.sharpe_ratio is not None else None,
            "total_trade_count": metric.total_trade_count if metric else None,
        } for run, metric in rows]

    def _walk_forward_stability(self, ranking_items):
        repo = WalkForwardWindowMetricRepository(self._session)
        result = []
        for item in ranking_items:
            if item.run_type != "WALK_FORWARD":
                continue
            windows = repo.list_by_run(
                strategy_performance_run_id=item.strategy_performance_run_id
            )
            if windows:
                result.append({
                    "strategy_code": item.strategy_code,
                    "strategy_performance_run_id": item.strategy_performance_run_id,
                    "stability": WalkForwardStabilityAnalyzer.analyze(windows),
                })
        return result

    @staticmethod
    def _selection_to_dict(x):
        return {
            "strategy_selection_run_id": x.strategy_selection_run_id,
            "market_code": x.market_code, "symbol": x.symbol,
            "run_type": x.run_type, "model_name": x.model_name,
            "status_code": x.status_code,
            "selected_strategy_code": x.selected_strategy_code,
            "selected_performance_run_id": x.selected_performance_run_id,
            "confidence_score": str(x.confidence_score),
            "reason": x.reason, "risk_notes": x.risk_notes,
            "alternatives": x.alternatives, "created_at": x.created_at,
        }
