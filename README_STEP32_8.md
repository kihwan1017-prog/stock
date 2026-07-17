# STEP32-8 키움 WebSocket 주문체결 수신 및 상태 동기화

이번 단계에서는 키움 국내주식 WebSocket의 주문체결 실시간 서비스
타입 `00`을 수신하고 로컬 주문 상태와 체결 테이블을 동기화합니다.

키움 공식 가이드 기준 국내주식 WebSocket 연결 정보:

```text
운영: wss://api.kiwoom.com:10000
모의: wss://mockapi.kiwoom.com:10000
경로: /api/dostk/websocket
주문체결 서비스 타입: 00
```

## 주요 기능

```text
OAuth 토큰으로 WebSocket 로그인
주문체결 서비스 타입 00 구독
PING 응답
자동 재연결
지수 백오프
체결 메시지 파싱
중복 체결 방지
trading.execution 저장
주문 체결수량 및 미체결수량 갱신
PARTIALLY_FILLED / FILLED 자동 전환
체결 조회 API
```

## 추가 파일

```text
src/stock_platform/broker/kiwoom/ws_config.py
src/stock_platform/broker/kiwoom/execution_models.py
src/stock_platform/broker/kiwoom/execution_parser.py
src/stock_platform/broker/kiwoom/execution_ws_client.py

src/stock_platform/trading/execution_entities.py
src/stock_platform/trading/execution_repository.py
src/stock_platform/trading/execution_sync_service.py
src/stock_platform/trading/execution_runtime.py

src/stock_platform/api/v1/executions.py

alembic/versions/step32_8_execution.py
requirements_step32_8.txt
```

## 환경변수

```dotenv
KIWOOM_USE_MOCK=true

KIWOOM_WS_URL=wss://mockapi.kiwoom.com:10000
KIWOOM_WS_PATH=/api/dostk/websocket
KIWOOM_WS_EXECUTION_TYPE=00

KIWOOM_WS_RECONNECT_MIN_SECONDS=1
KIWOOM_WS_RECONNECT_MAX_SECONDS=30
KIWOOM_WS_PING_INTERVAL_SECONDS=20
KIWOOM_WS_PING_TIMEOUT_SECONDS=10
```

이전 단계에서 문의했던 값은 다음과 같이 정리됩니다.

```text
KIWOOM_ORDER_WS_PATH=/api/dostk/websocket
```

다만 이번 구현에서는 주문용이라는 의미가 명확하도록
`KIWOOM_WS_PATH`를 사용합니다.

## 패키지 설치

```powershell
pip install "websockets>=12.0,<16.0"

# 또는
pip install -r requirements_step32_8.txt
```

## Alembic

STEP32-7 Revision ID가 실제로 `step32_7`이 아니면 아래 값을
현재 프로젝트의 Revision ID로 바꾸세요.

```python
down_revision = "step32_7"
```

적용:

```powershell
alembic upgrade head
```

`alembic/env.py`에는 Entity를 import합니다.

```python
from stock_platform.trading import execution_entities
```

## API Router 등록

```python
from stock_platform.api.v1.executions import (
    router as executions_router,
)

api_router.include_router(executions_router)
```

API:

```text
GET /api/v1/executions
GET /api/v1/orders/{order_id}/executions
```

## Runtime 연결

프로젝트의 실제 `SessionLocal` 이름에 맞게 import를 조정하세요.

```python
from stock_platform.broker.kiwoom.execution_parser import (
    KiwoomExecutionParser,
)
from stock_platform.broker.kiwoom.execution_ws_client import (
    KiwoomExecutionWebSocketClient,
)
from stock_platform.broker.kiwoom.ws_config import (
    KiwoomWebSocketConfig,
)
from stock_platform.broker.kiwoom.token_cache import (
    KiwoomTokenCache,
)
from stock_platform.broker.kiwoom.token_client import (
    KiwoomTokenClient,
)
from stock_platform.broker.kiwoom.config import (
    KiwoomOrderConfig,
)
from stock_platform.trading.execution_runtime import (
    ExecutionRuntime,
)

token_cache = KiwoomTokenCache(
    KiwoomTokenClient(
        KiwoomOrderConfig.from_env()
    )
)

runtime = None

async def handle_execution(event):
    await runtime.handle_event(event)

client = KiwoomExecutionWebSocketClient(
    config=KiwoomWebSocketConfig.from_env(),
    token_cache=token_cache,
    parser=KiwoomExecutionParser(),
    event_handler=handle_execution,
)

runtime = ExecutionRuntime(
    session_factory=SessionLocal,
    client=client,
)
```

FastAPI lifespan 시작:

```python
runtime.start()
```

종료:

```python
await runtime.shutdown()
```

## 메시지 필드 매핑 주의

키움 실시간 데이터는 문서 버전 또는 메시지 형태에 따라
필드명 또는 FID 기반 `values`로 전달될 수 있습니다.

현재 Parser는 다음 FID 별칭을 포함합니다.

```text
9203 주문번호
909  체결번호
9001 종목코드
907  매도수구분
910  체결가
911  체결량
902  미체결수량
908  주문/체결시간
```

실제 운영 전 키움 공식 가이드의 `주문체결 00` 상세 화면에서
현재 FID를 다시 대조하고 모의투자로 원문 메시지를 로그에 남겨
확인해야 합니다.

## 테스트

```powershell
$env:PYTHONPATH = "D:\\Projects\\stock-platform\\src"

python -m pytest `
  tests\\test_kiwoom_execution_parser.py `
  tests\\test_execution_ws_messages.py `
  -q
```

## Git

```powershell
git add README_STEP32_8.md `
  requirements_step32_8.txt `
  alembic\\versions\\step32_8_execution.py `
  src\\stock_platform\\broker\\kiwoom `
  src\\stock_platform\\trading `
  src\\stock_platform\\api\\v1\\executions.py `
  tests\\test_kiwoom_execution_parser.py `
  tests\\test_execution_ws_messages.py

git commit -m "feat(execution): add Kiwoom WebSocket execution sync"
```

다음 단계는 STEP32-9 Position Engine입니다.
