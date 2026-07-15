# STEP31-5 전략 자동배치·Runtime 교체 통합 파이프라인

최신 LLM 전략 선택부터 승인정책, PAPER 배치, Dry Run, 상태 이전,
Runtime 교체, 실패 시 Rollback까지 한 번의 파이프라인으로
연결합니다.

## 전체 흐름

```text
최신 LLM 전략 선택
  ↓
승인정책 평가
  ↓
APPROVED
  ↓
PAPER 전략 배치
  ↓
Dry Run
  ↓
기존 전략 상태 export
  ↓
새 전략 상태 import
  ↓
Runtime 교체
  ↓
실패 시 Rollback
```

## 신규 테이블

```text
trading.strategy_deployment_pipeline
```

저장 항목:

```text
전략 선택 Run ID
승인 Run ID
배치 ID
Runtime Switch ID
전략 코드
시장·종목
파이프라인 상태
요청자
처리 메시지
상세 JSON
시작·완료 시각
```

## 파이프라인 상태

```text
APPROVAL_REJECTED
DEPLOYED
SWITCHED
ROLLED_BACK
FAILED
```

## Alembic 등록

`database/alembic/env.py`:

```python
from stock_platform.strategy_deployment import pipeline_entities as strategy_pipeline_entities  # noqa: F401
```

## 마이그레이션

```powershell
alembic revision --autogenerate `
    -m "create strategy deployment pipeline table"

alembic upgrade head --sql
alembic upgrade head
```

예상하지 않은 삭제 작업이 있으면 적용하지 마세요.

## API

파이프라인 수동 실행:

```text
POST /api/v1/strategy-deployment-pipeline/run
```

```json
{
  "market_code": "KRX",
  "symbol": "005930",
  "requested_by": "operator",
  "sample_context": {
    "price": 72000,
    "volume": 100000
  },
  "allow_auto_deploy": false
}
```

초기 검증에서는 반드시 다음을 사용합니다.

```json
{
  "allow_auto_deploy": false
}
```

이 경우 승인평가까지만 수행하고 실제 배치·Runtime 교체는 하지
않습니다.

상태 조회:

```text
GET /api/v1/strategy-deployment-pipeline/status
```

이력 조회:

```text
GET /api/v1/strategy-deployment-pipeline/history
```

## 자동 실행

환경변수:

```dotenv
STRATEGY_AUTO_DEPLOY_ENABLED=false
```

모의투자 검증이 끝난 뒤에만 다음으로 변경합니다.

```dotenv
STRATEGY_AUTO_DEPLOY_ENABLED=true
```

스케줄러는 매일 16:20에 파이프라인을 실행합니다.

```text
strategy_deployment_pipeline
```

## main.py 연결

```python
from stock_platform.strategy_deployment.pipeline_scheduler import (
    strategy_deployment_pipeline_scheduler,
)
```

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()

    strategy_deployment_pipeline_scheduler.start()

    yield

    await strategy_deployment_pipeline_scheduler.shutdown()
```

기존 `strategy_approval_scheduler`와 동시에 켜면 동일 전략이 두 번
평가될 수 있습니다.

STEP31-5 적용 후에는 다음 중 하나만 사용하세요.

```text
권장: strategy_deployment_pipeline_scheduler
중지: strategy_approval_scheduler
```

## router.py 추가

```python
from stock_platform.api.v1.strategy_deployment_pipeline import (
    router as strategy_deployment_pipeline_router,
)

api_router.include_router(
    strategy_deployment_pipeline_router
)
```

## 포함 파일

```text
src/stock_platform/strategy_deployment/pipeline_models.py
src/stock_platform/strategy_deployment/pipeline_entities.py
src/stock_platform/strategy_deployment/pipeline_repository.py
src/stock_platform/strategy_deployment/pipeline_service.py
src/stock_platform/strategy_deployment/pipeline_runtime.py
src/stock_platform/strategy_deployment/pipeline_scheduler.py
src/stock_platform/api/v1/strategy_deployment_pipeline.py
tests/test_strategy_deployment_pipeline_models.py
tests/test_strategy_deployment_pipeline_runtime.py
README_STEP31_5.md
```

## 테스트

```powershell
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_strategy_deployment_pipeline_models.py `
    tests\test_strategy_deployment_pipeline_runtime.py `
    tests\test_strategy_approval_policy.py `
    tests\test_strategy_dry_run.py `
    tests\test_strategy_state_transfer.py `
    -q
```

## 검증 순서

```text
1. STRATEGY_AUTO_DEPLOY_ENABLED=false
2. 최신 LLM 전략 선택 확인
3. 파이프라인 수동 실행
4. APPROVAL_REJECTED 또는 승인결과 확인
5. Strategy Factory 등록 확인
6. PAPER 환경에서 allow_auto_deploy=true 실행
7. Deployment 생성 확인
8. Dry Run 결과 확인
9. Runtime 교체 확인
10. 실패 시 ROLLED_BACK 확인
```

## Git 커밋

```powershell
git add `
    README_STEP31_5.md `
    database\alembic\env.py `
    database\alembic\versions `
    src\stock_platform\strategy_deployment\pipeline_models.py `
    src\stock_platform\strategy_deployment\pipeline_entities.py `
    src\stock_platform\strategy_deployment\pipeline_repository.py `
    src\stock_platform\strategy_deployment\pipeline_service.py `
    src\stock_platform\strategy_deployment\pipeline_runtime.py `
    src\stock_platform\strategy_deployment\pipeline_scheduler.py `
    src\stock_platform\api\v1\strategy_deployment_pipeline.py `
    src\stock_platform\api\router.py `
    src\stock_platform\api\main.py `
    tests\test_strategy_deployment_pipeline_models.py `
    tests\test_strategy_deployment_pipeline_runtime.py

git commit -m "feat(strategy): add end-to-end deployment pipeline"
```

다음 단계는 STEP31-6 배치 전략의 모의투자 성과 자동 수집과
성과 저하 시 자동 중지입니다.
