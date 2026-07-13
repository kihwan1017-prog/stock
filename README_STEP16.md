# STEP 16 - PriceDaily 적용 안내

이 묶음은 다음 기능을 추가합니다.

- `market.price_daily` SQLAlchemy ORM
- PostgreSQL UPSERT 기반 Repository
- 일봉 조회·저장 Service
- FastAPI 일봉 조회 API
- 기본 단위 테스트

## 적용 전

프로젝트 루트가 다음 위치라고 가정합니다.

```text
D:\Projects\stock-platform
```

현재 변경사항을 먼저 확인하세요.

```powershell
git status
```

작업 중인 변경이 있다면 먼저 커밋하거나 백업하세요.

## 파일 적용

ZIP 파일을 프로젝트 루트에 압축 해제합니다.

```text
D:\Projects\stock-platform
```

동일한 파일이 있으면 덮어쓰기 전에 내용을 확인하세요.

## Alembic 마이그레이션 생성

가상환경을 활성화한 프로젝트 루트에서 실행합니다.

```powershell
alembic revision --autogenerate -m "create market price daily table"
```

생성 파일의 `upgrade()`에는 `market.price_daily` 생성만 있어야 합니다.

다음 구문이 있으면 적용하지 마세요.

```python
op.drop_table(...)
```

SQL 미리보기:

```powershell
alembic upgrade head --sql
```

적용:

```powershell
alembic upgrade head
```

테이블 확인:

```powershell
psql -U stock_app -h localhost -p 5432 -d stock_platform -c "\d market.price_daily"
```

## 테스트 데이터

먼저 `market.instrument`에 종목이 있어야 합니다.

```sql
INSERT INTO market.instrument
    (asset_type, exchange_code, symbol, name)
VALUES
    ('STOCK', 'KRX', '005930', '삼성전자')
ON CONFLICT (exchange_code, symbol) DO NOTHING;
```

일봉 테스트 데이터:

```sql
INSERT INTO market.price_daily
(
    instrument_id,
    trade_date,
    open_price,
    high_price,
    low_price,
    close_price,
    volume,
    trade_value,
    change_rate,
    source
)
SELECT
    instrument_id,
    DATE '2026-07-10',
    86000,
    87500,
    85500,
    87200,
    12000000,
    1046400000000,
    1.28,
    'MANUAL'
FROM market.instrument
WHERE exchange_code = 'KRX'
  AND symbol = '005930'
ON CONFLICT (instrument_id, trade_date)
DO UPDATE SET
    close_price = EXCLUDED.close_price,
    updated_at = now();
```

## API 실행

```powershell
uvicorn stock_platform.api.main:app --reload --app-dir src
```

Swagger:

```text
http://127.0.0.1:8000/docs
```

조회 예:

```text
GET /api/v1/prices/daily/KRX/005930?start_date=2026-07-01&end_date=2026-07-31
GET /api/v1/prices/latest/KRX/005930
```

## 테스트 실행

`pytest`가 없으면 설치합니다.

```powershell
python -m pip install pytest
```

테스트:

```powershell
$env:PYTHONPATH = "D:\Projects\stock-platform\src"
python -m pytest tests\test_price_daily_service.py -q
```

## Git 커밋

```powershell
git add .
git commit -m "feat(market): add daily price feature"
```
