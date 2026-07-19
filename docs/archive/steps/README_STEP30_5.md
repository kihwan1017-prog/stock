# STEP30-5 전략 Leaderboard 스냅샷과 순위 이력

STEP30-2의 상대평가 순위를 특정 날짜 기준으로 저장하고,
전략별 순위 변화를 조회합니다.

## 신규 테이블

```text
trading.strategy_leaderboard_snapshot
trading.strategy_leaderboard_entry
```

### Snapshot

```text
기준일
실행 유형
마켓
종목
최소 거래 수
전략 수
전체 Ranking JSON
생성 시각
```

### Entry

```text
순위
전략 코드
전략 성과 Run ID
점수
수익률
MDD
Sharpe Ratio
Sortino Ratio
승률
Profit Factor
거래 수
```

## Alembic 등록

`database/alembic/env.py`:

```python
from stock_platform.performance import leaderboard_entities as leaderboard_entities  # noqa: F401
```

## 마이그레이션

```powershell
alembic revision --autogenerate `
    -m "create strategy leaderboard tables"

alembic upgrade head --sql
alembic upgrade head
```

예상하지 않은 삭제 작업이 있으면 적용하지 마세요.

## API

스냅샷 생성:

```text
POST /api/v1/strategy-leaderboard/snapshots
```

```json
{
  "snapshot_date": "2026-07-16",
  "run_type": "WALK_FORWARD",
  "market_code": "KRX",
  "symbol": null,
  "minimum_trade_count": 20,
  "limit": 50
}
```

스냅샷 조회:

```text
GET /api/v1/strategy-leaderboard/snapshots/{snapshot_id}
```

기간별 스냅샷 이력:

```text
GET /api/v1/strategy-leaderboard/history
```

전략별 순위 이력:

```text
GET /api/v1/strategy-leaderboard/strategies/{strategy_code}/history
```

## 중복 방지

다음 조건이 같은 스냅샷은 하루에 한 번만 저장됩니다.

```text
snapshot_date
run_type
market_code
symbol
minimum_trade_count
```

중복 생성 시 `400 Bad Request`가 반환됩니다.

## Scheduler 연결 예

장 마감 후 매일 1회 저장하려면 기존 스케줄러의
AFTER_MARKET 단계에서 다음 서비스를 호출합니다.

```python
StrategyLeaderboardService(
    session
).generate_snapshot(
    snapshot_date=date.today(),
    run_type="WALK_FORWARD",
    market_code="KRX",
    symbol=None,
    minimum_trade_count=20,
    limit=50,
)
```

초기에는 API 수동 실행으로 검증한 뒤 스케줄러에 연결하세요.

## router.py 추가

```python
from stock_platform.api.v1.strategy_leaderboard import (
    router as strategy_leaderboard_router,
)

api_router.include_router(
    strategy_leaderboard_router
)
```

## 적용 파일

```text
src/stock_platform/performance/leaderboard_entities.py
src/stock_platform/performance/leaderboard_repository.py
src/stock_platform/performance/leaderboard_service.py
src/stock_platform/performance/leaderboard_trend_service.py
src/stock_platform/api/v1/strategy_leaderboard.py
tests/test_strategy_leaderboard_service.py
README_STEP30_5.md
```

## 테스트

```powershell
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_strategy_leaderboard_service.py `
    tests\test_strategy_ranking_service.py `
    -q
```

## Git 커밋

```powershell
git add `
    README_STEP30_5.md `
    database\alembic\env.py `
    database\alembic\versions `
    src\stock_platform\performance\leaderboard_entities.py `
    src\stock_platform\performance\leaderboard_repository.py `
    src\stock_platform\performance\leaderboard_service.py `
    src\stock_platform\performance\leaderboard_trend_service.py `
    src\stock_platform\api\v1\strategy_leaderboard.py `
    src\stock_platform\api\router.py `
    tests\test_strategy_leaderboard_service.py

git commit -m "feat(performance): add strategy leaderboard history"
```

다음 단계는 STEP30-6 LLM 기반 전략 선택기입니다.
