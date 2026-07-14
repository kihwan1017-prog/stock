from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from stock_platform.backtest.portfolio_models import PortfolioBacktestAsset
from stock_platform.backtest.portfolio_service import PortfolioBacktestService
class FakeBacktestService:
    def run_moving_average_backtest(self,**kwargs):
        initial=kwargs['initial_capital']; gain=Decimal('0.10') if kwargs['symbol']=='005930' else Decimal('-0.05'); final=(initial*(Decimal('1')+gain)).quantize(Decimal('0.01'))
        return SimpleNamespace(summary=SimpleNamespace(final_equity=final,total_profit_loss=final-initial,total_return_rate=gain*Decimal('100'),maximum_drawdown_rate=Decimal('5'),trade_count=3,win_rate=Decimal('50')),equity_curve=[(date(2026,1,1),initial),(date(2026,1,2),final)])
def test_portfolio_backtest_combines_assets():
    service=PortfolioBacktestService.__new__(PortfolioBacktestService); service._backtest_service=FakeBacktestService()
    result=service.run(assets=[PortfolioBacktestAsset('KRX','005930',Decimal('0.50')),PortfolioBacktestAsset('KRX','000660',Decimal('0.30'))],start_date=date(2026,1,1),end_date=date(2026,1,2),initial_capital=Decimal('10000000'),short_window=5,long_window=20,stop_loss_ratio=Decimal('0.05'),take_profit_ratio=Decimal('0.10'),fee_ratio=Decimal('0'),sell_tax_ratio=Decimal('0'),slippage_ratio=Decimal('0'))
    assert result.summary.invested_capital==Decimal('8000000.00')
    assert result.summary.unallocated_capital==Decimal('2000000.00')
    assert result.summary.final_equity==Decimal('10350000.00')
    assert result.summary.total_return_rate==Decimal('3.5000')
