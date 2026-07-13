# STEP 19 - Upbit Daily Collector

이 패키지는 업비트 공개 시세 API에서 일봉을 수집하여
기존 `market.price_daily` 테이블에 UPSERT합니다.

## 포함 기능

- 업비트 공개 Quotation Client
- 페어 목록 조회
- 일 캔들 조회
- 최대 200개 단위 페이지 조회
- 날짜 범위 필터링 및 이어받기
- `market.price_daily` UPSERT
- FastAPI 및 Swagger
- 단위 테스트

## 공식 API

- 기본 URL: `https://api.upbit.com/v1`
- 페어 목록: `GET /v1/market/all`
- 일 캔들: `GET /v1/candles/days`
- 캔들 그룹 요청 제한: 초당 최대 10회

프로젝트 기본값은 여유를 두고 초당 8회입니다.

## 적용

ZIP을 다음 위치에 압축 해제합니다.

```text
D:\Projects\stock-platform
```

`settings.py`와 `api/router.py`는 STEP18까지 적용된 프로젝트를
기준으로 확장한 완성본입니다.

## 환경설정

비밀파일에 아래 값은 선택적으로 추가할 수 있습니다.

```text
E:\StockTrading\secrets\stock-platform.env
```

```dotenv
UPBIT_BASE_URL=https://api.upbit.com
UPBIT_TIMEOUT_SECONDS=10
UPBIT_MAX_REQUESTS_PER_SECOND=8
```

공개 시세 조회에는 업비트 API Key가 필요하지 않습니다.

## 테스트 패키지

```powershell
python -m pip install pytest pytest-asyncio
```

## 테스트

```powershell
cd D:\Projects\stock-platform
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_upbit_client.py `
    tests\test_upbit_daily_parser.py `
    tests\test_upbit_daily_collector.py `
    -q
```

## 비트코인 종목 등록

```powershell
psql -U stock_app -h localhost -p 5432 -d stock_platform `
    -c "INSERT INTO market.instrument (asset_type, exchange_code, symbol, name) VALUES ('CRYPTO', 'UPBIT', 'KRW-BTC', '비트코인') ON CONFLICT (exchange_code, symbol) DO NOTHING;"
```

## 서버 실행

```powershell
uvicorn stock_platform.api.main:app --reload --app-dir src
```

Swagger:

```text
http://127.0.0.1:8000/docs
```

페어 목록:

```text
GET /api/v1/upbit/markets?krw_only=true
```

일봉 동기화:

```text
POST /api/v1/upbit/daily/sync
```

요청 예:

```json
{
  "market": "KRW-BTC",
  "start_date": "2023-01-01",
  "end_date": "2026-07-13",
  "resume": true
}
```

## 결과 확인

```powershell
psql -U stock_app -h localhost -p 5432 -d stock_platform `
    -c "SELECT i.symbol, p.trade_date, p.open_price, p.high_price, p.low_price, p.close_price, p.volume, p.source FROM market.price_daily p JOIN market.instrument i ON i.instrument_id = p.instrument_id WHERE i.exchange_code = 'UPBIT' AND i.symbol = 'KRW-BTC' ORDER BY p.trade_date DESC LIMIT 20;"
```

## Git 커밋

```powershell
git add `
    README_STEP19.md `
    src\stock_platform\common\settings.py `
    src\stock_platform\brokers\upbit `
    src\stock_platform\collectors\upbit `
    src\stock_platform\api\v1\upbit.py `
    src\stock_platform\api\router.py `
    tests\test_upbit_client.py `
    tests\test_upbit_daily_parser.py `
    tests\test_upbit_daily_collector.py

git commit -m "feat(upbit): add daily candle synchronization"
```
