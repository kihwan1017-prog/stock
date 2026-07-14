# STEP26-5 다종목 포트폴리오 백테스트

여러 종목에 고정 비중으로 자본을 배분하고 종목별 이동평균 전략 결과를 합산합니다.

## 적용 파일

```text
src/stock_platform/backtest/portfolio_models.py
src/stock_platform/backtest/portfolio_service.py
src/stock_platform/backtest/portfolio_report.py
src/stock_platform/api/v1/portfolio_backtests.py
tests/test_portfolio_backtest_service.py
tests/test_walk_forward_validation_service.py
```

`tests/test_walk_forward_validation_service.py`에는 이전 단계의 Window 개수 오류 수정이 포함되어 있습니다.

## 기존 파일 수정

`src/stock_platform/api/router.py`에 다음을 추가하세요.

```python
from stock_platform.api.v1.portfolio_backtests import router as portfolio_backtests_router
```

라우터 등록부 마지막에 추가합니다.

```python
api_router.include_router(portfolio_backtests_router)
```

`src/stock_platform/backtest/__init__.py`에는 필요 시 포트폴리오 클래스 import를 추가할 수 있지만 API 실행에는 필수가 아닙니다.

## API

```text
POST /api/v1/portfolio-backtests
```

요청 예:

```json
{
  "assets": [
    {"exchange_code": "KRX", "symbol": "005930", "weight": 0.30},
    {"exchange_code": "KRX", "symbol": "000660", "weight": 0.30},
    {"exchange_code": "UPBIT", "symbol": "KRW-BTC", "weight": 0.20}
  ],
  "start_date": "2023-01-01",
  "end_date": "2026-07-14",
  "initial_capital": 10000000,
  "short_window": 5,
  "long_window": 20,
  "stop_loss_ratio": 0.05,
  "take_profit_ratio": 0.10,
  "fee_ratio": 0.00015,
  "sell_tax_ratio": 0.0018,
  "slippage_ratio": 0.001
}
```

총 비중이 0.80이면 나머지 20%는 현금으로 유지됩니다. UPBIT 종목에는 매도세 0이 자동 적용됩니다.

## 테스트

```powershell
$env:PYTHONPATH = "D:\Projects\stock-platform\src"
python -m pytest `
    tests	test_portfolio_backtest_service.py `
    tests	test_walk_forward_validation_service.py `
    -q
```

신규 테이블이 없어 Alembic 작업은 필요 없습니다.

## Git 커밋

```powershell
git add `
    README_STEP26_5.md `
    src\stock_platform\backtest\portfolio_models.py `
    src\stock_platform\backtest\portfolio_service.py `
    src\stock_platform\backtest\portfolio_report.py `
    src\stock_platform\api\v1\portfolio_backtests.py `
    src\stock_platform\api\router.py `
    tests\test_portfolio_backtest_service.py `
    tests\test_walk_forward_validation_service.py

git commit -m "feat(backtest): add portfolio backtest"
```

다음 단계는 STEP26-6 정기 리밸런싱 포트폴리오 백테스트입니다.
