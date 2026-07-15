# STEP29-5 종목별 최대 보유수량·금액·비중 제한

BUY 주문 실행 전에 해당 종목의 예상 보유수량, 예상 평가금액,
총자산 대비 예상 비중을 검사합니다.

## 검사 항목

```text
종목별 최대 보유수량
종목별 최대 보유금액
종목별 최대 보유비중
```

SELL 주문은 보유위험을 줄이므로 통과합니다.

## 기본값

종목별 별도 설정이 없으면 다음 기본 정책을 사용합니다.

```text
최대 수량: 1,000,000
최대 금액: 500,000원
최대 비중: 총자산의 25%
```

기본값 파일:

```text
src/stock_platform/risk_engine/position_limit_models.py
```

## 신규 테이블

```text
operation.position_limit
```

계좌·거래소·종목별로 한도를 별도 설정할 수 있습니다.

## Alembic 등록

`database/alembic/env.py`:

```python
from stock_platform.risk_engine import position_limit_entities as position_limit_entities  # noqa: F401
```

## 마이그레이션

```powershell
alembic revision --autogenerate `
    -m "create position limit table"

alembic upgrade head --sql
alembic upgrade head
```

예상하지 않은 삭제 작업이 있으면 적용하지 마세요.

## 주문 검사 흐름

```text
Persistent Kill Switch
  ↓
Risk Engine
  ↓
Position Limit Rule
  ↓
Safety Guard
  ↓
Execution
```

한도 초과 시:

```text
RISK_ENGINE_BLOCKED
```

세부 결과에는 다음 규칙 코드가 포함됩니다.

```text
POSITION_LIMIT
```

## API

한도 저장:

```text
PUT /api/v1/risk/position-limits
```

```json
{
  "broker_code": "KIWOOM",
  "account_number": "1234567890",
  "exchange_code": "KRX",
  "symbol": "005930",
  "max_quantity": 10,
  "max_position_amount": 800000,
  "max_position_weight": 0.20,
  "enabled": true
}
```

한도 조회:

```text
GET /api/v1/risk/position-limits/{account_number}/{exchange_code}/{symbol}
```

## router.py

```python
from stock_platform.api.v1.position_limits import (
    router as position_limits_router,
)

api_router.include_router(
    position_limits_router
)
```

## 적용 파일

```text
src/stock_platform/risk_engine/position_limit_models.py
src/stock_platform/risk_engine/position_limit_entities.py
src/stock_platform/risk_engine/position_limit_repository.py
src/stock_platform/risk_engine/position_limit_rule.py
src/stock_platform/risk_engine/order_guard.py
src/stock_platform/api/v1/position_limits.py
tests/test_position_limit_rule.py
```

`order_guard.py`는 STEP29-2 파일을 교체합니다.

## 테스트

```powershell
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_position_limit_rule.py `
    tests\test_realtime_risk_engine.py `
    tests\test_risk_account_state_service.py `
    -q
```

## Git 커밋

```powershell
git add `
    README_STEP29_5.md `
    database\alembic\env.py `
    database\alembic\versions `
    src\stock_platform\risk_engine\position_limit_models.py `
    src\stock_platform\risk_engine\position_limit_entities.py `
    src\stock_platform\risk_engine\position_limit_repository.py `
    src\stock_platform\risk_engine\position_limit_rule.py `
    src\stock_platform\risk_engine\order_guard.py `
    src\stock_platform\api\v1\position_limits.py `
    src\stock_platform\api\router.py `
    tests\test_position_limit_rule.py

git commit -m "feat(risk): add per-symbol position limits"
```

다음 단계는 STEP29-6 Telegram·Slack 위험 알림 연결입니다.
