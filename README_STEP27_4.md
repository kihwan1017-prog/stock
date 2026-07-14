# STEP27-4 주문 안전장치 및 실거래 전환 잠금

실시간 신호를 주문으로 바꾸기 전에 위험조건을 검사합니다.

## 추가 안전장치

```text
최대 주문금액
일일 최대 손실
최대 보유 종목 수
동일 신호 중복 주문 차단
종목별 주문 쿨다운
분당 최대 주문 횟수
KRX 거래시간 제한
LIVE 모드 전환 잠금
LIVE 잠금 해제 토큰
```

## 기본값

```text
최대 주문금액: 100,000원
일일 최대 손실: 300,000원
최대 보유 종목: 5개
중복 차단: 30초
종목 쿨다운: 60초
분당 최대 주문: 10회
KRX 거래시간: 09:00~15:20
LIVE 거래: 비활성화
```

설정 위치:

```text
src/stock_platform/realtime/runtime.py
```

## 적용 파일

```text
src/stock_platform/realtime/safety_models.py
src/stock_platform/realtime/safety_guard.py
src/stock_platform/realtime/safe_order_executor.py
src/stock_platform/realtime/execution_runner.py
src/stock_platform/realtime/runtime.py
src/stock_platform/api/v1/realtime_safety.py
tests/test_realtime_order_safety_guard.py
README_STEP27_4.md
```

신규 테이블은 없어 Alembic 작업은 필요 없습니다.

## router.py 추가

```python
from stock_platform.api.v1.realtime_safety import (
    router as realtime_safety_router,
)
```

```python
api_router.include_router(
    realtime_safety_router
)
```

## 안전 상태 API

```text
GET /api/v1/realtime-safety/status
```

손익 반영:

```text
POST /api/v1/realtime-safety/realized-profit-loss
```

```json
{
  "realized_profit_loss": -50000
}
```

일일 초기화:

```text
POST /api/v1/realtime-safety/reset-daily
```

운영에서는 이 초기화를 매일 장 시작 전에 스케줄러에서 호출합니다.

## LIVE 모드 주의

현재 프로젝트에서는 실제 브로커 주문 연결이 아직 없으므로
`RealtimeExecutionMode.LIVE`를 사용하면 안 됩니다.

기본 설정은 반드시 유지하세요.

```python
mode=RealtimeExecutionMode.PAPER
```

실거래 잠금도 기본적으로 비활성화되어 있습니다.

```python
live_trading_enabled=False
live_unlock_token=""
```

실제 주문 어댑터를 구현하기 전까지 이 값을 변경하지 마세요.

## main.py 종료 순서

기존과 동일합니다.

```python
yield

await realtime_execution_runner.stop()
await realtime_strategy_runner.stop()
await realtime_manager.stop_all()
```

## 테스트

```powershell
cd D:\Projects\stock-platform
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_realtime_order_safety_guard.py `
    tests\test_realtime_paper_order_executor.py `
    -q
```

## Git 커밋

```powershell
git add `
    README_STEP27_4.md `
    src\stock_platform\realtime\safety_models.py `
    src\stock_platform\realtime\safety_guard.py `
    src\stock_platform\realtime\safe_order_executor.py `
    src\stock_platform\realtime\execution_runner.py `
    src\stock_platform\realtime\runtime.py `
    src\stock_platform\api\v1\realtime_safety.py `
    src\stock_platform\api\router.py `
    tests\test_realtime_order_safety_guard.py

git commit -m "feat(realtime): add order safety guard"
```

다음 단계는 STEP27-5 장전·장중·장마감 자동매매 스케줄러입니다.
