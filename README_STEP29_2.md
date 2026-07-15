# STEP29-2 DB 계좌 상태와 주문 실행기 Risk Engine 통합

STEP29-1의 Risk Engine을 실제 실시간 주문 실행 흐름에 연결합니다.

## 처리 흐름

```text
실시간 전략 신호
  ↓
키움 계좌 스냅샷 조회
  ↓
보유종목·현금·손익 계산
  ↓
Risk Engine
  ↓
기존 Safety Guard
  ↓
Paper 주문 실행
```

## 계좌 상태 출처

```text
trading.broker_account_snapshot
trading.broker_position_snapshot
```

STEP28-3 계좌 동기화가 먼저 정상 동작해야 합니다.

## 추가 파일

```text
src/stock_platform/risk_engine/account_state_service.py
src/stock_platform/risk_engine/integration_models.py
src/stock_platform/risk_engine/order_guard.py
src/stock_platform/realtime/risk_integrated_order_executor.py
src/stock_platform/realtime/execution_runner.py
src/stock_platform/api/v1/realtime_risk_account.py
tests/test_risk_account_state_service.py
tests/test_risk_integrated_order_executor.py
```

신규 테이블은 없어 Alembic 작업은 필요 없습니다.

## 필수 환경변수

```dotenv
KIWOOM_ACCOUNT_NUMBER=모의계좌번호
```

계좌번호가 없으면 실시간 주문은 다음 사유로 차단됩니다.

```text
RISK_ACCOUNT_NUMBER_MISSING
```

## Risk Engine 차단 사유

Risk Engine에서 하나라도 `BLOCK`이 나오면 주문은 실행되지 않고
다음 사유가 기록됩니다.

```text
RISK_ENGINE_BLOCKED
```

## API

계좌 상태 확인:

```text
GET /api/v1/realtime-risk/account-state/{account_number}/{exchange_code}/{symbol}
```

예:

```text
GET /api/v1/realtime-risk/account-state/1234567890/KRX/005930
```

## router.py 추가

```python
from stock_platform.api.v1.realtime_risk_account import (
    router as realtime_risk_account_router,
)

api_router.include_router(
    realtime_risk_account_router
)
```

## 적용 주의

이번 ZIP의 `execution_runner.py`는 STEP27-4 이후 파일을 교체합니다.

기존 호출:

```text
SafeRealtimeOrderExecutor
```

변경 호출:

```text
RiskIntegratedRealtimeOrderExecutor
```

Risk Engine 통과 후 기존 Safety Guard가 한 번 더 검사하므로
안전장치가 이중 적용됩니다.

## 테스트

```powershell
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_risk_account_state_service.py `
    tests\test_risk_integrated_order_executor.py `
    tests\test_realtime_risk_engine.py `
    -q
```

## 검증 순서

```text
1. 키움 모의계좌 동기화
2. broker_account_snapshot 확인
3. broker_position_snapshot 확인
4. Risk Account API 조회
5. 실시간 주문 실행기 시작
6. BUY 신호 테스트
7. 차단 또는 실행 이력 확인
```

모의계좌 동기화:

```text
POST /api/v1/broker/kiwoom/account/sync
```

주문 실행 이력:

```text
GET /api/v1/realtime-execution/history
```

## Git 커밋

```powershell
git add `
    README_STEP29_2.md `
    src\stock_platform\risk_engine\account_state_service.py `
    src\stock_platform\risk_engine\integration_models.py `
    src\stock_platform\risk_engine\order_guard.py `
    src\stock_platform\realtime\risk_integrated_order_executor.py `
    src\stock_platform\realtime\execution_runner.py `
    src\stock_platform\api\v1\realtime_risk_account.py `
    src\stock_platform\api\router.py `
    tests\test_risk_account_state_service.py `
    tests\test_risk_integrated_order_executor.py

git commit -m "feat(risk): integrate account state with order execution"
```

다음 단계는 STEP29-3 영구 긴급정지 Kill Switch와 모든 주문 차단입니다.
