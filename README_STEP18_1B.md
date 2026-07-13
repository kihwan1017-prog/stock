# STEP 18-1B - Kiwoom Daily Collector

현재 프로젝트의 STEP17 KiwoomRestClient와 호환되는 실제 일봉 Collector입니다.

## 적용 파일

```text
src/stock_platform/collectors/kiwoom/__init__.py
src/stock_platform/collectors/kiwoom/daily_collector.py
src/stock_platform/collectors/kiwoom/dto.py
src/stock_platform/collectors/kiwoom/pagination.py
src/stock_platform/collectors/kiwoom/parser.py
tests/test_kiwoom_daily_collector.py
tests/test_kiwoom_daily_parser.py
```

기존 STEP18-1A 골격 파일을 완성본으로 덮어씁니다.

## 키움 API

- TR: `ka10081`
- URL: `/api/dostk/chart`
- 요청: `stk_cd`, `base_dt`, `upd_stkpc_tp`
- 연속조회: 응답 헤더의 `cont-yn`, `next-key`를 다음 요청에 전달

Collector는 날짜 범위를 필터링하고 중복 일자를 제거한 뒤 오름차순으로 반환합니다.

## 테스트 의존성

비동기 pytest 테스트를 위해 다음 패키지를 설치합니다.

```powershell
python -m pip install pytest pytest-asyncio
```

`requirements.txt`에는 다음을 추가하는 것을 권장합니다.

```text
pytest
pytest-asyncio
```

## 테스트

```powershell
cd D:\Projects\stock-platform
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_kiwoom_daily_parser.py `
    tests\test_kiwoom_daily_collector.py `
    -q
```

## Git 커밋

```powershell
git add `
    README_STEP18_1B.md `
    src\stock_platform\collectors\kiwoom `
    tests\test_kiwoom_daily_parser.py `
    tests\test_kiwoom_daily_collector.py

git commit -m "feat(kiwoom): implement daily price collector"
```

## 다음 단계

STEP18-2에서 Collector 결과를 `PriceDailyService.save_many()`로 전달해
`market.price_daily`에 UPSERT하는 동기화 Service와 FastAPI API를 추가합니다.
