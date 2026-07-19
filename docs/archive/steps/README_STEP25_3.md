# STEP25-3 일일 파이프라인·재시도·의존성 제어

후보선정, AI 분석, 포지션 계획을 하나의 일일 운영 파이프라인으로
연결합니다.

## 실행 순서

```text
1. candidate_screening
2. ai_orchestration
3. position_planning
```

앞 단계가 성공해야 다음 단계가 실행됩니다.

각 단계는 기본 최대 3회 재시도합니다.

## 신규 테이블

```text
operation.pipeline_run
operation.pipeline_step_run
```

## Alembic 모델 등록

`database/alembic/env.py`에 추가합니다.

```python
from stock_platform.operation import pipeline_models as operation_pipeline_models  # noqa: F401
```

## 마이그레이션

```powershell
alembic revision --autogenerate `
    -m "create pipeline run tables"

alembic upgrade head --sql
alembic upgrade head
```

생성 파일에는 아래 두 테이블 생성만 있어야 합니다.

```text
operation.pipeline_run
operation.pipeline_step_run
```

`op.drop_table(...)`이 있으면 적용하지 마세요.

## API

일일 파이프라인 실행:

```text
POST /api/v1/pipelines/daily-strategy
```

요청 예:

```json
{
  "as_of_date": "2026-07-14",
  "trigger_type": "MANUAL",
  "retry_delay_seconds": 5
}
```

최신 파이프라인 조회:

```text
GET /api/v1/pipelines/latest
```

특정 파이프라인 조회:

```text
GET /api/v1/pipelines/latest?pipeline_name=daily_strategy_pipeline
```

## 실패 동작

- 한 단계가 실패하면 최대 3회 재시도
- 최종 실패 시 다음 단계 실행 중단
- 파이프라인 상태를 `FAILED`로 저장
- 단계별 오류 메시지와 시도 횟수 저장
- 성공 시 `SUCCESS`

## 테스트

```powershell
cd D:\Projects\stock-platform
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_daily_pipeline_service.py `
    -q
```

## Git 커밋

```powershell
git add `
    README_STEP25_3.md `
    database\alembic\env.py `
    database\alembic\versions `
    src\stock_platform\operation\pipeline_models.py `
    src\stock_platform\operation\pipeline_repository.py `
    src\stock_platform\scheduler\pipeline_service.py `
    src\stock_platform\scheduler\daily_pipeline.py `
    src\stock_platform\api\v1\pipelines.py `
    src\stock_platform\api\router.py `
    tests\test_daily_pipeline_service.py

git commit -m "feat(operation): add retryable daily pipeline"
```

다음 단계는 STEP25-4 공휴일·거래일 판단 및 스케줄러 안전장치입니다.
