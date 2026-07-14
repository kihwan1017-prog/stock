# STEP27-2 실시간 전략 실행기와 매수·매도 신호

STEP27-1 실시간 시세 버스를 구독해 이동평균 교차, 손절,
익절 신호를 생성합니다.

## 처리 흐름

```text
실시간 시세
    ↓
종목별 가격 이력
    ↓
이동평균 계산
    ↓
BUY / SELL / HOLD 판단
    ↓
실시간 신호 버스
    ↓
SSE 또는 다음 주문 엔진
```

## 생성 신호

```text
BUY
SELL
HOLD
```

주요 사유 코드:

```text
MA_GOLDEN_CROSS
MA_DEAD_CROSS
STOP_LOSS
TAKE_PROFIT
INSUFFICIENT_DATA
NO_SIGNAL
```

## 적용 파일

```text
src/stock_platform/realtime/strategy_models.py
src/stock_platform/realtime/strategy.py
src/stock_platform/realtime/signal_bus.py
src/stock_platform/realtime/strategy_runner.py
src/stock_platform/realtime/runtime.py
src/stock_platform/api/v1/realtime_strategy.py
tests/test_realtime_strategy_engine.py
```

신규 테이블은 없어 Alembic 작업은 필요 없습니다.

## router.py 추가

```python
from stock_platform.api.v1.realtime_strategy import (
    router as realtime_strategy_router,
)
```

```python
api_router.include_router(
    realtime_strategy_router
)
```

## main.py 종료 처리 추가

기존 lifespan 종료 부분에 실시간 전략 종료도 추가합니다.

```python
from stock_platform.realtime.runtime import (
    realtime_strategy_runner,
)
```

```python
yield

await realtime_strategy_runner.stop()
await realtime_manager.stop_all()
```

종료 순서는 전략 실행기 먼저, 시세 클라이언트 나중을 권장합니다.

## 실행 순서

1. FastAPI 실행
2. 실시간 전략 실행기 시작
3. 업비트 시세 수신 시작

실시간 전략 시작:

```text
POST /api/v1/realtime-strategy/start
```

업비트 시세 시작:

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

## 전략 상태

```text
GET /api/v1/realtime-strategy/status
```

## 현재 보유상태 등록

손절·익절 판단을 위해 종목별 보유 상태를 등록합니다.

```text
PUT /api/v1/realtime-strategy/positions
```

```json
{
  "exchange_code": "UPBIT",
  "symbol": "KRW-BTC",
  "quantity": 0.01,
  "average_entry_price": 150000000
}
```

미보유 상태:

```json
{
  "exchange_code": "UPBIT",
  "symbol": "KRW-BTC",
  "quantity": 0,
  "average_entry_price": null
}
```

## 보유상태 조회

```text
GET /api/v1/realtime-strategy/positions/UPBIT/KRW-BTC
```

## 실시간 신호 SSE

```text
GET /api/v1/realtime-strategy/signals/sse
```

## 전략 중지

```text
POST /api/v1/realtime-strategy/stop
```

## 기본 전략 설정

현재 기본값:

```text
단기 이동평균: 5
장기 이동평균: 20
손절: 3%
익절: 6%
동일 종목 신호 쿨다운: 30초
```

전략 설정의 환경변수화와 DB 저장은 이후 단계에서 연결합니다.

## 테스트

```powershell
cd D:\Projects\stock-platform
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_realtime_strategy_engine.py `
    -q
```

## Git 커밋

```powershell
git add `
    README_STEP27_2.md `
    src\stock_platform\realtime\strategy_models.py `
    src\stock_platform\realtime\strategy.py `
    src\stock_platform\realtime\signal_bus.py `
    src\stock_platform\realtime\strategy_runner.py `
    src\stock_platform\realtime\runtime.py `
    src\stock_platform\api\v1\realtime_strategy.py `
    src\stock_platform\api\router.py `
    src\stock_platform\api\main.py `
    tests\test_realtime_strategy_engine.py

git commit -m "feat(realtime): add realtime strategy signals"
```

다음 단계는 STEP27-3 실시간 신호를 모의 주문으로 연결하는
주문 실행기입니다. 실제 주문은 아직 전송하지 않습니다.
