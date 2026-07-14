from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.backtest.models import BacktestResult
from stock_platform.backtest.persistence_models import (
    BacktestEquityEntity,
    BacktestRunEntity,
    BacktestTradeEntity,
)


class BacktestRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def save_result(
        self,
        *,
        result: BacktestResult,
        strategy_code: str,
        parameters: dict,
    ) -> BacktestRunEntity:
        run = BacktestRunEntity(
            strategy_code=strategy_code,
            exchange_code=result.exchange_code,
            symbol=result.symbol,
            start_date=result.start_date,
            end_date=result.end_date,
            initial_capital=result.summary.initial_capital,
            final_equity=result.summary.final_equity,
            total_profit_loss=result.summary.total_profit_loss,
            total_return_rate=result.summary.total_return_rate,
            maximum_drawdown_rate=(
                result.summary.maximum_drawdown_rate
            ),
            trade_count=result.summary.trade_count,
            win_count=result.summary.win_count,
            loss_count=result.summary.loss_count,
            win_rate=result.summary.win_rate,
            average_trade_return_rate=(
                result.summary.average_trade_return_rate
            ),
            parameters=parameters,
            status_code="SUCCESS",
        )

        self._session.add(run)
        self._session.flush()

        for trade_no, trade in enumerate(
            result.trades,
            start=1,
        ):
            self._session.add(
                BacktestTradeEntity(
                    backtest_run_id=run.backtest_run_id,
                    trade_no=trade_no,
                    entry_date=trade.entry_date,
                    exit_date=trade.exit_date,
                    quantity=trade.quantity,
                    entry_price=trade.entry_price,
                    exit_price=trade.exit_price,
                    gross_profit_loss=trade.gross_profit_loss,
                    fee_amount=trade.fee_amount,
                    tax_amount=trade.tax_amount,
                    net_profit_loss=trade.net_profit_loss,
                    return_rate=trade.return_rate,
                    entry_reason=trade.entry_reason,
                    exit_reason=trade.exit_reason,
                )
            )

        for trade_date, equity_value in result.equity_curve:
            self._session.add(
                BacktestEquityEntity(
                    backtest_run_id=run.backtest_run_id,
                    trade_date=trade_date,
                    equity_value=equity_value,
                )
            )

        self._session.commit()
        self._session.refresh(run)
        return run

    def get_run(
        self,
        backtest_run_id: int,
    ) -> BacktestRunEntity | None:
        return self._session.get(
            BacktestRunEntity,
            backtest_run_id,
        )

    def get_trades(
        self,
        backtest_run_id: int,
    ) -> list[BacktestTradeEntity]:
        stmt = (
            select(BacktestTradeEntity)
            .where(
                BacktestTradeEntity.backtest_run_id
                == backtest_run_id
            )
            .order_by(
                BacktestTradeEntity.trade_no.asc()
            )
        )
        return list(self._session.scalars(stmt))

    def get_equity_curve(
        self,
        backtest_run_id: int,
    ) -> list[BacktestEquityEntity]:
        stmt = (
            select(BacktestEquityEntity)
            .where(
                BacktestEquityEntity.backtest_run_id
                == backtest_run_id
            )
            .order_by(
                BacktestEquityEntity.trade_date.asc()
            )
        )
        return list(self._session.scalars(stmt))

    def list_runs(
        self,
        *,
        exchange_code: str | None = None,
        symbol: str | None = None,
        strategy_code: str | None = None,
        limit: int = 100,
    ) -> list[BacktestRunEntity]:
        stmt = select(BacktestRunEntity)

        if exchange_code:
            stmt = stmt.where(
                BacktestRunEntity.exchange_code
                == exchange_code.upper()
            )

        if symbol:
            stmt = stmt.where(
                BacktestRunEntity.symbol == symbol.upper()
            )

        if strategy_code:
            stmt = stmt.where(
                BacktestRunEntity.strategy_code
                == strategy_code.upper()
            )

        stmt = stmt.order_by(
            BacktestRunEntity.created_at.desc(),
            BacktestRunEntity.backtest_run_id.desc(),
        ).limit(limit)

        return list(self._session.scalars(stmt))
