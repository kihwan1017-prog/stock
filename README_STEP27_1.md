# STEP27-1 실시간 시세 엔진

업비트 공개 WebSocket 현재가를 수신하고 종목별 최신 시세 캐시,
비동기 이벤트 버스, SSE 스트림을 제공합니다.

키움 KRX는 기존 REST 현재가 클라이언트를 연결할 수 있도록
`KrxPollingRealtimeClient` 어댑터를 포함합니다.

## 설치 패키지

```powershell
python -m pip install websockets
```

`requirements.txt`에도 추가합니다.

```text
websockets
```

## 포함 파일

```text
src/stock_platform/realtime/__init__.py
src/stock_platform/realtime/models.py
src/stock_platform/realtime/bus.py
src/stock_platform/realtime/cache.py
src/stock_platform/realtime/upbit_client.py
src/stock_platform/realtime/krx_polling.py
src/stock_platform/realtime/manager.py
src/stock_platform/api/v1/realtime_quotes.py
tests/test_realtime_quote_engine.py
```

신규 테이블은 없어 Alembic 작업은 필요 없습니다.

## router.py 추가

```python
from stock_platform.api.v1.realtime_quotes import (
    router as realtime_quotes_router,
)
```

```python
api_router.include_router(realtime_quotes_router)
```

## 업비트 실시간 수신 시작

```text
POST /api/v1/realtime-quotes/upbit/start
```

```json
{
  "symbols": [
    "KRW-BTC",
    "KRW-ETH"
  ]
}
```

## 실시간 상태

```text
GET /api/v1/realtime-quotes/status
```

## 최신 시세 조회

```text
GET /api/v1/realtime-quotes/UPBIT/KRW-BTC
GET /api/v1/realtime-quotes
```

## SSE 실시간 스트림

```text
GET /api/v1/realtime-quotes/stream/sse
```

브라우저 JavaScript 예:

```javascript
const source = new EventSource(
  "http://127.0.0.1:8000/api/v1/realtime-quotes/stream/sse"
);

source.onmessage = (event) => {
  console.log(JSON.parse(event.data));
};
```

## 업비트 수신 중지

```text
POST /api/v1/realtime-quotes/UPBIT/stop
```

## FastAPI 종료 연결

`src/stock_platform/api/main.py`의 lifespan 종료 부분에서 아래를
호출하는 것이 좋습니다.

```python
from stock_platform.realtime.manager import realtime_manager

await realtime_manager.stop_all()
```

## KRX 연결 방식

현재 ZIP에는 `KrxQuoteProvider` 프로토콜과 polling 엔진이
포함되어 있습니다.

기존 키움 REST 클라이언트에 다음 메서드를 가진 Adapter를
작성하면 연결할 수 있습니다.

```python
async def get_current_price(
    self,
    symbol: str,
) -> dict:
    return {
        "current_price": 72000,
        "opening_price": 71500,
        "high_price": 72500,
        "low_price": 71000,
        "previous_close_price": 71800,
        "change_price": 200,
        "change_rate": 0.002785,
        "accumulated_volume": 1000000
    }
```

실제 키움 주문 기능과 실시간 시세 기능은 다음 단계에서
안전 스위치와 함께 연결합니다.

## 테스트

```powershell
cd D:\Projects\stock-platform
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_realtime_quote_engine.py `
    -q
```

## Git 커밋

```powershell
git add `
    README_STEP27_1.md `
    requirements.txt `
    src\stock_platform\realtime `
    src\stock_platform\api\v1\realtime_quotes.py `
    src\stock_platform\api\router.py `
    tests\test_realtime_quote_engine.py

git commit -m "feat(realtime): add realtime market data engine"
```

다음 단계는 STEP27-2 실시간 전략 실행기와 매수·매도 신호 생성입니다.
