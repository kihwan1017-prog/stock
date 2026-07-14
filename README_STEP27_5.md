# STEP27-5 장전·장중·장마감 자동매매 스케줄러

실시간 자동매매 구성요소를 KRX 장 운영 시간에 맞춰 자동으로
시작하고 종료합니다.

## 기본 일정

```text
08:50 PRE_MARKET
09:00 MARKET_OPEN
15:20 MARKET_CLOSE
15:40 AFTER_MARKET
```

시간대는 기존 `SCHEDULER_TIMEZONE`을 사용합니다.

## 단계별 동작

### PRE_MARKET

```text
일일 손실 카운터 초기화
주문 속도 카운터 초기화
```

### MARKET_OPEN

```text
실시간 주문 실행기 시작
실시간 전략 실행기 시작
```

### MARKET_CLOSE

```text
실시간 주문 실행기 종료
실시간 전략 실행기 종료
```

### AFTER_MARKET

```text
실시간 시세 클라이언트 전체 종료
```

KRX 휴장일이면 실행을 건너뜁니다.

## 적용 파일

```text
src/stock_platform/realtime/session_models.py
src/stock_platform/realtime/session_service.py
src/stock_platform/realtime/session_scheduler.py
src/stock_platform/realtime/session_runtime.py
src/stock_platform/api/v1/realtime_sessions.py
tests/test_realtime_session_scheduler.py
```

신규 테이블은 없어 Alembic 작업은 필요 없습니다.

## router.py 추가

```python
from stock_platform.api.v1.realtime_sessions import (
    router as realtime_sessions_router,
)
```

```python
api_router.include_router(
    realtime_sessions_router
)
```

## main.py 종료 처리

import:

```python
from stock_platform.realtime.session_runtime import (
    realtime_trading_scheduler,
)
```

lifespan 종료 부분:

```python
yield

await realtime_trading_scheduler.shutdown()
await realtime_execution_runner.stop()
await realtime_strategy_runner.stop()
await realtime_manager.stop_all()
```

스케줄러 → 주문 → 전략 → 시세 순서로 종료합니다.

## API

스케줄러 시작:

```text
POST /api/v1/realtime-sessions/start-scheduler
```

스케줄러 중지:

```text
POST /api/v1/realtime-sessions/stop-scheduler
```

상태:

```text
GET /api/v1/realtime-sessions/status
```

단계 즉시 실행:

```text
POST /api/v1/realtime-sessions/run-now/PRE_MARKET
POST /api/v1/realtime-sessions/run-now/MARKET_OPEN
POST /api/v1/realtime-sessions/run-now/MARKET_CLOSE
POST /api/v1/realtime-sessions/run-now/AFTER_MARKET
```

## 중요

`MARKET_OPEN`은 전략과 주문 실행기만 시작합니다.

KRX 시세 수신기는 현재 STEP27-1의 polling provider 연결이
필요합니다. 업비트 WebSocket은 기존 시작 API를 사용합니다.

```text
POST /api/v1/realtime-quotes/upbit/start
```

실거래 모드는 여전히 잠겨 있으며 PAPER 모드만 사용합니다.

## 테스트

```powershell
cd D:\Projects\stock-platform
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_realtime_session_scheduler.py `
    -q
```

## Git 커밋

```powershell
git add `
    README_STEP27_5.md `
    src\stock_platform\realtime\session_models.py `
    src\stock_platform\realtime\session_service.py `
    src\stock_platform\realtime\session_scheduler.py `
    src\stock_platform\realtime\session_runtime.py `
    src\stock_platform\api\v1\realtime_sessions.py `
    src\stock_platform\api\router.py `
    src\stock_platform\api\main.py `
    tests\test_realtime_session_scheduler.py

git commit -m "feat(realtime): add trading session scheduler"
```

다음 단계는 STEP27-6 실시간 뉴스·공시 기반 AI 재평가입니다.
