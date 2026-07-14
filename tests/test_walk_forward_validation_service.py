from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from stock_platform.backtest.walk_forward_service import WalkForwardValidationService

def test_build_windows():
    windows=WalkForwardValidationService._build_windows(start_date=date(2023,1,1),end_date=date(2024,6,30),train_months=12,test_months=3)
    assert len(windows)==2
    assert windows[1].train_start_date==date(2023,4,1)
    assert windows[1].train_end_date==date(2024,3,31)
    assert windows[1].test_start_date==date(2024,4,1)
    assert windows[1].test_end_date==date(2024,6,30)

def test_summary_compounds_test_returns():
    p=SimpleNamespace(short_window=5,long_window=20,stop_loss_ratio=Decimal('0.05'),take_profit_ratio=Decimal('0.10'),position_ratio=Decimal('0.20'))
    rows=[SimpleNamespace(test_return_rate=Decimal('10'),test_maximum_drawdown_rate=Decimal('5'),selected_parameters=p),SimpleNamespace(test_return_rate=Decimal('-5'),test_maximum_drawdown_rate=Decimal('6'),selected_parameters=p)]
    s=WalkForwardValidationService._build_summary(total_window_count=2,results=rows,failures=[])
    assert s.compounded_test_return_rate==Decimal('4.5000')
