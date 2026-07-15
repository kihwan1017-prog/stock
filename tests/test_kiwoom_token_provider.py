import asyncio, httpx
from stock_platform.broker.kiwoom.auth import KiwoomTokenProvider
from stock_platform.broker.kiwoom.config import KiwoomBrokerConfig

def test_token_provider():
    async def handler(request):
        return httpx.Response(200, json={"expires_dt":"20991231235959","token_type":"bearer","token":"abc","return_code":0})
    async def run():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = KiwoomTokenProvider(KiwoomBrokerConfig("key","secret"), client)
        token = await provider.get_token()
        await client.aclose()
        assert token.token == "abc"
    asyncio.run(run())
