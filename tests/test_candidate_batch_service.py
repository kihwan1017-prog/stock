from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from stock_platform.screener.batch_service import (
    CandidateBatchService,
)


class FakeSession:
    def scalars(self, stmt):
        return [
            SimpleNamespace(
                symbol="005930",
                exchange_code="KRX",
                is_active=True,
            ),
            SimpleNamespace(
                symbol="000660",
                exchange_code="KRX",
                is_active=True,
            ),
        ]


class FakeCandidateService:
    def evaluate(
        self,
        *,
        exchange_code: str,
        symbol: str,
        as_of_date: date,
    ):
        score = (
            Decimal("90")
            if symbol == "000660"
            else Decimal("80")
        )

        rules = SimpleNamespace(
            passed_count=6,
            passed=True,
        )

        return SimpleNamespace(
            exchange_code=exchange_code,
            symbol=symbol,
            trade_date=as_of_date,
            total_score=score,
            rules=rules,
        )


def test_batch_service_sorts_by_score() -> None:
    service = CandidateBatchService.__new__(
        CandidateBatchService
    )
    service._session = FakeSession()  # type: ignore[attr-defined]
    service._candidate_service = FakeCandidateService()  # type: ignore[attr-defined]

    result = service.screen(
        exchange_code="KRX",
        as_of_date=date(2026, 7, 13),
        limit=30,
    )

    assert [item.symbol for item in result.selected] == [
        "000660",
        "005930",
    ]
    assert result.requested_count == 2
    assert result.evaluated_count == 2


def test_batch_service_applies_minimum_score() -> None:
    service = CandidateBatchService.__new__(
        CandidateBatchService
    )
    service._session = FakeSession()  # type: ignore[attr-defined]
    service._candidate_service = FakeCandidateService()  # type: ignore[attr-defined]

    result = service.screen(
        exchange_code="KRX",
        as_of_date=date(2026, 7, 13),
        minimum_score=85,
    )

    assert [item.symbol for item in result.selected] == [
        "000660",
    ]
