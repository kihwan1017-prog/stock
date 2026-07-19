# STEP24-1 모의 주문 및 주문 상태 관리

실제 브로커로 주문을 전송하지 않고 주문 생성, 접수, 부분체결,
완전체결, 취소, 거절 상태를 시뮬레이션합니다.

## 신규 테이블

```text
trading.paper_order
```

## Alembic 모델 등록

`database/alembic/env.py`에 추가합니다.

```python
from stock_platform.trading import models as trading_models  # noqa: F401
```

## 마이그레이션

```powershell
alembic revision --autogenerate `
    -m "create paper order table"

alembic upgrade head --sql
alembic upgrade head
```

생성 파일에는 `trading.paper_order` 생성만 있어야 합니다.
`op.drop_table(...)`이 있으면 적용하지 마세요.

## 주문 상태

```text
CREATED
ACCEPTED
PARTIALLY_FILLED
FILLED
CANCELLED
REJECTED
```

## API

모의 주문 생성:

```text
POST /api/v1/paper-orders
```

부분 또는 완전 체결:

```text
POST /api/v1/paper-orders/{order_id}/fills
```

취소:

```text
POST /api/v1/paper-orders/{order_id}/cancel
```

거절:

```text
POST /api/v1/paper-orders/{order_id}/reject
```

주문 목록:

```text
GET /api/v1/paper-orders
```

## 주문 생성 예

```json
{
  "exchange_code": "KRX",
  "symbol": "005930",
  "side": "BUY",
  "order_type": "LIMIT",
  "quantity": 10,
  "price": 70000,
  "position_plan_id": 1,
  "auto_accept": true
}
```

## 테스트

```powershell
cd D:\Projects\stock-platform
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_paper_order_engine.py `
    -q
```

## Git 커밋

```powershell
git add `
    README_STEP24_1.md `
    database\alembic\env.py `
    database\alembic\versions `
    src\stock_platform\trading `
    src\stock_platform\api\v1\paper_orders.py `
    src\stock_platform\api\router.py `
    tests\test_paper_order_engine.py

git commit -m "feat(trading): add paper order management"
```

다음 단계는 STEP24-2 모의 계좌, 포지션, 실현·미실현 손익 관리입니다.
