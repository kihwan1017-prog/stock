# STEP30-4 Walk Forward 결과 자동 저장·안정성 분석

Walk Forward Validation의 각 테스트 윈도우 결과를 개별 저장하고,
전체 집계 성과와 안정성 점수를 계산합니다.

## 신규 테이블

```text
trading.walk_forward_window_metric
```

STEP30-1의 다음 테이블도 함께 사용합니다.

```text
trading.strategy_performance_run
trading.strategy_performance_metric
```

## 저장 구조

```text
Walk Forward 실행
  ↓
윈도우별 테스트 결과
  ↓
walk_forward_window_metric 저장
  ↓
전체 성과 집계
  ↓
strategy_performance_metric 저장
  ↓
안정성 분석
```

## 윈도우별 저장 항목

```text
윈도우 번호
학습 시작·종료일
테스트 시작·종료일
초기·최종 자본
수익률
MDD
Sharpe Ratio
Sortino Ratio
승률
Profit Factor
거래 수
순이익
전략 파라미터
원본 결과
```

## 안정성 지표

```text
윈도우 수
양수 수익 윈도우 수
음수 수익 윈도우 수
양수 윈도우 비율
평균 수익률
수익률 표준편차
최고 윈도우 수익률
최악 윈도우 수익률
최대 MDD
안정성 점수
```

현재 안정성 점수:

```text
max(
    양수 윈도우 비율
    - 수익률 표준편차
    - 최대 MDD,
    0
)
```

프로젝트 운영 결과에 따라 가중식을 조정할 수 있습니다.

## Alembic 등록

`database/alembic/env.py`:

```python
from stock_platform.performance import walk_forward_entities as walk_forward_entities  # noqa: F401
```

## 마이그레이션

```powershell
alembic revision --autogenerate `
    -m "create walk forward window metric table"

alembic upgrade head --sql
alembic upgrade head
```

예상하지 않은 삭제 작업이 있으면 적용하지 마세요.

## API

Walk Forward 성과 저장:

```text
POST /api/v1/walk-forward-performance/save
```

윈도우 조회:

```text
GET /api/v1/walk-forward-performance/runs/{run_id}/windows
```

## 요청 예

```json
{
  "strategy_code": "MA_CROSS_V1",
  "market_code": "KRX",
  "symbol": "005930",
  "period_start_date": "2023-01-01",
  "period_end_date": "2025-12-31",
  "aggregate_parameter_payload": {
    "train_months": 12,
    "test_months": 3
  },
  "windows": [
    {
      "window_no": 1,
      "train_start_date": "2023-01-01",
      "train_end_date": "2023-12-31",
      "test_start_date": "2024-01-01",
      "test_end_date": "2024-03-31",
      "parameter_payload": {
        "short_window": 5,
        "long_window": 20
      },
      "result_payload": {
        "initial_capital": 10000000,
        "final_capital": 10500000,
        "total_trade_count": 10,
        "winning_trade_count": 6,
        "losing_trade_count": 4,
        "gross_profit_amount": 900000,
        "gross_loss_amount": -400000,
        "maximum_drawdown_rate": 0.05,
        "sharpe_ratio": 1.2
      }
    }
  ]
}
```

## 기존 Walk Forward 서비스에 연결

기존 `WalkForwardValidationService`가 윈도우 결과 목록을 반환한 뒤
다음 서비스를 호출합니다.

```python
WalkForwardPerformanceIntegrationService(
    session
).save(source)
```

윈도우 결과 키가 기존 백테스트 결과와 다르면 STEP30-3의
`BacktestResultPayloadAdapter.KEY_ALIASES`를 조정하세요.

## router.py 추가

```python
from stock_platform.api.v1.walk_forward_performance import (
    router as walk_forward_performance_router,
)

api_router.include_router(
    walk_forward_performance_router
)
```

## 적용 파일

```text
src/stock_platform/performance/walk_forward_models.py
src/stock_platform/performance/walk_forward_entities.py
src/stock_platform/performance/walk_forward_repository.py
src/stock_platform/performance/walk_forward_mapper.py
src/stock_platform/performance/walk_forward_stability.py
src/stock_platform/performance/walk_forward_service.py
src/stock_platform/api/v1/walk_forward_performance.py
tests/test_walk_forward_stability.py
tests/test_walk_forward_performance_mapper.py
README_STEP30_4.md
```

## 테스트

```powershell
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_walk_forward_stability.py `
    tests\test_walk_forward_performance_mapper.py `
    tests\test_walk_forward_validation_service.py `
    -q
```

## Git 커밋

```powershell
git add `
    README_STEP30_4.md `
    database\alembic\env.py `
    database\alembic\versions `
    src\stock_platform\performance\walk_forward_models.py `
    src\stock_platform\performance\walk_forward_entities.py `
    src\stock_platform\performance\walk_forward_repository.py `
    src\stock_platform\performance\walk_forward_mapper.py `
    src\stock_platform\performance\walk_forward_stability.py `
    src\stock_platform\performance\walk_forward_service.py `
    src\stock_platform\api\v1\walk_forward_performance.py `
    src\stock_platform\api\router.py `
    tests\test_walk_forward_stability.py `
    tests\test_walk_forward_performance_mapper.py

git commit -m "feat(performance): persist walk forward window metrics"
```

다음 단계는 STEP30-5 전략 Leaderboard 스냅샷 저장과
기간별 순위 이력 관리입니다.
