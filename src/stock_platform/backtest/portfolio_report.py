from stock_platform.backtest.portfolio_models import PortfolioBacktestResult
class PortfolioBacktestReportBuilder:
    @staticmethod
    def build(result: PortfolioBacktestResult)->str:
        s=result.summary
        lines=[f'포트폴리오 백테스트 {result.start_date}~{result.end_date}',f'초기자본={s.initial_capital}, 최종자산={s.final_equity}, 총손익={s.total_profit_loss}, 수익률={s.total_return_rate}%, MDD={s.maximum_drawdown_rate}%',f'종목수={s.asset_count}, 수익종목={s.profitable_asset_count}, 손실종목={s.losing_asset_count}, 미배분현금={s.unallocated_capital}','']
        for x in sorted(result.assets,key=lambda v:v.total_return_rate,reverse=True):
            lines.append(f'{x.exchange_code}/{x.symbol}: 비중={x.weight}, 배분금액={x.allocated_capital}, 수익률={x.total_return_rate}%, MDD={x.maximum_drawdown_rate}%, 거래={x.trade_count}회, 승률={x.win_rate}%')
        if result.failures: lines += ['',f'실패 종목={len(result.failures)}개']
        return '
'.join(lines)
