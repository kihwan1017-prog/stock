# STEP31-4 전략 자동 배치 승인정책과 스케줄러

LLM이 선택한 전략을 즉시 배치하지 않고, 성과·위험·Runtime 상태를
정책으로 검증한 뒤 PAPER 배치를 승인하거나 거부합니다.

## 신규 테이블

```text
trading.strategy_approval_run
```

## 기본 승인 조건

```text
LLM 신뢰도             >= 0.60
성과 Run 유형          = WALK_FORWARD
총수익률               > 0
Sharpe Ratio           >= 0.80
MDD                    <= 0.20
승률                   >= 0.45
거래 수                >= 20
Kill Switch            INACTIVE
Runtime 오류           없음
```

기본 정책 파일:

```text
src/stock_platform/strategy_deployment/policy_models.py
```

## Alembic 등록

`database/alembic/env.py`:

```python
from stock_platform.strategy_deployment import policy_entities as strategy_policy_entities  # noqa: F401
```

## 마이그레이션

```powershell
alembic revision --autogenerate `
    -m "create strategy approval run table"

alembic upgrade head --sql
alembic upgrade head
```

예상하지 않은 삭제 작업이 있으면 적용하지 마세요.

## API

최신 LLM 선택 전략 평가:

```text
POST /api/v1/strategy-policy/evaluate
```

```json
{
  "market_code": "KRX",
  "symbol": "005930",
  "requested_by": "operator",
  "auto_deploy": false
}
```

강제 PAPER 배치:

```text
POST /api/v1/strategy-policy/{approval_run_id}/force
```

수동 거부:

```text
POST /api/v1/strategy-policy/{approval_run_id}/reject
```

승인 이력:

```text
GET /api/v1/strategy-policy/history
```

## 자동 배치 설정

초기에는 반드시 비활성화합니다.

```dotenv
STRATEGY_AUTO_DEPLOY_ENABLED=false
```

모의투자 검증 후에만 다음으로 변경합니다.

```dotenv
STRATEGY_AUTO_DEPLOY_ENABLED=true
```

이 설정은 PAPER 전략 배치에만 사용됩니다. LIVE 배치는 지원하지
않습니다.

## Scheduler

매일 16:10에 최신 LLM 선택 전략을 평가합니다.

```text
strategy_approval_after_market
```

`main.py` 연결:

```python
from stock_platform.strategy_deployment.policy_scheduler import (
    strategy_approval_scheduler,
)
```

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()

    strategy_approval_scheduler.start()

    yield

    await strategy_approval_scheduler.shutdown()
```

## router.py

```python
from stock_platform.api.v1.strategy_approval_policy import (
    router as strategy_approval_policy_router,
)

api_router.include_router(
    strategy_approval_policy_router
)
```

## 포함 파일

```text
src/stock_platform/strategy_deployment/policy_models.py
src/stock_platform/strategy_deployment/policy_entities.py
src/stock_platform/strategy_deployment/policy_repository.py
src/stock_platform/strategy_deployment/policy_service.py
src/stock_platform/strategy_deployment/automation_service.py
src/stock_platform/strategy_deployment/policy_scheduler.py
src/stock_platform/api/v1/strategy_approval_policy.py
tests/test_strategy_approval_policy.py
tests/test_strategy_auto_deployment_service.py
README_STEP31_4.md
```

## 테스트

```powershell
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_strategy_approval_policy.py `
    tests\test_strategy_auto_deployment_service.py `
    tests\test_strategy_deployment_service.py `
    tests\test_strategy_selector_service.py `
    -q
```

## Git 커밋

```powershell
git add `
    README_STEP31_4.md `
    database\alembic\env.py `
    database\alembic\versions `
    src\stock_platform\strategy_deployment\policy_models.py `
    src\stock_platform\strategy_deployment\policy_entities.py `
    src\stock_platform\strategy_deployment\policy_repository.py `
    src\stock_platform\strategy_deployment\policy_service.py `
    src\stock_platform\strategy_deployment\automation_service.py `
    src\stock_platform\strategy_deployment\policy_scheduler.py `
    src\stock_platform\api\v1\strategy_approval_policy.py `
    src\stock_platform\api\router.py `
    src\stock_platform\api\main.py `
    tests\test_strategy_approval_policy.py `
    tests\test_strategy_auto_deployment_service.py

git commit -m "feat(strategy): add automated deployment approval policy"
```

다음 단계는 STEP31-5 자동 배치 후 Runtime 교체·Dry Run·Rollback까지
하나의 파이프라인으로 연결하는 단계입니다.
