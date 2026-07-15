# STEP28-6 서버 재시작·연결장애 자동 복구

서버 재시작 후 키움 계좌, 미체결 주문, 주문체결 WebSocket,
실시간 스케줄러 상태를 순서대로 복구합니다.

## 복구 순서

```text
1. 키움 계좌 스냅샷 동기화
2. 키움 미체결 주문 동기화
3. 주문체결 WebSocket 재연결
4. 실시간 주문 실행기 시작(선택)
5. 실시간 전략 실행기 시작(선택)
6. 장중 스케줄러 시작
```

계좌 동기화와 미체결 동기화가 실패하면 전체 복구 결과는
`FAILED`입니다.

WebSocket이나 스케줄러 실패는 단계별 결과에 기록됩니다.

## 신규 테이블

```text
operation.broker_recovery_run
operation.broker_recovery_step
```

## Alembic 등록

`database/alembic/env.py`:

```python
from stock_platform.broker import recovery_entities as broker_recovery_entities  # noqa: F401
```

## 마이그레이션

```powershell
alembic revision --autogenerate `
    -m "create broker recovery tables"

alembic upgrade head --sql
alembic upgrade head
```

예상하지 않은 `drop_table`이나 `drop_column`이 있으면 적용하지
마세요.

## 환경변수

```dotenv
KIWOOM_ACCOUNT_NUMBER=모의계좌번호

KIWOOM_RECOVERY_START_WS=true
KIWOOM_RECOVERY_START_TRADING=false
KIWOOM_RECOVERY_START_SCHEDULER=true
```

`KIWOOM_RECOVERY_START_TRADING=false`를 유지하면 서버 재시작 후
전략과 주문 실행기는 자동 시작되지 않습니다.

모의투자 검증이 끝나기 전까지 `true`로 변경하지 마세요.

기존 WebSocket 설정도 필요합니다.

```dotenv
KIWOOM_USE_MOCK=true
KIWOOM_LIVE_ORDER_ENABLED=false

KIWOOM_ORDER_WS_URL=wss://mockapi.kiwoom.com:10000
KIWOOM_ORDER_WS_PATH=공식문서에서_확인한_경로
KIWOOM_ORDER_WS_SUBSCRIBE_JSON={"공식문서에서":"복사한 구독 JSON"}
```

## API

복구 실행:

```text
POST /api/v1/broker/recovery/run
```

상태 조회:

```text
GET /api/v1/broker/recovery/status
```

## router.py

```python
from stock_platform.api.v1.broker_recovery import (
    router as broker_recovery_router,
)

api_router.include_router(
    broker_recovery_router
)
```

## FastAPI 시작 시 자동 복구

자동 복구를 사용하려면 `main.py`의 `lifespan` 시작 부분에서
호출할 수 있습니다.

```python
from stock_platform.broker.recovery_runtime import (
    broker_recovery_manager,
)
```

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    logger.info("Stock Platform starting...")

    # 서버 시작 시 복구
    try:
        await broker_recovery_manager.recover()
    except Exception:
        logger.exception(
            "Broker recovery failed during startup"
        )

    yield

    await kiwoom_order_websocket_manager.stop()
    await realtime_trading_scheduler.shutdown()
    await realtime_execution_runner.stop()
    await realtime_strategy_runner.stop()
    await realtime_manager.stop_all()
```

초기 적용 시에는 API로 수동 복구를 먼저 검증한 뒤 자동 복구를
추가하는 것을 권장합니다.

## 테스트

```powershell
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_broker_recovery_service.py `
    -q
```

## Git 커밋

```powershell
git add `
    README_STEP28_6.md `
    database\alembic\env.py `
    database\alembic\versions `
    src\stock_platform\broker\recovery_models.py `
    src\stock_platform\broker\recovery_entities.py `
    src\stock_platform\broker\recovery_repository.py `
    src\stock_platform\broker\recovery_service.py `
    src\stock_platform\broker\recovery_runtime.py `
    src\stock_platform\api\v1\broker_recovery.py `
    src\stock_platform\api\router.py `
    src\stock_platform\api\main.py `
    tests\test_broker_recovery_service.py

git commit -m "feat(broker): add restart recovery workflow"
```

다음 단계는 STEP28-7 모의투자 검증 체크리스트와 제한된 실거래
전환 절차입니다.
