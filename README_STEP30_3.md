# STEP30-3 기존 백테스트 결과 자동 저장 연동

기존 백테스트 결과를 STEP30-1의 전략 성과 Run/Metric 테이블에
자동 저장합니다.

## 처리 흐름

```text
기존 백테스트 실행
  ↓
백테스트 결과 dict
  ↓
BacktestResultPayloadAdapter
  ↓
BacktestPerformanceMapper
  ↓
strategy_performance_run 생성
  ↓
strategy_performance_metric 저장
```

## 자동 계산 지표

백테스트 결과에서 다음 값을 자동 계산합니다.

```text
총수익률
승률
평균 수익
평균 손실
Profit Factor
순이익
```

계산식:

```text
총수익률
= (최종자본 - 초기자본) / 초기자본

승률
= 승리 거래 수 / 전체 거래 수

Profit Factor
= 총이익 / abs(총손실)
```

## 수익률 저장 형식

수익률과 MDD는 백분율 숫자가 아니라 소수 비율로 저장합니다.

```text
10%  → 0.10
5%   → 0.05
-3%  → -0.03
```

기존 백테스트 결과가 `10`처럼 백분율 단위라면 Adapter에서
`100`으로 나누도록 프로젝트에 맞게 조정해야 합니다.

## 지원하는 결과 필드 별칭

예:

```text
initial_capital / starting_capital / start_balance
final_capital / ending_capital / end_balance
total_trade_count / trade_count / total_trades
winning_trade_count / win_count / winning_trades
losing_trade_count / loss_count / losing_trades
gross_profit_amount / gross_profit / total_profit
gross_loss_amount / gross_loss / total_loss
maximum_drawdown_rate / max_drawdown_rate / mdd
sharpe_ratio / sharpe
sortino_ratio / sortino
```

실제 백테스트 결과 키가 다르면 다음 파일의 `KEY_ALIASES`만
조정하세요.

```text
src/stock_platform/performance/backtest_result_adapter.py
```

## API

```text
POST /api/v1/backtest-performance/save
```

요청 예:

```json
{
  "strategy_code": "MA_CROSS_V1",
  "market_code": "KRX",
  "symbol": "005930",
  "period_start_date": "2023-01-01",
  "period_end_date": "2025-12-31",
  "parameter_payload": {
    "short_window": 5,
    "long_window": 20
  },
  "result_payload": {
    "initial_capital": 10000000,
    "final_capital": 11500000,
    "total_trade_count": 30,
    "winning_trade_count": 18,
    "losing_trade_count": 12,
    "gross_profit_amount": 3000000,
    "gross_loss_amount": -1500000,
    "maximum_drawdown_rate": 0.12,
    "sharpe_ratio": 1.3,
    "sortino_ratio": 1.7
  }
}
```

## 기존 백테스트 서비스에 직접 연결

기존 백테스트 실행 메서드가 다음처럼 결과를 반환한다고 가정합니다.

```python
result = backtest_service.run(...)
```

완료 직후 다음을 호출합니다.

```python
from stock_platform.performance.backtest_integration_service import (
    BacktestPerformanceIntegrationService,
)
from stock_platform.performance.backtest_result_adapter import (
    BacktestResultPayloadAdapter,
)

source = BacktestResultPayloadAdapter.from_payload(
    strategy_code="MA_CROSS_V1",
    market_code="KRX",
    symbol="005930",
    period_start_date=start_date,
    period_end_date=end_date,
    parameter_payload=parameters,
    result_payload=result,
)

BacktestPerformanceIntegrationService(
    session
).save_completed_backtest(source)
```

## router.py 추가

```python
from stock_platform.api.v1.backtest_performance import (
    router as backtest_performance_router,
)

api_router.include_router(
    backtest_performance_router
)
```

## 적용 파일

```text
src/stock_platform/performance/backtest_models.py
src/stock_platform/performance/backtest_mapper.py
src/stock_platform/performance/backtest_result_adapter.py
src/stock_platform/performance/backtest_integration_service.py
src/stock_platform/api/v1/backtest_performance.py
tests/test_backtest_performance_mapper.py
tests/test_backtest_result_payload_adapter.py
README_STEP30_3.md
```

신규 테이블과 Alembic 작업은 없습니다.

STEP30-1 테이블을 사용합니다.

```text
trading.strategy_performance_run
trading.strategy_performance_metric
```

## 테스트

```powershell
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_backtest_performance_mapper.py `
    tests\test_backtest_result_payload_adapter.py `
    tests\test_strategy_performance_service.py `
    -q
```

## 검증 순서

```text
1. 기존 백테스트 1건 실행
2. 결과 JSON 확인
3. KEY_ALIASES 조정
4. 성과 저장 API 호출
5. strategy_performance_run 확인
6. strategy_performance_metric 확인
7. strategy-ranking API에서 노출 확인
```

## Git 커밋

```powershell
git add `
    README_STEP30_3.md `
    src\stock_platform\performance\backtest_models.py `
    src\stock_platform\performance\backtest_mapper.py `
    src\stock_platform\performance\backtest_result_adapter.py `
    src\stock_platform\performance\backtest_integration_service.py `
    src\stock_platform\api\v1\backtest_performance.py `
    src\stock_platform\api\router.py `
    tests\test_backtest_performance_mapper.py `
    tests\test_backtest_result_payload_adapter.py

git commit -m "feat(performance): persist backtest results automatically"
```

다음 단계는 STEP30-4 Walk Forward Validation 결과 자동 저장과
윈도우별 안정성 분석입니다.
