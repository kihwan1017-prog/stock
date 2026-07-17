from stock_platform.indicator.models import IndicatorValue

class ScreenerService:
    def filter_candidates(self, indicators: list[IndicatorValue]) -> list[IndicatorValue]:
        return [
            item for item in indicators
            if item.sma5 is not None
            and item.sma20 is not None
            and item.rsi14 is not None
            and item.sma5 > item.sma20
            and 40 <= item.rsi14 <= 70
        ]
