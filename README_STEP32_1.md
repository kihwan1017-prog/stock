# STEP32-1 주문 Entity·Repository

SQL 예약어 `ORDER`와 충돌하지 않도록 테이블명은 다음을 사용합니다.

```text
trading.trading_order
trading.trading_order_status_history
```

## 상태

```text
CREATED
PENDING
SENT
ACCEPTED
PARTIALLY_FILLED
FILLED
CANCEL_REQUESTED
CANCELLED
REPLACE_REQUESTED
REPLACED
REJECTED
FAILED
```

## Alembic 등록

```python
from stock_platform.order import entities as order_entities  # noqa: F401
```

## 마이그레이션

```powershell
alembic revision --autogenerate -m "create trading order tables"
alembic upgrade head --sql
alembic upgrade head
```

예상하지 않은 DROP이 있으면 적용하지 마세요.

## router.py

```python
from stock_platform.api.v1.orders import router as orders_router
api_router.include_router(orders_router)
```

## API

```text
POST /api/v1/orders
GET  /api/v1/orders
GET  /api/v1/orders/{order_id}
GET  /api/v1/orders/{order_id}/history
```

주문 원장은 삭제하지 않습니다. 취소는 다음 단계의 상태 전이로 처리합니다.

## 테스트

```powershell
$env:PYTHONPATH = "D:\Projects\stock-platform\src"
python -m pytest `
    tests\test_order_service.py `
    tests\test_client_order_id_generator.py `
    -q
```

## Git 커밋

```powershell
git add README_STEP32_1.md database\alembic src\stock_platform\order `
    src\stock_platform\api\v1\orders.py src\stock_platform\api\router.py `
    tests\test_order_service.py tests\test_client_order_id_generator.py

git commit -m "feat(order): add order entity and repository"
```

다음 단계는 STEP32-2 주문 상태 머신과 상태 전이 검증입니다.
