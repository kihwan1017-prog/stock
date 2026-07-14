# STEP25-5 일일 운영 리포트 및 장애 요약

파이프라인, 작업 실행, 후보선정, AI 분석, 포지션 계획,
모의 계좌 손익을 하나의 일일 운영 리포트로 저장합니다.

## 신규 테이블

```text
operation.daily_operations_report
```

## Alembic 모델 등록

`database/alembic/env.py`에 추가합니다.

```python
from stock_platform.operation import report_models as operation_report_models  # noqa: F401
```

## 마이그레이션

```powershell
alembic revision --autogenerate `
    -m "create daily operations report table"

alembic upgrade head --sql
alembic upgrade head
```

생성 파일에는 아래 테이블 생성만 있어야 합니다.

```text
operation.daily_operations_report
```

`op.drop_table(...)`이 있으면 적용하지 마세요.

## 리포트 항목

- 파이프라인 상태
- 성공한 작업 수
- 실패한 작업 수
- 규칙 기반 후보 수
- AI 후보 수
- 승인된 포지션 계획 수
- 총 계획 주문금액
- 실현손익
- 미실현손익
- 실패 작업 요약
- 관련 실행 ID

## 리포트 생성 API

```text
POST /api/v1/daily-reports
```

요청 예:

```json
{
  "report_date": "2026-07-14",
  "exchange_code": "KRX",
  "paper_account_id": 1,
  "current_prices": {
    "KRX:005930": 72000,
    "KRX:000660": 250000
  }
}
```

`paper_account_id`와 `current_prices`를 생략하면
계좌 미실현손익은 0으로 기록됩니다.

## 리포트 조회

```text
GET /api/v1/daily-reports/2026-07-14/KRX
GET /api/v1/daily-reports?exchange_code=KRX&limit=30
```

## 스케줄러 작업

STEP25-1 작업 목록에 아래 작업이 추가됩니다.

```text
daily_operations_report
```

즉시 실행 예:

```text
POST /api/v1/jobs/daily_operations_report/execute
```

```json
{
  "trigger_type": "MANUAL",
  "payload": {
    "report_date": "2026-07-14",
    "exchange_code": "KRX",
    "paper_account_id": 1,
    "current_prices": {
      "KRX:005930": 72000
    }
  }
}
```

## 테스트

```powershell
cd D:\Projects\stock-platform
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_daily_operations_report_service.py `
    -q
```

## Git 커밋

```powershell
git add `
    README_STEP25_5.md `
    database\alembic\env.py `
    database\alembic\versions `
    src\stock_platform\operation\report_models.py `
    src\stock_platform\operation\report_repository.py `
    src\stock_platform\operation\report_service.py `
    src\stock_platform\scheduler\report_job.py `
    src\stock_platform\scheduler\factory.py `
    src\stock_platform\api\v1\daily_reports.py `
    src\stock_platform\api\router.py `
    tests\test_daily_operations_report_service.py

git commit -m "feat(operation): add daily operations report"
```

다음 단계는 STEP26 통합 백테스트 엔진입니다.
