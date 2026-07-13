# STEP 20 - Indicator Engine

기존 `market.price_daily` 데이터를 사용해 기술적 지표를 계산합니다.

## 지원 지표

- 단순이동평균: MA5, MA20, MA60
- 지수이동평균: EMA12, EMA26
- RSI14 (Wilder 방식)
- MACD(12, 26, 9)
- 볼린저밴드(20, 2)
- ATR14 (Wilder 방식)
- 거래량 이동평균 20일

외부 계산 라이브러리를 추가하지 않고 Python `Decimal` 기반으로 구현했습니다.

## 적용 파일

```text
src/stock_platform/indicators/__init__.py
src/stock_platform/indicators/models.py
src/stock_platform/indicators/engine.py
src/stock_platform/indicators/service.py
src/stock_platform/api/v1/indicators.py
src/stock_platform/api/router.py
tests/test_indicator_engine.py
tests/test_indicator_service.py
```

ZIP을 다음 위치에 압축 해제합니다.

```text
D:\Projects\stock-platform
```

## 테스트

```powershell
cd D:\Projects\stock-platform
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_indicator_engine.py `
    tests\test_indicator_service.py `
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
GET /api/v1/indicators/daily/{exchange_code}/{symbol}
```

예시:

```text
GET /api/v1/indicators/daily/KRX/005930?start_date=2026-01-01&end_date=2026-07-13
```

업비트 예시:

```text
GET /api/v1/indicators/daily/UPBIT/KRW-BTC?start_date=2026-01-01&end_date=2026-07-13
```

MA60, MACD Signal 등이 계산되려면 충분한 과거 일봉이 있어야 합니다.
Service는 요청 시작일보다 180일 앞선 데이터부터 조회해 준비 기간을 확보합니다.

## Git 커밋

```powershell
git add `
    README_STEP20.md `
    src\stock_platform\indicators `
    src\stock_platform\api\v1\indicators.py `
    src\stock_platform\api\router.py `
    tests\test_indicator_engine.py `
    tests\test_indicator_service.py

git commit -m "feat(indicators): add daily technical indicator engine"
```

다음 단계는 STEP21 후보 종목 선정 엔진입니다.
