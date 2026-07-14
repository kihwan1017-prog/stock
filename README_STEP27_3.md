# STEP27-3 실시간 신호 → 모의 주문 실행기

STEP27-2에서 생성된 BUY·SELL 신호를 모의 주문으로 변환하고,
필요 시 즉시 모의 체결하여 `paper_account`, `paper_position`,
`paper_trade`에 반영합니다.

실제 주문은 전송하지 않습니다.

## 처리 흐름

```text
실시간 전략 신호
    ↓
RealtimeExecutionRunner
    ↓
PaperOrder 생성
    ↓
자동 체결
    ↓
모의 계좌·포지션·체결 원장 반영
```

## 기본 설정

```text
실행 모드: PAPER
모의 계좌 ID: 1
신호당 주문금액: 100,000원
자동 체결: 사용
매수: 허용
매도: 허용
```

설정 위치:

```text
src/stock_platform/realtime/runtime.py
```

## 적용 파일

```text
src/stock_platform/realtime/execution_models.py
src/stock_platform/realtime/order_executor.py
src/stock_platform/realtime/execution_runner.py
src/stock_platform/realtime/runtime.py
src/stock_platform/realtime/__init__.py
src/stock_platform/api/v1/realtime_execution.py
tests/test_realtime_paper_order_executor.py
```

신규 테이블은 없어 Alembic 작업은 필요 없습니다.

STEP24의 아래 테이블이 먼저 존재해야 합니다.

```text
trading.paper_order
trading.paper_account
trading.paper_position
trading.paper_trade
```

## router.py 추가

```python
from stock_platform.api.v1.realtime_execution import (
    router as realtime_execution_router,
)
```

```python
api_router.include_router(
    realtime_execution_router
)
```

## main.py 종료 처리

import:

```python
from stock_platform.realtime.runtime import (
    realtime_execution_runner,
    realtime_strategy_runner,
)
```

lifespan 종료 순서:

```python
yield

await realtime_execution_runner.stop()
await realtime_strategy_runner.stop()
await realtime_manager.stop_all()
```

주문 실행기 → 전략 실행기 → 시세 수신기 순서로 종료합니다.

## 실행 순서

```text
1. 모의 계좌 생성 및 account_id 확인
2. 실시간 주문 실행기 시작
3. 실시간 전략 실행기 시작
4. 업비트 또는 KRX 실시간 시세 시작
```

주문 실행기 시작:

```text
POST /api/v1/realtime-execution/start
```

전략 실행기 시작:

```text
POST /api/v1/realtime-strategy/start
```

업비트 시세 시작:

```text
POST /api/v1/realtime-quotes/upbit/start
```

## 상태·이력 API

```text
GET  /api/v1/realtime-execution/status
GET  /api/v1/realtime-execution/history
POST /api/v1/realtime-execution/stop
```

## 중요 주의사항

`runtime.py`의 기본 `account_id=1`이 실제 DB의 모의 계좌 ID와
일치해야 합니다.

존재하지 않는 계좌 ID면 체결 반영에 실패합니다.

SELL 신호는 해당 계좌에 충분한 보유수량이 있어야 합니다.
현재 SELL 주문수량도 고정 주문금액을 현재가로 나눈 수량입니다.

다음 단계에서 아래 안전장치를 추가합니다.

- 중복 주문 차단
- 종목별 쿨다운
- 최대 주문금액
- 최대 보유 종목 수
- 일일 최대 손실
- 거래시간 제한
- PAPER/LIVE 전환 잠금

## 테스트

```powershell
cd D:\Projects\stock-platform
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_realtime_paper_order_executor.py `
    -q
```

## Git 커밋

```powershell
git add `
    README_STEP27_3.md `
    src\stock_platform\realtime\execution_models.py `
    src\stock_platform\realtime\order_executor.py `
    src\stock_platform\realtime\execution_runner.py `
    src\stock_platform\realtime\runtime.py `
    src\stock_platform\realtime\__init__.py `
    src\stock_platform\api\v1\realtime_execution.py `
    src\stock_platform\api\router.py `
    src\stock_platform\api\main.py `
    tests\test_realtime_paper_order_executor.py

git commit -m "feat(realtime): connect signals to paper orders"
```

다음 단계는 STEP27-4 주문 안전장치와 실거래 전환 잠금입니다.
