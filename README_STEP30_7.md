# STEP30-7 전략 성과·순위·LLM 선택 통합 대시보드

STEP30에서 구축한 전략 성과, Ranking, Leaderboard 이력,
Walk Forward 안정성, LLM 전략 선택 결과를 하나의 API에서 조회합니다.

## API

```text
GET /api/v1/dashboard/strategy-performance
```

예:

```text
GET /api/v1/dashboard/strategy-performance?run_type=WALK_FORWARD&market_code=KRX&minimum_trade_count=20
```

응답 항목:

```text
summary
ranking
latest_selection
leaderboard_history
recent_runs
walk_forward_stability
```

## router.py

```python
from stock_platform.api.v1.strategy_performance_dashboard import (
    router as strategy_performance_dashboard_router,
)

api_router.include_router(
    strategy_performance_dashboard_router
)
```

## 적용 파일

```text
src/stock_platform/performance/dashboard_models.py
src/stock_platform/performance/dashboard_service.py
src/stock_platform/api/v1/strategy_performance_dashboard.py
tests/test_strategy_performance_dashboard_service.py
README_STEP30_7.md
```

신규 테이블과 Alembic 작업은 없습니다.

## 테스트

```powershell
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_strategy_performance_dashboard_service.py `
    tests\test_strategy_ranking_service.py `
    tests\test_walk_forward_stability.py `
    tests\test_strategy_selector_service.py `
    -q
```

## Git 커밋

```powershell
git add `
    README_STEP30_7.md `
    src\stock_platform\performance\dashboard_models.py `
    src\stock_platform\performance\dashboard_service.py `
    src\stock_platform\api\v1\strategy_performance_dashboard.py `
    src\stock_platform\api\router.py `
    tests\test_strategy_performance_dashboard_service.py

git commit -m "feat(performance): add strategy performance dashboard"
```

STEP30 전략 성과·순위·LLM 선택 기반은 여기까지입니다.

다음 단계는 STEP31 모의투자 전략 자동 배치와 안전한 전략 교체입니다.
