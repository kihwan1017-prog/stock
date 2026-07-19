# STEP30-1 전략 성과 저장 구조

백테스트, Walk Forward, 모의투자, 실거래 결과를 동일한 구조로
저장하기 위한 전략 성과 테이블과 API를 추가합니다.

## 지원 실행 유형

```text
BACKTEST
WALK_FORWARD
PAPER
LIVE
```

## 신규 테이블

```text
trading.strategy_performance_run
trading.strategy_performance_metric
```

### strategy_performance_run

```text
전략 코드
실행 유형
마켓
종목
분석 기간
전략 파라미터
파라미터 해시
실행 상태
원본 결과 JSON
오류 메시지
시작·완료 시각
```

### strategy_performance_metric

```text
초기 자본
최종 자본
총수익률
연환산수익률
최대낙폭
변동성
Sharpe Ratio
Sortino Ratio
승률
Profit Factor
총 거래 수
승리 거래 수
손실 거래 수
평균 수익
평균 손실
총 이익
총 손실
순이익
```

## Alembic 등록

`database/alembic/env.py`:

```python
from stock_platform.performance import entities as performance_entities  # noqa: F401
```

## 마이그레이션

```powershell
alembic revision --autogenerate `
    -m "create strategy performance tables"

alembic upgrade head --sql
alembic upgrade head
```

예상하지 않은 삭제 작업이 있으면 적용하지 마세요.

## API

성과 실행 생성:

```text
POST /api/v1/strategy-performance/runs
```

```json
{
  "strategy_code": "MA_CROSS_V1",
  "run_type": "BACKTEST",
  "market_code": "KRX",
  "symbol": "005930",
  "period_start_date": "2023-01-01",
  "period_end_date": "2025-12-31",
  "parameter_payload": {
    "short_window": 5,
    "long_window": 20
  }
}
```

성과 완료:

```text
POST /api/v1/strategy-performance/runs/{run_id}/complete
```

성과 조회:

```text
GET /api/v1/strategy-performance/runs/{run_id}
```

## router.py 추가

```python
from stock_platform.api.v1.strategy_performance import (
    router as strategy_performance_router,
)

api_router.include_router(
    strategy_performance_router
)
```

## 적용 파일

```text
src/stock_platform/performance/__init__.py
src/stock_platform/performance/models.py
src/stock_platform/performance/entities.py
src/stock_platform/performance/repository.py
src/stock_platform/performance/service.py
src/stock_platform/api/v1/strategy_performance.py
tests/test_strategy_performance_service.py
README_STEP30_1.md
```

## 테스트

```powershell
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_strategy_performance_service.py `
    -q
```

## Git 커밋

```powershell
git add `
    README_STEP30_1.md `
    database\alembic\env.py `
    database\alembic\versions `
    src\stock_platform\performance `
    src\stock_platform\api\v1\strategy_performance.py `
    src\stock_platform\api\router.py `
    tests\test_strategy_performance_service.py

git commit -m "feat(performance): add strategy performance storage"
```

다음 단계는 STEP30-2 전략별 수익률·승률·MDD 집계와 순위 산정입니다.
