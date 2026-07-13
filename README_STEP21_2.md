# STEP21-2 후보 종목 점수 계산기

STEP20 기술적 지표와 일봉 데이터를 이용해 단일 종목을 100점 만점으로 평가합니다.

## 점수 구성

```text
거래량 급증       20점
이동평균 추세     20점
RSI               15점
MACD              20점
60일 신고가       15점
ATR 변동성        10점
----------------------
합계             100점
```

## 필수 규칙

- 거래량이 20일 평균의 2배 이상
- MA5 > MA20 > MA60
- RSI14가 40~70
- MACD > Signal
- 종가가 직전 60일 최고가 이상
- ATR 비율이 종가의 8% 이하

## 적용

ZIP을 다음 위치에 압축 해제합니다.

```text
D:\Projects\stock-platform
```

기존 STEP21-1 `rules.py`는 완성된 버전으로 교체됩니다.

## 테스트

```powershell
cd D:\Projects\stock-platform
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_candidate_rule_engine.py `
    tests\test_candidate_scoring.py `
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
GET /api/v1/candidates/evaluate/{exchange_code}/{symbol}
```

예:

```text
GET /api/v1/candidates/evaluate/KRX/005930?as_of_date=2026-07-13
```

업비트:

```text
GET /api/v1/candidates/evaluate/UPBIT/KRW-BTC?as_of_date=2026-07-13
```

## Git 커밋

```powershell
git add `
    README_STEP21_2.md `
    src\stock_platform\screener `
    src\stock_platform\api\v1\candidates.py `
    src\stock_platform\api\router.py `
    tests\test_candidate_rule_engine.py `
    tests\test_candidate_scoring.py

git commit -m "feat(screener): add candidate scoring engine"
```

다음 단계 STEP21-3에서는 여러 종목을 일괄 평가해 점수순으로 정렬하고 Top30을 반환합니다.
