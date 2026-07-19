# STEP26-6 정기 리밸런싱 포트폴리오 백테스트

목표 비중을 기준으로 주기적으로 매수·매도하여 포트폴리오를
다시 맞추는 백테스트입니다.

## 리밸런싱 주기

```text
WEEKLY
MONTHLY
QUARTERLY
SEMIANNUAL
YEARLY
```

## 지원 기능

- 최대 50종목
- KRX·UPBIT 혼합
- 목표 비중 합계 최대 1
- 나머지 비중은 현금 유지
- 매수·매도 수수료 반영
- KRX 매도세 반영
- UPBIT 매도세 자동 0
- 슬리피지 반영
- 최소 비중 이탈 임계값
- 거래 상세
- 일별 자산 스냅샷
- 최종 종목 비중
- 총수익률
- CAGR
- MDD
- 연환산 변동성
- Sharpe
- Sortino
- Calmar
- 리밸런싱 횟수

## 적용 파일

```text
src/stock_platform/backtest/rebalancing_models.py
src/stock_platform/backtest/rebalancing_service.py
src/stock_platform/backtest/rebalancing_report.py
src/stock_platform/api/v1/portfolio_rebalancing_backtests.py
tests/test_portfolio_rebalancing_backtest.py
README_STEP26_6.md
```

신규 테이블은 없어 Alembic 작업은 필요 없습니다.

## router.py 추가

```python
from stock_platform.api.v1.portfolio_rebalancing_backtests import (
    router as portfolio_rebalancing_backtests_router,
)
```

```python
api_router.include_router(
    portfolio_rebalancing_backtests_router
)
```

## API

```text
POST /api/v1/portfolio-rebalancing-backtests
```

요청 예:

```json
{
  "assets": [
    {
      "exchange_code": "KRX",
      "symbol": "005930",
      "target_weight": 0.30
    },
    {
      "exchange_code": "KRX",
      "symbol": "000660",
      "target_weight": 0.30
    },
    {
      "exchange_code": "UPBIT",
      "symbol": "KRW-BTC",
      "target_weight": 0.20
    }
  ],
  "start_date": "2023-01-01",
  "end_date": "2026-07-14",
  "initial_capital": 10000000,
  "frequency": "MONTHLY",
  "fee_ratio": 0.00015,
  "sell_tax_ratio": 0.0018,
  "slippage_ratio": 0.001,
  "rebalance_threshold": 0.01
}
```

`rebalance_threshold=0.01`은 전체 평가금액 기준 비중 차이가
1% 미만인 종목은 매매하지 않는다는 의미입니다.

## 테스트

```powershell
cd D:\Projects\stock-platform
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_portfolio_rebalancing_backtest.py `
    -q
```

## Git 커밋

```powershell
git add `
    README_STEP26_6.md `
    src\stock_platform\backtest\rebalancing_models.py `
    src\stock_platform\backtest\rebalancing_service.py `
    src\stock_platform\backtest\rebalancing_report.py `
    src\stock_platform\api\v1\portfolio_rebalancing_backtests.py `
    src\stock_platform\api\router.py `
    tests\test_portfolio_rebalancing_backtest.py

git commit -m "feat(backtest): add portfolio rebalancing backtest"
```

다음 단계는 STEP27 실시간 자동매매 기반을 구현하기 전에
주문 안전장치와 실거래 전환 스위치를 추가하는 단계입니다.
