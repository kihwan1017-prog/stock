# STEP32-2 주문 상태 머신

주문 상태가 허용된 순서로만 변경되도록 강제합니다.

## 추가 파일

```text
src/stock_platform/order/state_models.py
src/stock_platform/order/state_machine.py
src/stock_platform/order/state_service.py
src/stock_platform/api/v1/order_states.py
tests/test_order_state_machine.py
```

## 기존 파일 수정

`TradingOrderRepository.change_status()`에 아래 검증을 추가해야 합니다.

```python
from stock_platform.order.state_machine import OrderStateMachine

current_status = OrderStatus(entity.status_code)
if validate_transition:
    OrderStateMachine.validate_transition(
        current=current_status,
        target=new_status,
    )
```

메서드 인자에도 추가합니다.

```python
validate_transition: bool = True
```

## Router 추가

```python
from stock_platform.api.v1.order_states import (
    router as order_states_router,
)

api_router.include_router(order_states_router)
```

## API

```text
POST /api/v1/orders/{order_id}/transition
GET  /api/v1/orders/{order_id}/allowed-transitions
```

잘못된 전이는 HTTP 409를 반환합니다.

## 테스트

```powershell
$env:PYTHONPATH = "D:\Projects\stock-platform\src"
python -m pytest tests\test_order_state_machine.py -q
```

## Git 커밋

```powershell
git add README_STEP32_2.md src\stock_platform\order\state_models.py `
    src\stock_platform\order\state_machine.py `
    src\stock_platform\order\state_service.py `
    src\stock_platform\api\v1\order_states.py `
    src\stock_platform\api\router.py `
    src\stock_platform\order\repository.py `
    tests\test_order_state_machine.py

git commit -m "feat(order): add order state machine"
```

다음 단계는 STEP32-3 주문 송신 Dispatcher와 Broker Adapter 인터페이스입니다.
