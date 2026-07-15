import asyncio

import httpx

from stock_platform.performance.selector_llm import (
    OllamaStrategySelectorClient,
)


def test_parses_ollama_json_response() -> None:
    async def handler(request):
        return httpx.Response(
            200,
            json={
                "response": (
                    '{"selected_strategy_code":"A",'
                    '"selected_performance_run_id":1,'
                    '"confidence_score":0.8,'
                    '"reason":"ok",'
                    '"risk_notes":[],'
                    '"alternatives":[]}'
                )
            },
        )

    async def run():
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        )
        selector = OllamaStrategySelectorClient(
            base_url="http://localhost:11434",
            model_name="test",
            client=client,
        )
        result = await selector.select(
            prompt="test"
        )
        await client.aclose()
        return result

    result = asyncio.run(run())

    assert result["selected_strategy_code"] == "A"
    assert result["selected_performance_run_id"] == 1
