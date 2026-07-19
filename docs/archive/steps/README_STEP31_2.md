# STEP31-2 배치 전략의 Realtime Strategy Runner 동적 로딩

STEP31-1에서 ACTIVE 상태로 배치된 PAPER 전략을 DB에서 읽어
실시간 전략 인스턴스로 생성하고, 배치 변경 시 메모리 전략을
안전하게 교체합니다.

## 처리 흐름

```text
strategy_deployment ACTIVE
  ↓
StrategyFactoryRegistry
  ↓
전략 클래스 생성
  ↓
DynamicStrategyRuntimeManager
  ↓
Realtime Strategy Runner
```

## 핵심 기능

```text
ACTIVE 배치 조회
strategy_code별 Factory 등록
parameter_payload 기반 전략 생성
배치 ID 변경 감지
메모리 전략 원자적 교체
30초 주기 자동 Reload
수동 Reload API
Runtime 상태 조회
```

## 신규 테이블

없습니다.

STEP31-1의 다음 테이블을 사용합니다.

```text
trading.strategy_deployment
trading.strategy_deployment_history
```

## 전략 Factory 등록

다음 파일을 실제 프로젝트 전략 클래스에 맞게 수정합니다.

```text
src/stock_platform/strategy_deployment/default_registry.py
```

예:

```python
from stock_platform.strategy.ma_cross import (
    MaCrossStrategy,
)
from stock_platform.strategy_deployment.registry import (
    strategy_factory_registry,
)

strategy_factory_registry.replace(
    "MA_CROSS_V1",
    lambda params: MaCrossStrategy(
        short_window=int(
            params["short_window"]
        ),
        long_window=int(
            params["long_window"]
        ),
    ),
)
```

DB의 `strategy_code`와 Registry의 코드가 정확히 같아야 합니다.

## 환경변수

```dotenv
REALTIME_STRATEGY_MARKET_CODE=KRX
REALTIME_STRATEGY_SYMBOL=005930
```

시장 전체 공통 전략이면 종목을 비웁니다.

```dotenv
REALTIME_STRATEGY_SYMBOL=
```

## API

수동 Reload:

```text
POST /api/v1/strategy-runtime/reload
```

예:

```text
POST /api/v1/strategy-runtime/reload?market_code=KRX&symbol=005930&force=true
```

상태:

```text
GET /api/v1/strategy-runtime/status
```

메모리 전략 제거:

```text
POST /api/v1/strategy-runtime/clear
```

## router.py 추가

```python
from stock_platform.api.v1.strategy_runtime import (
    router as strategy_runtime_router,
)

api_router.include_router(
    strategy_runtime_router
)
```

## main.py 시작·종료 연결

```python
from stock_platform.strategy_deployment.runtime_manager import (
    dynamic_strategy_runtime_manager,
)
from stock_platform.strategy_deployment.reload_scheduler import (
    strategy_runtime_reload_scheduler,
)
```

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()

    try:
        await dynamic_strategy_runtime_manager.initialize(
            market_code=os.getenv(
                "REALTIME_STRATEGY_MARKET_CODE",
                "KRX",
            ),
            symbol=(
                os.getenv(
                    "REALTIME_STRATEGY_SYMBOL",
                    "",
                ).strip()
                or None
            ),
        )
    except Exception:
        logger.exception(
            "Initial strategy runtime load failed"
        )

    strategy_runtime_reload_scheduler.start()

    yield

    await strategy_runtime_reload_scheduler.shutdown()
    await dynamic_strategy_runtime_manager.clear()
```

## Realtime Strategy Runner 연결

기존 Runner가 직접 전략 객체를 들고 있다면 다음 Adapter로
교체합니다.

```python
from stock_platform.realtime.dynamic_strategy_adapter import (
    DynamicRealtimeStrategyAdapter,
)

strategy = DynamicRealtimeStrategyAdapter()
```

Runner에서는 기존처럼 호출합니다.

```python
signal = strategy.evaluate(...)
```

Adapter가 현재 ACTIVE 배치 전략을 자동으로 사용합니다.

## 적용 파일

```text
src/stock_platform/strategy_deployment/runtime_models.py
src/stock_platform/strategy_deployment/registry.py
src/stock_platform/strategy_deployment/default_registry.py
src/stock_platform/strategy_deployment/runtime_loader.py
src/stock_platform/strategy_deployment/runtime_manager.py
src/stock_platform/strategy_deployment/reload_scheduler.py
src/stock_platform/realtime/dynamic_strategy_adapter.py
src/stock_platform/api/v1/strategy_runtime.py
tests/test_strategy_factory_registry.py
tests/test_dynamic_strategy_runtime_manager.py
README_STEP31_2.md
```

## 테스트

```powershell
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_strategy_factory_registry.py `
    tests\test_dynamic_strategy_runtime_manager.py `
    tests\test_strategy_deployment_service.py `
    -q
```

## 검증 순서

```text
1. Strategy Factory 등록
2. PAPER 전략 배치 생성
3. ACTIVE 상태 확인
4. 수동 Runtime Reload
5. Runtime status 확인
6. Realtime Strategy Runner 시작
7. 전략 신호 생성 확인
8. 다른 전략 배치
9. 30초 내 자동 교체 확인
```

## Git 커밋

```powershell
git add `
    README_STEP31_2.md `
    src\stock_platform\strategy_deployment\runtime_models.py `
    src\stock_platform\strategy_deployment\registry.py `
    src\stock_platform\strategy_deployment\default_registry.py `
    src\stock_platform\strategy_deployment\runtime_loader.py `
    src\stock_platform\strategy_deployment\runtime_manager.py `
    src\stock_platform\strategy_deployment\reload_scheduler.py `
    src\stock_platform\realtime\dynamic_strategy_adapter.py `
    src\stock_platform\api\v1\strategy_runtime.py `
    src\stock_platform\api\router.py `
    src\stock_platform\api\main.py `
    tests\test_strategy_factory_registry.py `
    tests\test_dynamic_strategy_runtime_manager.py

git commit -m "feat(strategy): dynamically load active paper strategy"
```

다음 단계는 STEP31-3 전략 교체 전 Dry Run·상태 이전·Rollback입니다.
