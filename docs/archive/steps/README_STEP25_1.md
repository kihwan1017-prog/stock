# STEP25-1 스케줄러 작업 등록 및 실행 이력

후보선정, AI 분석, 포지션 계획을 이름이 있는 작업으로 등록하고
수동 실행 결과를 PostgreSQL에 기록합니다.

## 신규 테이블

```text
operation.job_run_history
```

## Alembic 모델 등록

`database/alembic/env.py`에 추가합니다.

```python
from stock_platform.operation import job_models as operation_job_models  # noqa: F401
```

## 마이그레이션

```powershell
alembic revision --autogenerate `
    -m "create job run history table"

alembic upgrade head --sql
alembic upgrade head
```

생성 파일에는 `operation.job_run_history` 생성만 있어야 합니다.
`op.drop_table(...)`이 있으면 적용하지 마세요.

## 등록 작업

```text
candidate_screening
ai_orchestration
position_planning
```

## API

등록 작업 목록:

```text
GET /api/v1/jobs
```

작업 실행:

```text
POST /api/v1/jobs/{job_name}/execute
```

실행 이력:

```text
GET /api/v1/jobs/history
```

## 후보선정 실행 예

```text
POST /api/v1/jobs/candidate_screening/execute
```

```json
{
  "trigger_type": "MANUAL",
  "payload": {
    "exchange_code": "KRX",
    "as_of_date": "2026-07-14",
    "limit": 30,
    "minimum_score": 50,
    "require_all_rules": false,
    "run_type": "DAILY"
  }
}
```

## AI 분석 실행 예

```text
POST /api/v1/jobs/ai_orchestration/execute
```

```json
{
  "trigger_type": "MANUAL",
  "payload": {
    "exchange_code": "KRX",
    "limit": 10,
    "news_limit": 20,
    "disclosure_limit": 20,
    "lookback_days": 90
  }
}
```

## 포지션 계획 실행 예

```text
POST /api/v1/jobs/position_planning/execute
```

```json
{
  "trigger_type": "MANUAL",
  "payload": {
    "exchange_code": "KRX",
    "policy_id": 1,
    "portfolio_value": 10000000,
    "available_cash": 5000000,
    "current_position_count": 0,
    "limit": 5,
    "minimum_ai_score": 70,
    "minimum_confidence": 0.5,
    "allowed_actions": [
      "WATCH",
      "REVIEW"
    ]
  }
}
```

## 테스트

```powershell
cd D:\Projects\stock-platform
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_job_registry.py `
    tests\test_job_execution_service.py `
    -q
```

## Git 커밋

```powershell
git add `
    README_STEP25_1.md `
    database\alembic\env.py `
    database\alembic\versions `
    src\stock_platform\operation\job_models.py `
    src\stock_platform\operation\job_repository.py `
    src\stock_platform\operation\job_service.py `
    src\stock_platform\scheduler `
    src\stock_platform\api\v1\jobs.py `
    src\stock_platform\api\router.py `
    tests\test_job_registry.py `
    tests\test_job_execution_service.py

git commit -m "feat(operation): add scheduler job execution history"
```

이번 단계는 작업 등록과 수동 실행 기반입니다.
다음 단계에서 APScheduler 또는 Windows 작업 스케줄러에 연결해
장전·장중·장후 자동 실행 시간을 구성할 수 있습니다.
