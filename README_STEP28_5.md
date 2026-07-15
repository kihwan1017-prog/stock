# STEP28-5 키움 실시간 주문체결 WebSocket

키움 WebSocket에서 주문 접수·부분체결·완전체결·취소·거부
이벤트를 수신하고 `trading.broker_pending_order`에 즉시 반영합니다.

## 공식 도메인

키움 공식 WebSocket 가이드에서 운영·모의 WebSocket 도메인은
다음 형태로 안내됩니다.

```text
운영: wss://api.kiwoom.com:10000
모의: wss://mockapi.kiwoom.com:10000
```

정확한 국내주식 주문체결 WebSocket 경로와 구독 JSON은 현재
키움 공식 가이드 또는 계정에 제공되는 샘플에서 확인해야 합니다.

잘못된 추정값으로 실계좌 연결하지 않도록 코드에 구독 메시지
기본값을 넣지 않았습니다.

## 환경변수

```dotenv
KIWOOM_USE_MOCK=true
KIWOOM_LIVE_ORDER_ENABLED=false

KIWOOM_ORDER_WS_URL=wss://mockapi.kiwoom.com:10000
KIWOOM_ORDER_WS_PATH=공식문서에서_확인한_경로

KIWOOM_ORDER_WS_SUBSCRIBE_JSON={"공식문서에서":"복사한 구독 JSON"}
```

`KIWOOM_ORDER_WS_SUBSCRIBE_JSON`이 비어 있으면 시작되지 않습니다.

## 포함 기능

```text
OAuth 토큰 사용
WebSocket 연결
주문체결 구독
자동 Ping
자동 재접속
지수 백오프
주문 이벤트 Mapper
DB 즉시 반영
내부 이벤트 버스
최근 처리 이력
상태 API
```

## 적용 파일

```text
src/stock_platform/broker/kiwoom/ws_models.py
src/stock_platform/broker/kiwoom/ws_mapper.py
src/stock_platform/broker/kiwoom/ws_client.py
src/stock_platform/broker/kiwoom/ws_service.py
src/stock_platform/broker/kiwoom/ws_runtime.py
src/stock_platform/broker/kiwoom/ws_manager.py
src/stock_platform/broker/order_event_bus.py
src/stock_platform/api/v1/kiwoom_order_websocket.py
tests/test_kiwoom_order_execution_mapper.py
```

신규 테이블은 없습니다. STEP28-4의 다음 테이블을 사용합니다.

```text
trading.broker_pending_order
```

## router.py

```python
from stock_platform.api.v1.kiwoom_order_websocket import (
    router as kiwoom_order_websocket_router,
)

api_router.include_router(
    kiwoom_order_websocket_router
)
```

## main.py 종료 처리

```python
from stock_platform.broker.kiwoom.ws_manager import (
    kiwoom_order_websocket_manager,
)
```

`lifespan` 종료 부분에서 가장 먼저 WebSocket을 종료합니다.

```python
yield

await kiwoom_order_websocket_manager.stop()
await realtime_trading_scheduler.shutdown()
await realtime_execution_runner.stop()
await realtime_strategy_runner.stop()
await realtime_manager.stop_all()
```

## API

```text
POST /api/v1/broker/kiwoom/order-websocket/start
POST /api/v1/broker/kiwoom/order-websocket/stop
GET  /api/v1/broker/kiwoom/order-websocket/status
GET  /api/v1/broker/kiwoom/order-websocket/history
```

## 테스트

```powershell
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_kiwoom_order_execution_mapper.py `
    -q
```

## Git 커밋

```powershell
git add `
    README_STEP28_5.md `
    src\stock_platform\broker\order_event_bus.py `
    src\stock_platform\broker\kiwoom\ws_models.py `
    src\stock_platform\broker\kiwoom\ws_mapper.py `
    src\stock_platform\broker\kiwoom\ws_client.py `
    src\stock_platform\broker\kiwoom\ws_service.py `
    src\stock_platform\broker\kiwoom\ws_runtime.py `
    src\stock_platform\broker\kiwoom\ws_manager.py `
    src\stock_platform\api\v1\kiwoom_order_websocket.py `
    src\stock_platform\api\router.py `
    src\stock_platform\api\main.py `
    tests\test_kiwoom_order_execution_mapper.py

git commit -m "feat(broker): add Kiwoom order execution websocket"
```

다음 단계는 STEP28-6 서버 재시작·연결장애 자동 복구입니다.
