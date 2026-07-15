# STEP30-2 전략 성과 집계와 순위 산정

STEP30-1에 저장된 완료 성과를 조회하여 전략별 수익률·승률·MDD
요약과 가중 점수 기반 순위를 계산합니다.

## 순위 점수

각 지표를 조회 대상 내에서 0~1로 정규화하고 가중합합니다.

```text
총수익률      30%
Sharpe Ratio  20%
Sortino Ratio 10%
승률          15%
Profit Factor 10%
MDD           15%
```

MDD는 낮을수록 높은 점수를 받습니다.

기본 가중치 파일:

```text
src/stock_platform/performance/ranking_models.py
```

## 주의

전략 순위는 조회된 비교 그룹 안에서 계산되는 상대평가입니다.

예를 들어 다음 조건에 따라 결과가 달라질 수 있습니다.

```text
BACKTEST만 비교
WALK_FORWARD만 비교
KRX만 비교
특정 종목만 비교
최소 거래 수 조건
```

거래 수가 너무 적은 전략이 상위에 오르는 것을 막기 위해
`minimum_trade_count`를 사용합니다.

## API

전략 순위:

```text
GET /api/v1/strategy-ranking
```

예:

```text
GET /api/v1/strategy-ranking?run_type=BACKTEST&market_code=KRX&minimum_trade_count=20&limit=20
```

지원 조건:

```text
run_type
market_code
symbol
minimum_trade_count
limit
```

성과 요약:

```text
GET /api/v1/strategy-ranking/summary
```

예:

```text
GET /api/v1/strategy-ranking/summary?strategy_code=MA_CROSS_V1&run_type=BACKTEST
```

요약 항목:

```text
실행 수
평균 수익률
평균 승률
평균 MDD
평균 Sharpe Ratio
총 순이익
총 거래 수
```

## router.py 추가

```python
from stock_platform.api.v1.strategy_ranking import (
    router as strategy_ranking_router,
)

api_router.include_router(
    strategy_ranking_router
)
```

## 적용 파일

```text
src/stock_platform/performance/ranking_models.py
src/stock_platform/performance/ranking_service.py
src/stock_platform/performance/summary_service.py
src/stock_platform/api/v1/strategy_ranking.py
tests/test_strategy_ranking_service.py
tests/test_strategy_ranking_weights.py
README_STEP30_2.md
```

신규 테이블과 Alembic 작업은 없습니다.

STEP30-1의 다음 테이블을 사용합니다.

```text
trading.strategy_performance_run
trading.strategy_performance_metric
```

## 테스트

```powershell
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_strategy_ranking_service.py `
    tests\test_strategy_ranking_weights.py `
    -q
```

## 검증 순서

```text
1. STEP30-1 마이그레이션 적용
2. 성과 Run 생성
3. 성과 Metric 완료 저장
4. 여러 전략 데이터 입력
5. Ranking API 조회
6. 최소 거래 수 필터 검증
7. 종목·마켓 필터 검증
```

## Git 커밋

```powershell
git add `
    README_STEP30_2.md `
    src\stock_platform\performance\ranking_models.py `
    src\stock_platform\performance\ranking_service.py `
    src\stock_platform\performance\summary_service.py `
    src\stock_platform\api\v1\strategy_ranking.py `
    src\stock_platform\api\router.py `
    tests\test_strategy_ranking_service.py `
    tests\test_strategy_ranking_weights.py

git commit -m "feat(performance): add strategy ranking and summary"
```

다음 단계는 STEP30-3 기존 백테스트 결과를 전략 성과 테이블에
자동 저장하는 연동 작업입니다.
