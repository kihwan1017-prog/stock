# STEP28-4 키움 미체결 조회·정정·취소

공식 TR:

```text
미체결요청     ka10075
주식 정정주문  kt10002
주식 취소주문  kt10003
```

## 신규 테이블

```text
trading.broker_pending_order
```

## Alembic 등록

```python
from stock_platform.broker import pending_entities as broker_pending_entities  # noqa: F401
```

```powershell
alembic revision --autogenerate `
    -m "create broker pending order table"

alembic upgrade head --sql
alembic upgrade head
```

예상하지 않은 `drop_table`이 있으면 적용하지 마세요.

## API

```text
POST /api/v1/broker/kiwoom/pending-orders/{account_number}/sync
GET  /api/v1/broker/kiwoom/pending-orders/{account_number}
POST /api/v1/broker/kiwoom/pending-orders/{order_id}/modify
POST /api/v1/broker/kiwoom/pending-orders/{order_id}/cancel
```

## router.py

```python
from stock_platform.api.v1.kiwoom_pending_orders import (
    router as kiwoom_pending_orders_router,
)
api_router.include_router(kiwoom_pending_orders_router)
```

정정 요청의 `trade_type`은 공식 문서에서 확인한 값을 사용하세요.
안전 설정은 유지합니다.

```dotenv
KIWOOM_USE_MOCK=true
KIWOOM_LIVE_ORDER_ENABLED=false
```

## 테스트

```powershell
$env:PYTHONPATH = "D:\Projects\stock-platform\src"
python -m pytest tests\test_kiwoom_pending_order_mapper.py -q
```

## 커밋

```powershell
git add `
    README_STEP28_4.md `
    database\alembic\env.py `
    database\alembic\versions `
    src\stock_platform\broker\pending_models.py `
    src\stock_platform\broker\pending_entities.py `
    src\stock_platform\broker\pending_repository.py `
    src\stock_platform\broker\kiwoom\pending_client.py `
    src\stock_platform\broker\kiwoom\pending_mapper.py `
    src\stock_platform\broker\kiwoom\pending_service.py `
    src\stock_platform\broker\kiwoom\pending_factory.py `
    src\stock_platform\api\v1\kiwoom_pending_orders.py `
    src\stock_platform\api\router.py `
    tests\test_kiwoom_pending_order_mapper.py

git commit -m "feat(broker): manage Kiwoom pending orders"
```

다음 단계는 STEP28-5 키움 실시간 주문체결 WebSocket입니다.
