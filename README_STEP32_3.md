# STEP32-3 주문 Dispatcher와 Broker Adapter

전략 주문을 특정 증권사 구현과 분리하는 브로커 추상화 계층입니다.

## 흐름

```text
CREATED → PENDING → SENT → Broker.submit_order()
                          ├─ ACCEPTED
                          ├─ REJECTED
                          └─ FAILED
```

## 포함 파일

```text
src/stock_platform/broker/models.py
src/stock_platform/broker/adapter.py
src/stock_platform/broker/exceptions.py
src/stock_platform/broker/factory.py
src/stock_platform/broker/dispatcher.py
src/stock_platform/broker/paper/adapter.py
src/stock_platform/broker/kiwoom/adapter.py
src/stock_platform/api/v1/order_dispatch.py
tests/test_broker_factory.py
tests/test_order_dispatcher.py
```

## Router 등록

```python
from stock_platform.api.v1.order_dispatch import router as order_dispatch_router
api_router.include_router(order_dispatch_router)
```

## API

```text
POST /api/v1/orders/{order_id}/dispatch
```

요청:

```json
{
  "environment": "PAPER",
  "broker_code": "KIWOOM",
  "actor": "API"
}
```

## 테스트

```powershell
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
  tests\test_broker_factory.py `
  tests\test_order_dispatcher.py `
  -q
```

## 주의

`KiwoomBrokerAdapter`는 이번 단계에서 Mock입니다.
실제 키움 REST 인증과 주문 API 호출은 다음 단계에서 연결합니다.

## Git

```powershell
git add README_STEP32_3.md src\stock_platform\broker `
  src\stock_platform\api\v1\order_dispatch.py `
  src\stock_platform\api\router.py `
  tests\test_broker_factory.py tests\test_order_dispatcher.py

git commit -m "feat(order): add broker adapter and dispatcher"
```

다음 단계는 STEP32-4 실제 키움 REST 주문 Adapter입니다.
