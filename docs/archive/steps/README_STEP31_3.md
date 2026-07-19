# STEP31-3 전략 교체 전 Dry Run·상태 이전·Rollback

ACTIVE 전략을 실시간 Runtime에 반영하기 전에 Dry Run을 수행하고,
기존 전략 상태를 새 전략에 이전합니다. 교체 중 오류가 발생하면
이전 Runtime을 즉시 복원합니다.

## 처리 흐름

```text
대상 ACTIVE 배치 조회
  ↓
새 전략 인스턴스 생성
  ↓
Dry Run
  ↓
기존 전략 상태 export
  ↓
새 전략 상태 import
  ↓
Runtime 원자적 교체
  ↓
실패 시 이전 Runtime Rollback
```

## 신규 테이블

```text
trading.strategy_runtime_switch
```

저장 항목:

```text
이전 배치 ID
대상 배치 ID
Dry Run 결과
이전 전략 상태
대상 전략 상태
상태 코드
오류 메시지
요청자
완료 시각
```

## 상태

```text
DRY_RUN_PASSED
DRY_RUN_FAILED
SWITCHED
ROLLED_BACK
FAILED
```

## 전략 선택 인터페이스

상태 이전을 지원하는 전략은 다음 메서드를 구현합니다.

```python
def export_state(self) -> dict:
    return {
        "last_signal": self.last_signal,
        "position": self.position,
    }

def import_state(self, state: dict) -> None:
    self.last_signal = state.get("last_signal")
    self.position = state.get("position")
```

미구현 전략은 빈 상태로 시작합니다.

선택적으로 다음 메서드를 구현할 수 있습니다.

```python
def validate_configuration(self) -> None:
    ...

def warmup(self, context: dict) -> None:
    ...
```

## Alembic 등록

`database/alembic/env.py`:

```python
from stock_platform.strategy_deployment import switch_entities as strategy_switch_entities  # noqa: F401
```

## 마이그레이션

```powershell
alembic revision --autogenerate `
    -m "create strategy runtime switch table"

alembic upgrade head --sql
alembic upgrade head
```

예상하지 않은 삭제 작업이 있으면 적용하지 마세요.

## API

```text
POST /api/v1/strategy-runtime-switch
```

요청 예:

```json
{
  "target_deployment_id": 12,
  "requested_by": "operator",
  "sample_context": {
    "price": 72000,
    "volume": 100000
  }
}
```

## router.py 추가

```python
from stock_platform.api.v1.strategy_runtime_switch import (
    router as strategy_runtime_switch_router,
)

api_router.include_router(
    strategy_runtime_switch_router
)
```

## 적용 파일

```text
src/stock_platform/strategy_deployment/switch_models.py
src/stock_platform/strategy_deployment/switch_entities.py
src/stock_platform/strategy_deployment/state_transfer.py
src/stock_platform/strategy_deployment/dry_run.py
src/stock_platform/strategy_deployment/switch_repository.py
src/stock_platform/strategy_deployment/switch_service.py
src/stock_platform/api/v1/strategy_runtime_switch.py
tests/test_strategy_dry_run.py
tests/test_strategy_state_transfer.py
README_STEP31_3.md
```

## 테스트

```powershell
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_strategy_dry_run.py `
    tests\test_strategy_state_transfer.py `
    tests\test_dynamic_strategy_runtime_manager.py `
    -q
```

## Git 커밋

```powershell
git add `
    README_STEP31_3.md `
    database\alembic\env.py `
    database\alembic\versions `
    src\stock_platform\strategy_deployment\switch_models.py `
    src\stock_platform\strategy_deployment\switch_entities.py `
    src\stock_platform\strategy_deployment\state_transfer.py `
    src\stock_platform\strategy_deployment\dry_run.py `
    src\stock_platform\strategy_deployment\switch_repository.py `
    src\stock_platform\strategy_deployment\switch_service.py `
    src\stock_platform\api\v1\strategy_runtime_switch.py `
    src\stock_platform\api\router.py `
    tests\test_strategy_dry_run.py `
    tests\test_strategy_state_transfer.py

git commit -m "feat(strategy): add safe runtime switch and rollback"
```

다음 단계는 STEP31-4 전략 자동 배치 승인정책과 스케줄러 연결입니다.
