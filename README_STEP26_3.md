# STEP26-3 파라미터 조합 일괄 실행

여러 이동평균·손절·익절·포지션 비율 조합을 일괄 백테스트하고
상위 전략 후보를 선정합니다.

## 조합 대상

```text
short_windows
long_windows
stop_loss_ratios
take_profit_ratios
position_ratios
```

각 성공 결과는 STEP26-2 테이블에 자동 저장됩니다.

```text
backtest.backtest_run
backtest.backtest_trade
backtest.backtest_equity
```

## 적용 파일

```text
src/stock_platform/backtest/grid_models.py
src/stock_platform/backtest/grid_service.py
src/stock_platform/backtest/grid_report.py
src/stock_platform/backtest/__init__.py
src/stock_platform/api/v1/backtest_grid.py
src/stock_platform/api/router.py
tests/test_backtest_grid_service.py
```

신규 테이블은 없어 Alembic 작업은 필요 없습니다.

## API

```text
POST /api/v1/backtest-grid
```

요청 예:

```json
{
  "exchange_code": "KRX",
  "symbol": "005930",
  "start_date": "2023-01-01",
  "end_date": "2026-07-14",
  "initial_capital": 10000000,
  "short_windows": [5, 10, 20],
  "long_windows": [20, 60, 120],
  "stop_loss_ratios": [0.03, 0.05],
  "take_profit_ratios": [0.08, 0.10, 0.15],
  "position_ratios": [0.10, 0.20],
  "fee_ratio": 0.00015,
  "sell_tax_ratio": 0.0018,
  "slippage_ratio": 0.001,
  "top_n": 10
}
```

위 요청은 최대 108개 조합을 실행합니다.

## 조합 제한

서버 보호를 위해 조합 수는 최대 500개입니다.

```text
short 개수
× long 개수
× 손절 개수
× 익절 개수
× 포지션 비율 개수
<= 500
```

## 순위 점수

```text
점수
=
총 수익률
- 최대 낙폭
+ 승률 × 0.1
```

응답에는 다음이 포함됩니다.

- 전체 조합 수
- 성공 수
- 실패 수
- 상위 전략 후보
- 실패한 파라미터와 오류
- 사람이 읽기 쉬운 요약 문자열

## 주의

파라미터 조합을 많이 실행하면 DB와 CPU 사용량이 크게 증가합니다.

먼저 적은 조합으로 검증하세요.

```json
{
  "short_windows": [5, 10],
  "long_windows": [20, 60],
  "stop_loss_ratios": [0.03],
  "take_profit_ratios": [0.10],
  "position_ratios": [0.20]
}
```

백테스트 최고 점수를 실거래 전략으로 바로 사용하면 안 됩니다.
과최적화 방지를 위해 학습기간과 검증기간을 분리해야 합니다.

## 테스트

```powershell
cd D:\Projects\stock-platform
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_backtest_grid_service.py `
    -q
```

## Git 커밋

```powershell
git add `
    README_STEP26_3.md `
    src\stock_platform\backtest\grid_models.py `
    src\stock_platform\backtest\grid_service.py `
    src\stock_platform\backtest\grid_report.py `
    src\stock_platform\backtest\__init__.py `
    src\stock_platform\api\v1\backtest_grid.py `
    src\stock_platform\api\router.py `
    tests\test_backtest_grid_service.py

git commit -m "feat(backtest): add parameter grid search"
```

다음 단계는 STEP26-4 워크포워드 검증으로 과최적화를 점검합니다.
