# STEP29-1 실시간 위험관리 엔진

모든 주문을 실행하기 전에 공통 Risk Engine으로 검사합니다.

## 주문 흐름

```text
Strategy
  ↓
Risk Engine
  ↓
PASS / WARNING / BLOCK
  ↓
Execution
  ↓
Broker
```

## 검사 규칙

```text
긴급정지
KRX 거래시간
최대 주문금액
최대 주문수량
사용 가능 현금
최대 보유종목 수
최대 투자비율
일일 손실한도
매도 가능수량
```

## 결과

```text
PASS
WARNING
BLOCK
```

`BLOCK`이면 주문을 실행하면 안 됩니다.

`WARNING`은 위험 축소 목적의 SELL처럼 제한적으로 허용되는
상태입니다.

## 기본 정책

```text
최대 주문금액:       100,000원
최대 주문수량:       1,000,000
최대 보유종목:       5개
최대 투자비율:       총자산의 70%
일일 최대손실:       300,000원
KRX 거래시간:        09:00~15:20
긴급정지:            비활성화
긴급정지 중 SELL:    허용
```

설정 파일:

```text
src/stock_platform/risk_engine/runtime.py
```

## 포함 파일

```text
src/stock_platform/risk_engine/models.py
src/stock_platform/risk_engine/rules.py
src/stock_platform/risk_engine/engine.py
src/stock_platform/risk_engine/runtime.py
src/stock_platform/api/v1/realtime_risk_engine.py
tests/test_realtime_risk_engine.py
```

신규 테이블은 없어 Alembic 작업은 필요 없습니다.

## router.py 추가

```python
from stock_platform.api.v1.realtime_risk_engine import (
    router as realtime_risk_engine_router,
)

api_router.include_router(
    realtime_risk_engine_router
)
```

## API

상태:

```text
GET /api/v1/realtime-risk/status
```

주문 위험검사:

```text
POST /api/v1/realtime-risk/check
```

요청 예:

```json
{
  "exchange_code": "KRX",
  "symbol": "005930",
  "side": "BUY",
  "quantity": 1,
  "price": 72000,
  "account_id": 1,
  "requested_at": "2026-07-15T10:00:00+09:00",
  "cash_balance": 1000000,
  "total_asset_value": 2000000,
  "invested_amount": 500000,
  "daily_realized_profit_loss": -10000,
  "daily_unrealized_profit_loss": -20000,
  "open_position_count": 2,
  "symbol_position_quantity": 0
}
```

## 주문 실행기 연결

STEP27-4의 `SafeRealtimeOrderExecutor.execute()`에서 기존
Safety Guard 전에 Risk Engine을 호출하도록 연결합니다.

핵심 조건:

```python
risk_result = realtime_risk_engine.evaluate(
    order=risk_order,
    account=risk_account,
    policy=realtime_risk_policy,
)

if not risk_result.allowed:
    return skipped_result
```

계좌 상태를 DB에서 조회하는 연결 코드는 STEP29-2에서
추가합니다.

## 테스트

```powershell
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_realtime_risk_engine.py `
    -q
```

## Git 커밋

```powershell
git add `
    README_STEP29_1.md `
    src\stock_platform\risk_engine `
    src\stock_platform\api\v1\realtime_risk_engine.py `
    src\stock_platform\api\router.py `
    tests\test_realtime_risk_engine.py

git commit -m "feat(risk): add realtime risk engine"
```

다음 단계는 STEP29-2 DB 계좌 상태를 Risk Engine에 자동 연결하는
주문 전 위험검사 통합입니다.
