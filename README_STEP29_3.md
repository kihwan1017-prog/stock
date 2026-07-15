# STEP29-3 영구 긴급정지 Kill Switch

DB에 저장되는 GLOBAL Kill Switch를 추가합니다.

서버를 재시작해도 긴급정지 상태가 유지됩니다.

## 주문 처리 순서

```text
Persistent Kill Switch
  ↓
Risk Engine
  ↓
Safety Guard
  ↓
Execution
```

Kill Switch가 활성화되면:

```text
BUY  → 차단
SELL → 위험 축소 목적으로 허용
```

차단 사유:

```text
GLOBAL_KILL_SWITCH_ACTIVE
```

## 신규 테이블

```text
operation.kill_switch
operation.kill_switch_history
```

## Alembic 등록

`database/alembic/env.py`:

```python
from stock_platform.risk_engine import kill_switch_entities as kill_switch_entities  # noqa: F401
```

## 마이그레이션

```powershell
alembic revision --autogenerate `
    -m "create persistent kill switch tables"

alembic upgrade head --sql
alembic upgrade head
```

예상하지 않은 삭제 작업이 있으면 적용하지 마세요.

## API

현재 상태:

```text
GET /api/v1/risk/kill-switch
```

긴급정지 활성화:

```text
POST /api/v1/risk/kill-switch/activate
```

```json
{
  "actor": "operator",
  "reason": "unexpected order activity"
}
```

긴급정지 해제:

```text
POST /api/v1/risk/kill-switch/deactivate
```

```json
{
  "actor": "operator",
  "reason": "issue resolved"
}
```

## router.py 추가

```python
from stock_platform.api.v1.kill_switch import (
    router as kill_switch_router,
)

api_router.include_router(
    kill_switch_router
)
```

## 적용 파일

```text
src/stock_platform/risk_engine/kill_switch_models.py
src/stock_platform/risk_engine/kill_switch_entities.py
src/stock_platform/risk_engine/kill_switch_service.py
src/stock_platform/risk_engine/kill_switch_guard.py
src/stock_platform/realtime/risk_integrated_order_executor.py
src/stock_platform/api/v1/kill_switch.py
tests/test_kill_switch_service.py
tests/test_persistent_kill_switch_guard.py
```

`risk_integrated_order_executor.py`는 STEP29-2 파일을 교체합니다.

## 중요

Kill Switch 해제는 자동으로 하지 마세요.

운영 중 이상이 발생하면:

```text
1. Kill Switch 활성화
2. 주문 실행기 중지
3. 전략 실행기 중지
4. 미체결 주문 확인
5. 필요 시 수동 취소
6. 계좌·포지션 동기화
7. 원인 확인
8. 운영자 수동 해제
```

## 테스트

```powershell
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_kill_switch_service.py `
    tests\test_persistent_kill_switch_guard.py `
    tests\test_risk_integrated_order_executor.py `
    -q
```

## Git 커밋

```powershell
git add `
    README_STEP29_3.md `
    database\alembic\env.py `
    database\alembic\versions `
    src\stock_platform\risk_engine\kill_switch_models.py `
    src\stock_platform\risk_engine\kill_switch_entities.py `
    src\stock_platform\risk_engine\kill_switch_service.py `
    src\stock_platform\risk_engine\kill_switch_guard.py `
    src\stock_platform\realtime\risk_integrated_order_executor.py `
    src\stock_platform\api\v1\kill_switch.py `
    src\stock_platform\api\router.py `
    tests\test_kill_switch_service.py `
    tests\test_persistent_kill_switch_guard.py

git commit -m "feat(risk): add persistent global kill switch"
```

다음 단계는 STEP29-4 일일 손실 자동 감지와 Kill Switch 자동 활성화입니다.
