# STEP 18-2 - Kiwoom Daily Sync

이 ZIP은 STEP18-1B Collector 결과를 기존 `PriceDailyService`로 저장하고,
Swagger에서 실행할 수 있는 동기화 API를 추가합니다.

## 포함 파일

```text
src/stock_platform/collectors/kiwoom/sync_service.py
src/stock_platform/api/v1/sync.py
src/stock_platform/api/router.py
tests/test_kiwoom_daily_sync_service.py
```

## 적용 위치

ZIP을 다음 위치에 압축 해제합니다.

```text
D:\Projects\stock-platform
```

`src/stock_platform/api/router.py`는 기존 Router에 Sync Router를 추가한
완성본이므로 덮어씁니다.

## 사전 조건

1. STEP17 키움 REST Client 적용
2. STEP18-1B 일봉 Collector 적용
3. `market.instrument`에 종목 등록
4. `market.price_daily` 테이블 생성
5. 키움 API 키 등록

비밀파일:

```text
E:\StockTrading\secrets\stock-platform.env
```

예:

```dotenv
KIWOOM_APP_KEY=발급받은_앱키
KIWOOM_SECRET_KEY=발급받은_시크릿키
KIWOOM_USE_MOCK=true
```

## 종목 등록

```sql
INSERT INTO market.instrument
    (asset_type, exchange_code, symbol, name)
VALUES
    ('STOCK', 'KRX', '005930', '삼성전자')
ON CONFLICT (exchange_code, symbol) DO NOTHING;
```

## 단위 테스트

```powershell
cd D:\Projects\stock-platform
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_kiwoom_daily_sync_service.py `
    -q
```

## 서버 실행

```powershell
uvicorn stock_platform.api.main:app --reload --app-dir src
```

Swagger:

```text
http://127.0.0.1:8000/docs
```

API:

```text
POST /api/v1/sync/kiwoom/daily
```

요청 예:

```json
{
  "symbol": "005930",
  "start_date": "2026-01-01",
  "end_date": "2026-07-13",
  "exchange_code": "KRX",
  "adjusted_price": true,
  "resume": true
}
```

`resume=true`이면 DB의 최신 저장일 다음 날부터 이어서 수집합니다.

## 결과 확인

```powershell
psql -U stock_app -h localhost -p 5432 -d stock_platform `
    -c "SELECT trade_date, open_price, high_price, low_price, close_price, volume, source FROM market.price_daily ORDER BY trade_date DESC LIMIT 20;"
```

## Git 커밋

```powershell
git add `
    README_STEP18_2.md `
    src\stock_platform\collectors\kiwoom\sync_service.py `
    src\stock_platform\api\v1\sync.py `
    src\stock_platform\api\router.py `
    tests\test_kiwoom_daily_sync_service.py

git commit -m "feat(kiwoom): add daily price synchronization"
```
