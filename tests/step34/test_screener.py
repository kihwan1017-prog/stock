from datetime import date
from decimal import Decimal
from stock_platform.indicator.models import IndicatorValue
from stock_platform.screener.service import ScreenerService

def test_filter_candidates() -> None:
    service = ScreenerService()
    selected = IndicatorValue("KRX", "005930", date(2026, 7, 17), Decimal("71000"), Decimal("70000"), None, Decimal("55"))
    excluded = IndicatorValue("KRX", "000660", date(2026, 7, 17), Decimal("120000"), Decimal("125000"), None, Decimal("35"))
    assert service.filter_candidates([selected, excluded]) == [selected]
