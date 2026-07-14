import asyncio
from decimal import Decimal

from stock_platform.realtime.ai_models import (
    RealtimeAiAction,
    RealtimeAiReviewRequest,
)
from stock_platform.realtime.ai_service import (
    RealtimeAiReviewService,
)


class FakeOllamaClient:
    async def generate(self, **kwargs):
        return {
            "response": (
                '{"action":"REDUCE",'
                '"score":42,'
                '"confidence":0.82,'
                '"summary":"단기 위험 증가",'
                '"risk_factors":["변동성 확대"]}'
            )
        }


def test_realtime_ai_review_parses_json() -> None:
    service = RealtimeAiReviewService.__new__(
        RealtimeAiReviewService
    )
    service._session = object()
    service._ollama_client = FakeOllamaClient()
    service._settings = type(
        "Settings",
        (),
        {"ollama_model": "test-model"},
    )()

    async def fake_context(request):
        return {
            "symbol": request.symbol,
            "news": [],
            "disclosures": [],
        }

    service._load_context = fake_context

    result = asyncio.run(
        service.review(
            RealtimeAiReviewRequest(
                exchange_code="KRX",
                symbol="005930",
                current_price=Decimal("72000"),
                current_quantity=Decimal("10"),
                average_entry_price=Decimal("70000"),
            )
        )
    )

    assert result.action == RealtimeAiAction.REDUCE
    assert result.score == Decimal("42")
    assert result.confidence == Decimal("0.82")
    assert result.risk_factors == ["변동성 확대"]
