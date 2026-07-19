# STEP29-4 일일 손실 자동 감지와 Kill Switch 자동 활성화

키움 계좌·보유종목 스냅샷의 손익을 1분마다 확인하고 일일 손실
한도를 넘으면 GLOBAL Kill Switch를 자동 활성화합니다.

## 동작

```text
계좌 스냅샷
  ↓
실현손익 + 미실현손익
  ↓
현재 손실 계산
  ↓
max_daily_loss 이상
  ↓
Kill Switch 자동 활성화
  ↓
Risk Event 저장
  ↓
로그 알림
```

STEP29-6에서 로그 알림을 Telegram·Slack으로 확장합니다.

## 신규 테이블

```text
operation.risk_event
```

## Alembic 등록

`database/alembic/env.py`:

```python
from stock_platform.risk_engine import risk_event_entities as risk_event_entities  # noqa: F401
```

## 마이그레이션

```powershell
alembic revision --autogenerate `
    -m "create risk event table"

alembic upgrade head --sql
alembic upgrade head
```

예상하지 않은 삭제 작업이 있으면 적용하지 마세요.

## 손실 계산

```text
combined_profit_loss
= account.total_profit_loss
+ 보유종목 profit_loss 합계

current_loss
= max(-combined_profit_loss, 0)
```

현재 계좌 모델에서 `total_profit_loss`의 정의가 이미 평가손익을
포함한다면 미실현손익이 중복 계산될 수 있습니다.

실제 키움 응답 검증 후 다음 중 하나로 조정하세요.

```text
A. total_profit_loss가 실현손익만 포함
   → 현재 코드 유지

B. total_profit_loss가 전체 평가손익 포함
   → positions profit_loss 합계를 더하지 않음
```

이 부분은 모의계좌 응답 확인이 반드시 필요합니다.

## Scheduler

1분마다 실행:

```text
daily_loss_monitor
```

`main.py`에서 시작·종료:

```python
from stock_platform.risk_engine.daily_loss_scheduler import (
    daily_loss_monitor_scheduler,
)
```

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()

    daily_loss_monitor_scheduler.start()

    yield

    await daily_loss_monitor_scheduler.shutdown()
    await kiwoom_order_websocket_manager.stop()
    await realtime_trading_scheduler.shutdown()
    await realtime_execution_runner.stop()
    await realtime_strategy_runner.stop()
    await realtime_manager.stop_all()
```

## API

```text
GET  /api/v1/risk/daily-loss/status
POST /api/v1/risk/daily-loss/check
POST /api/v1/risk/daily-loss/reset
GET  /api/v1/risk/daily-loss/events
```

`reset`은 손익 값을 초기화하지 않습니다. 계좌 스냅샷이 원본이므로
상태 설명만 반환합니다. Kill Switch 해제는 별도 API를 사용합니다.

```text
POST /api/v1/risk/kill-switch/deactivate
```

## router.py

```python
from stock_platform.api.v1.daily_loss_monitor import (
    router as daily_loss_monitor_router,
)

api_router.include_router(
    daily_loss_monitor_router
)
```

## 필수 환경변수

```dotenv
KIWOOM_ACCOUNT_NUMBER=모의계좌번호
KIWOOM_USE_MOCK=true
KIWOOM_LIVE_ORDER_ENABLED=false
```

## 테스트

```powershell
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_daily_loss_monitor.py `
    tests\test_kill_switch_service.py `
    -q
```

## Git 커밋

```powershell
git add `
    README_STEP29_4.md `
    database\alembic\env.py `
    database\alembic\versions `
    src\stock_platform\risk_engine\risk_event_entities.py `
    src\stock_platform\risk_engine\daily_loss_models.py `
    src\stock_platform\risk_engine\risk_event_repository.py `
    src\stock_platform\risk_engine\alert.py `
    src\stock_platform\risk_engine\daily_loss_monitor.py `
    src\stock_platform\risk_engine\daily_loss_runtime.py `
    src\stock_platform\risk_engine\daily_loss_scheduler.py `
    src\stock_platform\api\v1\daily_loss_monitor.py `
    src\stock_platform\api\router.py `
    src\stock_platform\api\main.py `
    tests\test_daily_loss_monitor.py

git commit -m "feat(risk): add automatic daily loss monitor"
```

다음 단계는 STEP29-5 종목별 최대 보유금액·비중·수량 제한입니다.
