# STEP26-2 백테스트 결과 저장 및 파라미터 비교

STEP26-1 백테스트 결과를 PostgreSQL에 저장하고 여러 실행의
전략 파라미터와 성과를 비교합니다.

## 신규 테이블

```text
backtest.backtest_run
backtest.backtest_trade
backtest.backtest_equity
```

## Alembic 모델 등록

`database/alembic/env.py`에 추가합니다.

```python
from stock_platform.backtest import persistence_models as backtest_models  # noqa: F401
```

## 마이그레이션

```powershell
alembic revision --autogenerate `
    -m "create backtest result tables"

alembic upgrade head --sql
alembic upgrade head
```

생성 파일에는 아래 테이블 생성만 있어야 합니다.

```text
backtest.backtest_run
backtest.backtest_trade
backtest.backtest_equity
```

`op.drop_table(...)`이 있으면 적용하지 마세요.

## 실행 및 저장 API

```text
POST /api/v1/backtest-runs
```

요청 예:

```json
{
  "exchange_code": "KRX",
  "symbol": "005930",
  "start_date": "2023-01-01",
  "end_date": "2026-07-14",
  "initial_capital": 10000000,
  "short_window": 5,
  "long_window": 20,
  "stop_loss_ratio": 0.05,
  "take_profit_ratio": 0.10,
  "position_ratio": 0.20,
  "fee_ratio": 0.00015,
  "sell_tax_ratio": 0.0018,
  "slippage_ratio": 0.001
}
```

## 실행 결과 상세 조회

```text
GET /api/v1/backtest-runs/{backtest_run_id}
```

반환 항목:

- 실행 요약
- 거래 상세
- 일별 자산 곡선

## 실행 목록

```text
GET /api/v1/backtest-runs
GET /api/v1/backtest-runs?exchange_code=KRX&symbol=005930
```

## 파라미터 성과 비교

```text
GET /api/v1/backtest-runs/compare/ranking
```

예:

```text
GET /api/v1/backtest-runs/compare/ranking?exchange_code=KRX&symbol=005930&limit=20
```

비교 점수:

```text
점수
=
총 수익률
- 최대 낙폭
+ 승률 × 0.1
```

이 점수는 단순 비교용이며 실제 전략 채택 기준으로 바로 사용하면
안 됩니다. 거래 수, 기간, 시장 국면, 과최적화 여부를 함께 검토해야
합니다.

## 테스트

```powershell
cd D:\Projects\stock-platform
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_backtest_engine.py `
    tests\test_backtest_comparison_service.py `
    -q
```

## Git 커밋

```powershell
git add `
    README_STEP26_2.md `
    database\alembic\env.py `
    database\alembic\versions `
    src\stock_platform\backtest `
    src\stock_platform\api\v1\backtest_runs.py `
    src\stock_platform\api\router.py `
    tests\test_backtest_comparison_service.py

git commit -m "feat(backtest): persist and compare backtest results"
```

다음 단계는 STEP26-3 파라미터 조합 일괄 실행 및 최적화 후보 선정입니다.
