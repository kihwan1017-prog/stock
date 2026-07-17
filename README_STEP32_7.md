# STEP32-7 PostgreSQL 멱등성 저장소와 주문 Outbox

이번 단계에서는 주문 명령을 PostgreSQL에 먼저 저장한 뒤
백그라운드 Worker가 Broker로 전송하도록 변경합니다.

## 구조

```text
API / Strategy
    ↓
주문 DB 저장
    +
Outbox 저장
    ↓
같은 Transaction Commit
    ↓
OrderOutboxWorker
    ↓
Kiwoom REST
```

## 추가 테이블

```text
operation.idempotency_key
trading.order_outbox
```

## Outbox 상태

```text
PENDING
PROCESSING
RETRY
DONE
FAILED
```

## 재시도 간격

```text
1차 실패: 5초
2차 실패: 15초
3차 실패: 30초
4차 실패: 60초
5차 실패: 300초
```

최대 재시도 횟수를 넘으면 `FAILED`가 됩니다.

## 동시 Worker 잠금

PostgreSQL의 다음 잠금 방식을 사용합니다.

```sql
SELECT ...
  FROM trading.order_outbox
 WHERE status_code IN ('PENDING', 'RETRY')
 FOR UPDATE SKIP LOCKED;
```

여러 Worker가 실행되어도 같은 Outbox 행을 동시에 가져가지 않습니다.

## Alembic 적용

먼저 다음 파일의 이전 Revision을 실제 값으로 바꾸세요.

```text
alembic/versions/step32_7_order_outbox_idempotency.py
```

수정 부분:

```python
down_revision = "REPLACE_WITH_PREVIOUS_REVISION"
```

적용:

```powershell
alembic upgrade head
```

## Alembic env.py Entity import

```python
from stock_platform.operation import idempotency_entities
from stock_platform.order import outbox_entities
```

## API Router 등록

```python
from stock_platform.api.v1.order_outbox import (
    router as order_outbox_router,
)

api_router.include_router(order_outbox_router)
```

관리 API:

```text
GET  /api/v1/order-outbox
POST /api/v1/order-outbox/retry
```

## 주문 생성과 Outbox를 같은 Transaction에 저장

```python
order = order_repository.create(...)

outbox_repository.enqueue(
    order_id=order.order_id,
    event_type=OutboxEventType.SUBMIT_ORDER,
    idempotency_key=(
        f"SUBMIT:{order.client_order_id}"
    ),
    payload_json={
        "client_order_id": order.client_order_id,
        "account_id": order.account_id,
        "exchange_code": order.exchange_code,
        "symbol": order.symbol,
        "side": order.side_code,
        "order_type": order.order_type_code,
        "quantity": str(order.order_quantity),
        "price": (
            None
            if order.order_price is None
            else str(order.order_price)
        ),
        "time_in_force": order.time_in_force_code,
    },
)

session.commit()
```

중요한 점은 주문 저장과 Outbox 저장 사이에서 Commit하지 않는 것입니다.

## Worker 생성 예

프로젝트의 실제 `SessionLocal` 이름에 맞게 import를 조정하세요.

```python
from stock_platform.database.session import SessionLocal
from stock_platform.broker.factory import BrokerAdapterFactory
from stock_platform.broker.models import BrokerEnvironment
from stock_platform.order.outbox_dispatcher import (
    OrderOutboxDispatcher,
)
from stock_platform.order.outbox_worker import (
    OrderOutboxWorker,
)
from stock_platform.order.outbox_scheduler import (
    OrderOutboxScheduler,
)

adapter = BrokerAdapterFactory.create(
    BrokerEnvironment.LIVE,
    "KIWOOM",
)

worker = OrderOutboxWorker(
    session_factory=SessionLocal,
    dispatcher=OrderOutboxDispatcher(adapter),
    worker_id="stock-platform-01",
)

order_outbox_scheduler = OrderOutboxScheduler(
    worker=worker,
    interval_seconds=1.0,
)
```

## FastAPI lifespan 연결 예

시작:

```python
order_outbox_scheduler.start()
```

종료:

```python
await order_outbox_scheduler.shutdown()
```

## 테스트

```powershell
$env:PYTHONPATH = "D:\\Projects\\stock-platform\\src"

python -m pytest `
  tests\\test_outbox_retry_policy.py `
  tests\\test_postgresql_idempotency_hash.py `
  tests\\test_outbox_dispatcher.py `
  -q
```

PostgreSQL 통합 테스트는 테스트 DB를 별도로 지정해서 실행하세요.

## 주의할 점

현재 프로젝트의 DB 모듈 이름이 다음과 다를 수 있습니다.

```text
stock_platform.database.base.Base
stock_platform.database.session.get_db_session
stock_platform.database.session.SessionLocal
```

실제 프로젝트 이름이 다르면 import 경로만 맞춰야 합니다.

또한 STEP32-6의 메모리 `InMemoryIdempotencyStore`는 단위 테스트나
Paper Adapter용으로 남겨두고, 실제 Worker에서는
`PostgreSqlIdempotencyRepository`를 사용합니다.

## Git

```powershell
git add README_STEP32_7.md `
  alembic\\versions\\step32_7_order_outbox_idempotency.py `
  src\\stock_platform\\operation `
  src\\stock_platform\\order `
  src\\stock_platform\\api\\v1\\order_outbox.py `
  src\\stock_platform\\api\\router.py `
  tests\\test_outbox_retry_policy.py `
  tests\\test_postgresql_idempotency_hash.py `
  tests\\test_outbox_dispatcher.py

git commit -m "feat(order): add PostgreSQL idempotency and outbox"
```

다음 단계는 STEP32-8 키움 WebSocket 체결 이벤트 수신과 주문 상태 자동 동기화입니다.
