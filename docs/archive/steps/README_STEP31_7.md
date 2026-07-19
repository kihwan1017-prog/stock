# STEP31-7 전략 운영 통합 대시보드

전략 선택 이후의 승인, 배치, Runtime 교체, Rollback, PAPER 성과
점검 상태를 하나의 API로 통합 조회합니다.

## API

```text
GET /api/v1/dashboard/strategy-operations
```

예:

```text
GET /api/v1/dashboard/strategy-operations?market_code=KRX&symbol=005930&limit=20
```

## 응답 항목

```text
active_deployment
runtime
latest_approval
latest_pipeline
latest_performance
recent_deployments
recent_approvals
recent_switches
recent_pipeline_runs
recent_performance_checks
```

## Active Deployment

```text
배치 ID
전략 코드
성과 Run ID
시장·종목
PAPER/LIVE 모드
ACTIVE/STOPPED/REPLACED 상태
전략 파라미터
활성·중지 시각
교체 배치 ID
오류 메시지
```

## Runtime

```text
전략 로드 여부
현재 배치 ID
현재 전략 코드
등록된 Strategy Factory 목록
최근 Runtime 오류
```

## Approval

```text
선택 Run ID
성과 Run ID
결정 상태
자동 승인 여부
승인·거부 사유
배치 ID
요청자·결정자
```

## Pipeline

```text
전략 선택
승인
PAPER 배치
Runtime Switch
Rollback
실패 상태
```

## Performance

```text
PAPER 거래 수
총수익률
MDD
승률
Profit Factor
연속 손실
HEALTHY/WARNING/STOPPED 상태
```

## 적용 파일

```text
src/stock_platform/strategy_deployment/dashboard_models.py
src/stock_platform/strategy_deployment/dashboard_service.py
src/stock_platform/api/v1/strategy_operations_dashboard.py
tests/test_strategy_operations_dashboard_service.py
README_STEP31_7.md
```

신규 테이블과 Alembic 작업은 없습니다.

STEP31에서 생성한 기존 테이블을 조회합니다.

```text
trading.strategy_deployment
trading.strategy_approval_run
trading.strategy_runtime_switch
trading.strategy_deployment_pipeline
trading.strategy_deployment_performance
```

## router.py 추가

```python
from stock_platform.api.v1.strategy_operations_dashboard import (
    router as strategy_operations_dashboard_router,
)

api_router.include_router(
    strategy_operations_dashboard_router
)
```

## 테스트

```powershell
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_strategy_operations_dashboard_service.py `
    tests\test_strategy_deployment_pipeline_runtime.py `
    tests\test_deployment_performance_monitor_service.py `
    -q
```

## Swagger 확인

```powershell
uvicorn stock_platform.api.main:app `
    --app-dir src `
    --reload
```

```text
http://127.0.0.1:8000/docs
```

## Git 커밋

```powershell
git add `
    README_STEP31_7.md `
    src\stock_platform\strategy_deployment\dashboard_models.py `
    src\stock_platform\strategy_deployment\dashboard_service.py `
    src\stock_platform\api\v1\strategy_operations_dashboard.py `
    src\stock_platform\api\router.py `
    tests\test_strategy_operations_dashboard_service.py

git commit -m "feat(strategy): add strategy operations dashboard"
```

STEP31 모의투자 전략 배치와 안전한 전략 교체 기반은 여기까지입니다.

다음 단계는 STEP32 주문 생명주기 통합과 정정·취소·재시도 관리입니다.
