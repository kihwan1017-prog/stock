# STEP28-1 Broker 주문 어댑터와 실거래 승인 절차

실거래 API를 바로 연결하지 않고 공통 Broker Adapter와
1회용 승인 토큰 구조를 먼저 구성합니다.

## 주요 구성

```text
BrokerOrderAdapter
PaperBrokerOrderAdapter
BrokerOrderService
LiveTradingApprovalService
```

## 안전 원칙

현재 기본값은 Paper Adapter입니다.

```python
live_mode=False
```

실제 키움·업비트 주문 어댑터가 구현되기 전까지
이 값을 변경하지 마세요.

## 1회용 승인 토큰

실거래 모드에서는 주문마다 다음 절차가 필요합니다.

```text
승인 토큰 발급
→ 5분 이내 주문 요청
→ 1회 사용 후 자동 폐기
```

원문 토큰은 저장하지 않고 SHA-256 해시만 보관합니다.

## API

승인 발급:

```text
POST /api/v1/broker/live-approval
```

주문 요청:

```text
POST /api/v1/broker/orders
```

주문 조회:

```text
GET /api/v1/broker/orders/{broker_order_id}
```

주문 취소:

```text
POST /api/v1/broker/orders/{broker_order_id}/cancel
```

계좌 조회:

```text
GET /api/v1/broker/account
```

## 주문 예

```json
{
  "exchange_code": "KRX",
  "symbol": "005930",
  "side": "BUY",
  "order_type": "MARKET",
  "quantity": 1,
  "price": null,
  "approval_id": null,
  "approval_token": null
}
```

Paper 모드에서는 승인값이 없어도 됩니다.

## 적용 파일

```text
src/stock_platform/broker/__init__.py
src/stock_platform/broker/base.py
src/stock_platform/broker/models.py
src/stock_platform/broker/paper_adapter.py
src/stock_platform/broker/live_approval.py
src/stock_platform/broker/service.py
src/stock_platform/broker/runtime.py
src/stock_platform/api/v1/broker_orders.py
tests/test_live_trading_approval.py
tests/test_broker_order_service.py
```

신규 테이블은 없어 Alembic 작업은 필요 없습니다.

## router.py 추가

```python
from stock_platform.api.v1.broker_orders import (
    router as broker_orders_router,
)
```

```python
api_router.include_router(broker_orders_router)
```

## 테스트

```powershell
cd D:\Projects\stock-platform
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_live_trading_approval.py `
    tests\test_broker_order_service.py `
    -q
```

## Git 커밋

```powershell
git add `
    README_STEP28_1.md `
    src\stock_platform\broker `
    src\stock_platform\api\v1\broker_orders.py `
    src\stock_platform\api\router.py `
    tests\test_live_trading_approval.py `
    tests\test_broker_order_service.py

git commit -m "feat(broker): add adapter and live approval flow"
```

다음 단계는 STEP28-2 키움 REST 주문 어댑터입니다.
