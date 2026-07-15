# STEP31-1 모의투자 전략 배치와 안전한 교체

LLM 전략 선택 또는 운영자 선택 결과를 모의투자 전략 배치로
등록하고, 동일 시장·종목의 기존 활성 전략을 안전하게 교체합니다.

## 지원 범위

```text
PAPER 모드만 지원
LIVE 모드는 차단
```

## 신규 테이블

```text
trading.strategy_deployment
trading.strategy_deployment_history
```

## 배치 흐름

```text
성과 Run 검증
  ↓
COMPLETED 여부 확인
  ↓
WALK_FORWARD 또는 PAPER 여부 확인
  ↓
기존 ACTIVE 전략 조회
  ↓
기존 전략 REPLACED 처리
  ↓
신규 전략 ACTIVE 처리
  ↓
이력 저장
```

## Alembic 등록

`database/alembic/env.py`:

```python
from stock_platform.strategy_deployment import entities as strategy_deployment_entities  # noqa: F401
```

## 마이그레이션

```powershell
alembic revision --autogenerate `
    -m "create strategy deployment tables"

alembic upgrade head --sql
alembic upgrade head
```

예상하지 않은 삭제 작업이 있으면 적용하지 마세요.

## API

전략 배치:

```text
POST /api/v1/strategy-deployments
```

```json
{
  "strategy_code": "MA_CROSS_V1",
  "strategy_performance_run_id": 10,
  "market_code": "KRX",
  "symbol": "005930",
  "mode": "PAPER",
  "parameter_payload": {
    "short_window": 5,
    "long_window": 20
  },
  "requested_by": "operator"
}
```

활성 전략 조회:

```text
GET /api/v1/strategy-deployments/active?market_code=KRX&symbol=005930&mode=PAPER
```

전략 중지:

```text
POST /api/v1/strategy-deployments/{deployment_id}/stop
```

## 배치 가능 조건

```text
성과 Run 상태 = COMPLETED
전략 코드 일치
마켓·종목 일치
성과 유형 = WALK_FORWARD 또는 PAPER
모드 = PAPER
```

## router.py 추가

```python
from stock_platform.api.v1.strategy_deployment import (
    router as strategy_deployment_router,
)

api_router.include_router(
    strategy_deployment_router
)
```

## 적용 파일

```text
src/stock_platform/strategy_deployment/models.py
src/stock_platform/strategy_deployment/entities.py
src/stock_platform/strategy_deployment/repository.py
src/stock_platform/strategy_deployment/validation.py
src/stock_platform/strategy_deployment/service.py
src/stock_platform/api/v1/strategy_deployment.py
tests/test_strategy_deployment_service.py
README_STEP31_1.md
```

## 테스트

```powershell
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_strategy_deployment_service.py `
    -q
```

## Git 커밋

```powershell
git add `
    README_STEP31_1.md `
    database\alembic\env.py `
    database\alembic\versions `
    src\stock_platform\strategy_deployment `
    src\stock_platform\api\v1\strategy_deployment.py `
    src\stock_platform\api\router.py `
    tests\test_strategy_deployment_service.py

git commit -m "feat(strategy): add paper strategy deployment"
```

다음 단계는 STEP31-2 배치된 전략을 Realtime Strategy Runner에
동적으로 로드하는 기능입니다.
