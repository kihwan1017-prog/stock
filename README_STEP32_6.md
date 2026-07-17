# STEP32-6 키움 취소·정정 주문과 중복 방지

공식 키움 REST API의 국내주식 주문 TR 중 다음 항목을 연결합니다.

```text
주식 정정주문: kt10002
주식 취소주문: kt10003
```

두 요청 모두 기존 주문번호를 기준으로 처리합니다.

## 추가 파일

```text
src/stock_platform/broker/idempotency.py
src/stock_platform/broker/kiwoom/cancel_replace_models.py
src/stock_platform/broker/kiwoom/cancel_replace_mapper.py
src/stock_platform/order/cancel_replace_service.py
src/stock_platform/api/v1/order_cancel_replace.py

tests/test_broker_idempotency.py
tests/test_kiwoom_cancel_replace_mapper.py
tests/test_kiwoom_cancel_replace_adapter.py
```

교체 파일:

```text
src/stock_platform/broker/kiwoom/adapter.py
```

## API

```text
POST /api/v1/orders/{order_id}/cancel
POST /api/v1/orders/{order_id}/replace
```

취소 요청:

```json
{
  "quantity": 1,
  "actor": "API"
}
```

수량을 생략하면 로컬 주문의 `remaining_quantity` 전량을 취소합니다.

정정 요청:

```json
{
  "quantity": 2,
  "price": 71000,
  "actor": "API"
}
```

## Router 등록

```python
from stock_platform.api.v1.order_cancel_replace import (
    router as order_cancel_replace_router,
)

api_router.include_router(
    order_cancel_replace_router
)
```

## 상태 흐름

취소:

```text
ACCEPTED/PARTIALLY_FILLED
→ CANCEL_REQUESTED
→ CANCELLED
```

정정:

```text
ACCEPTED/PARTIALLY_FILLED
→ REPLACE_REQUESTED
→ REPLACED
```

Broker 거부 또는 통신 오류는 `FAILED`로 기록됩니다.

## 멱등성

같은 `idempotency_key`의 요청은 Broker에 한 번만 전송됩니다.

현재 구현은 프로세스 메모리 방식입니다. 서버 재시작 후에도 중복을
방지하려면 다음 단계에서 PostgreSQL 기반 저장소로 교체합니다.

## 요청 Body 확인

이번 Mapper는 다음 필드명을 사용합니다.

```text
dmst_stex_tp
orig_ord_no
stk_cd
mdfy_qty
mdfy_uv
cncl_qty
```

키움 사이트의 `kt10002`, `kt10003` 상세 화면에서 계정에 표시되는
최신 요청 필드와 반드시 대조한 뒤 모의투자로 검증하세요.

## 테스트

```powershell
$env:PYTHONPATH = "D:\\Projects\\stock-platform\\src"

python -m pytest `
  tests\\test_broker_idempotency.py `
  tests\\test_kiwoom_cancel_replace_mapper.py `
  tests\\test_kiwoom_cancel_replace_adapter.py `
  tests\\test_order_state_machine.py `
  -q
```

테스트는 실제 주문을 전송하지 않습니다.

## Git

```powershell
git add README_STEP32_6.md `
  src\\stock_platform\\broker `
  src\\stock_platform\\order\\cancel_replace_service.py `
  src\\stock_platform\\api\\v1\\order_cancel_replace.py `
  src\\stock_platform\\api\\router.py `
  tests\\test_broker_idempotency.py `
  tests\\test_kiwoom_cancel_replace_mapper.py `
  tests\\test_kiwoom_cancel_replace_adapter.py

git commit -m "feat(order): add Kiwoom cancel and replace orders"
```

다음 단계는 STEP32-7 PostgreSQL 멱등성 저장소와 주문 명령 Outbox입니다.
