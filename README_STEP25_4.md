# STEP25-4 거래일·공휴일 판단 및 파이프라인 안전장치

거래소별 거래일 달력을 저장하고 휴장일에는 일일 전략
파이프라인을 실행하지 않도록 안전장치를 추가합니다.

## 신규 테이블

```text
operation.trading_calendar_day
```

## Alembic 모델 등록

`database/alembic/env.py`에 추가합니다.

```python
from stock_platform.operation import calendar_models as operation_calendar_models  # noqa: F401
```

## 마이그레이션

```powershell
alembic revision --autogenerate `
    -m "create trading calendar table"

alembic upgrade head --sql
alembic upgrade head
```

생성 파일에는 아래 테이블 생성만 있어야 합니다.

```text
operation.trading_calendar_day
```

`op.drop_table(...)`이 있으면 적용하지 마세요.

## 판단 우선순위

KRX:

```text
1. DB에 등록된 거래일/휴장일
2. 토요일·일요일은 휴장
3. 등록되지 않은 평일은 거래일로 임시 판단
```

UPBIT:

```text
연중무휴 거래일
```

실제 운영 전 KRX 휴장일 데이터를 DB에 등록해야 합니다.

## 달력 등록 API

```text
POST /api/v1/trading-calendar/import
```

요청 예:

```json
{
  "exchange_code": "KRX",
  "days": [
    {
      "calendar_date": "2026-08-17",
      "is_trading_day": false,
      "holiday_name": "대체공휴일",
      "source_code": "MANUAL"
    },
    {
      "calendar_date": "2026-12-31",
      "is_trading_day": false,
      "holiday_name": "연말 휴장일",
      "source_code": "MANUAL"
    }
  ]
}
```

## 거래일 확인

```text
GET /api/v1/trading-calendar/KRX/2026-08-17
GET /api/v1/trading-calendar/UPBIT/2026-08-17
```

## 직전·다음 거래일

```text
GET /api/v1/trading-calendar/KRX/2026-07-18/previous
GET /api/v1/trading-calendar/KRX/2026-07-18/next
```

## 안전 파이프라인

```text
POST /api/v1/guarded-pipelines/daily-strategy
```

요청 예:

```json
{
  "exchange_code": "KRX",
  "as_of_date": "2026-07-18",
  "trigger_type": "MANUAL",
  "retry_delay_seconds": 5
}
```

휴장일 응답:

```json
{
  "executed": false,
  "reason_code": "NON_TRADING_DAY",
  "pipeline_run_id": null,
  "pipeline_status_code": null,
  "steps": []
}
```

## 테스트

```powershell
cd D:\Projects\stock-platform
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_trading_calendar_service.py `
    tests\test_guarded_pipeline.py `
    -q
```

## Git 커밋

```powershell
git add `
    README_STEP25_4.md `
    database\alembic\env.py `
    database\alembic\versions `
    src\stock_platform\operation\calendar_models.py `
    src\stock_platform\operation\calendar_repository.py `
    src\stock_platform\operation\calendar_service.py `
    src\stock_platform\scheduler\guarded_pipeline.py `
    src\stock_platform\api\v1\trading_calendar.py `
    src\stock_platform\api\v1\guarded_pipeline.py `
    src\stock_platform\api\router.py `
    tests\test_trading_calendar_service.py `
    tests\test_guarded_pipeline.py

git commit -m "feat(operation): add trading calendar guard"
```

다음 단계는 STEP25-5 일일 운영 리포트와 장애 요약입니다.
