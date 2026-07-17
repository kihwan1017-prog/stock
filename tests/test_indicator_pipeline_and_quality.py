from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

from stock_platform.indicators.engine import IndicatorEngine
from stock_platform.indicators.models import PriceBar
from stock_platform.indicators.pipeline_service import (
    IndicatorPipelineService,
)
from stock_platform.markets.quality_service import (
    MarketDataQualityService,
)

def _bars(count: int = 80) -> list[PriceBar]:
    start = date(2026, 1, 1)
    return [
        PriceBar(
            trade_date=start + timedelta(days=index),
            open_price=Decimal(100 + index),
            high_price=Decimal(102 + index),
            low_price=Decimal(98 + index),
            close_price=Decimal(101 + index),
            volume=Decimal(1000 + index * 10),
        )
        for index in range(count)
    ]


def test_status_is_partial_before_52w() -> None:
    result = IndicatorEngine().calculate(_bars(80))
    latest = result[-1]
    assert latest.ma60 is not None
    assert latest.high_52w is None
    assert latest.status_code == "PARTIAL"
    assert "high_52w" in latest.missing_fields


def test_status_ready_with_252_bars() -> None:
    result = IndicatorEngine().calculate(_bars(260))
    latest = result[-1]
    assert latest.high_52w is not None
    assert latest.low_52w is not None
    assert latest.status_code == "READY"
    assert latest.missing_fields == ()


def test_pipeline_persists_rows() -> None:
    class FakePriceService:
        def get_between(self, **kwargs):
            return [
                SimpleNamespace(
                    trade_date=date(2026, 1, 1) + timedelta(days=i),
                    open_price=Decimal(100 + i),
                    high_price=Decimal(102 + i),
                    low_price=Decimal(98 + i),
                    close_price=Decimal(101 + i),
                    volume=Decimal(1000),
                )
                for i in range(30)
            ]

    class FakeRepo:
        def __init__(self) -> None:
            self.rows: list[dict] = []

        def upsert_many(self, rows):
            self.rows = list(rows)
            return len(self.rows)

        def list_between(self, *args, **kwargs):
            return []

    class FakeInstruments:
        def get(self, exchange_code, symbol):
            return SimpleNamespace(
                instrument_id=7,
                exchange_code=exchange_code,
                symbol=symbol,
            )

        def list(self, **kwargs):
            return [
                SimpleNamespace(
                    instrument_id=7,
                    exchange_code="UPBIT",
                    symbol="KRW-BTC",
                )
            ]

    repo = FakeRepo()
    pipeline = IndicatorPipelineService(
        price_service=FakePriceService(),  # type: ignore[arg-type]
        indicator_repository=repo,  # type: ignore[arg-type]
        instrument_service=FakeInstruments(),  # type: ignore[arg-type]
    )

    result = pipeline.compute_and_save(
        exchange_code="UPBIT",
        symbol="KRW-BTC",
        start_date=date(2026, 1, 10),
        end_date=date(2026, 1, 30),
    )

    assert result.saved_count == len(repo.rows)
    assert result.computed_count > 0
    assert repo.rows[0]["instrument_id"] == 7
    assert "status_code" in repo.rows[0]


def test_quality_detects_ohlc_and_negative() -> None:
    instrument = SimpleNamespace(
        exchange_code="UPBIT",
        symbol="KRW-BTC",
        instrument_id=1,
    )
    rows = [
        SimpleNamespace(
            trade_date=date(2026, 1, 1),
            open_price=Decimal("100"),
            high_price=Decimal("90"),
            low_price=Decimal("95"),
            close_price=Decimal("100"),
            volume=Decimal("-1"),
            trade_value=Decimal("0"),
        ),
        SimpleNamespace(
            trade_date=date(2026, 1, 10),
            open_price=Decimal("100"),
            high_price=Decimal("110"),
            low_price=Decimal("90"),
            close_price=Decimal("105"),
            volume=Decimal("1"),
            trade_value=Decimal("1"),
        ),
    ]

    service = MarketDataQualityService.__new__(
        MarketDataQualityService
    )
    issues = service._check_price_rows(  # type: ignore[arg-type]
        instrument,  # type: ignore[arg-type]
        rows,  # type: ignore[arg-type]
        default_max_gap_days=3,
    )

    types = {item.issue_type for item in issues}
    assert "OHLC_LOGIC" in types
    assert "NEGATIVE_VALUE" in types
    assert "MISSING_DAYS" in types
