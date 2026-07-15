# STEP31-6 PAPER 전략 성과 자동 수집·성과 저하 자동 중지

현재 ACTIVE PAPER 전략의 최신 PAPER 성과를 주기적으로 검사하고,
수익률·MDD·승률·Profit Factor·연속 손실이 기준을 벗어나면
경고하거나 전략을 자동 중지합니다.

## 신규 테이블

```text
trading.strategy_deployment_performance
```

## 기본 모니터링 기준

```text
최소 거래 수            5
최소 총수익률           -3%
최대 MDD                10%
최소 승률               30%
최소 Profit Factor      0.80
최대 연속 손실          5회
자동 중지               비활성
```

## 상태

```text
HEALTHY
WARNING
STOP_REQUIRED
STOPPED
NOT_ENOUGH_DATA
```

## 성과 원본

현재 구현은 다음 조건의 최신 성과를 사용합니다.

```text
strategy_code 일치
market_code 일치
symbol 일치
run_type = PAPER
status_code = COMPLETED
```

프로젝트에서 체결·포지션으로 PAPER 성과를 직접 계산하는 서비스가
이미 있다면 다음 파일의 조회 로직을 교체하세요.

```text
src/stock_platform/strategy_deployment/performance_collector.py
```

## Alembic 등록

`database/alembic/env.py`:

```python
from stock_platform.strategy_deployment import performance_monitor_entities as deployment_performance_entities  # noqa: F401
```

## 마이그레이션

```powershell
alembic revision --autogenerate `
    -m "create strategy deployment performance table"

alembic upgrade head --sql
alembic upgrade head
```

예상하지 않은 삭제 작업이 있으면 적용하지 마세요.

## 환경변수

초기에는 반드시 자동 중지를 비활성화합니다.

```dotenv
PAPER_STRATEGY_AUTO_STOP_ENABLED=false
```

모의투자 성과 계산을 검증한 뒤에만 활성화합니다.

```dotenv
PAPER_STRATEGY_AUTO_STOP_ENABLED=true
```

## API

ACTIVE PAPER 전략 성과 검사:

```text
POST /api/v1/strategy-deployment-performance/check-active
```

예:

```text
POST /api/v1/strategy-deployment-performance/check-active?market_code=KRX&symbol=005930
```

상태:

```text
GET /api/v1/strategy-deployment-performance/status
```

이력:

```text
GET /api/v1/strategy-deployment-performance/history
```

## Scheduler

매일 16:30에 ACTIVE PAPER 전략을 검사합니다.

```text
paper_strategy_performance_monitor
```

`main.py` 연결:

```python
from stock_platform.strategy_deployment.performance_monitor_scheduler import (
    deployment_performance_monitor_scheduler,
)
```

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()

    deployment_performance_monitor_scheduler.start()

    yield

    await deployment_performance_monitor_scheduler.shutdown()
```

## router.py

```python
from stock_platform.api.v1.deployment_performance_monitor import (
    router as deployment_performance_monitor_router,
)

api_router.include_router(
    deployment_performance_monitor_router
)
```

## 적용 파일

```text
src/stock_platform/strategy_deployment/performance_monitor_models.py
src/stock_platform/strategy_deployment/performance_monitor_entities.py
src/stock_platform/strategy_deployment/performance_collector.py
src/stock_platform/strategy_deployment/performance_monitor_repository.py
src/stock_platform/strategy_deployment/performance_monitor_service.py
src/stock_platform/strategy_deployment/performance_monitor_runtime.py
src/stock_platform/strategy_deployment/performance_monitor_scheduler.py
src/stock_platform/api/v1/deployment_performance_monitor.py
tests/test_deployment_performance_policy.py
tests/test_deployment_performance_monitor_service.py
README_STEP31_6.md
```

## 테스트

```powershell
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_deployment_performance_policy.py `
    tests\test_deployment_performance_monitor_service.py `
    tests\test_strategy_deployment_service.py `
    -q
```

## 검증 순서

```text
1. PAPER 성과 Run 저장 확인
2. 자동 중지 비활성화
3. check-active API 실행
4. HEALTHY/WARNING/STOP_REQUIRED 확인
5. 성과 계산값 검증
6. 테스트 환경에서 자동 중지 활성화
7. 기준 초과 시 STOPPED 확인
8. Runtime clear 또는 재배치 확인
```

## Git 커밋

```powershell
git add `
    README_STEP31_6.md `
    database\alembic\env.py `
    database\alembic\versions `
    src\stock_platform\strategy_deployment\performance_monitor_models.py `
    src\stock_platform\strategy_deployment\performance_monitor_entities.py `
    src\stock_platform\strategy_deployment\performance_collector.py `
    src\stock_platform\strategy_deployment\performance_monitor_repository.py `
    src\stock_platform\strategy_deployment\performance_monitor_service.py `
    src\stock_platform\strategy_deployment\performance_monitor_runtime.py `
    src\stock_platform\strategy_deployment\performance_monitor_scheduler.py `
    src\stock_platform\api\v1\deployment_performance_monitor.py `
    src\stock_platform\api\router.py `
    src\stock_platform\api\main.py `
    tests\test_deployment_performance_policy.py `
    tests\test_deployment_performance_monitor_service.py

git commit -m "feat(strategy): monitor paper deployment performance"
```

다음 단계는 STEP31-7 전략 배치·승인·Runtime·성과 상태를 통합하는
운영 대시보드입니다.
