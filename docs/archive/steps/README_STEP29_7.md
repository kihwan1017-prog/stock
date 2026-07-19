# STEP29-7 위험관리 통합 운영 대시보드

Kill Switch, 일일 손실, 브로커 WebSocket, 알림 채널,
Risk Policy, 주문 실행기, 보유상태, 최근 Risk Event를 하나의
API에서 조회합니다.

## API

```text
GET /api/v1/dashboard/risk
```

요청 예:

```text
GET /api/v1/dashboard/risk?account_number=1234567890&recent_limit=50
```

## 조회 항목

```text
kill_switch
daily_loss
broker
notification
risk_engine
execution
position
recent_events
```

### Kill Switch

```text
ACTIVE / INACTIVE
활성화 사유
활성화 사용자
활성화 시각
해제 사용자
해제 시각
```

### Daily Loss

```text
실현손익
미실현손익
합산손익
현재 손실
손실 한도
손실 진행률
최근 검사 시각
```

### Broker

```text
키움 주문체결 WebSocket 상태
수신 메시지 수
변환 이벤트 수
최근 오류
계좌 스냅샷 존재 여부
```

### Notification

```text
Log
Telegram
Slack
활성화 여부
설정 여부
성공 횟수
실패 횟수
최근 성공 시각
최근 오류
```

### Risk Engine

```text
최대 주문금액
최대 주문수량
최대 보유종목
최대 투자비율
일일 최대손실
WARNING/CRITICAL 이벤트 수
```

### Execution

```text
주문 실행기 상태
실행 주문 수
차단 주문 수
실패 주문 수
전략 실행기 상태
처리 신호 수
발행 신호 수
```

### Position

```text
사용 가능 현금
총 투자금
총 자산
투자비율
보유종목 수
```

### Recent Events

```text
AUTO_KILL_SWITCH
POSITION_LIMIT
ORDER_BLOCKED
BROKER_DISCONNECTED
기타 Risk Event
```

## 적용 파일

```text
src/stock_platform/risk_engine/dashboard_models.py
src/stock_platform/risk_engine/dashboard_service.py
src/stock_platform/api/v1/risk_dashboard.py
tests/test_risk_dashboard_service.py
README_STEP29_7.md
```

신규 테이블과 Alembic 작업은 없습니다.

## router.py 추가

```python
from stock_platform.api.v1.risk_dashboard import (
    router as risk_dashboard_router,
)

api_router.include_router(
    risk_dashboard_router
)
```

## 테스트

```powershell
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_risk_dashboard_service.py `
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
    README_STEP29_7.md `
    src\stock_platform\risk_engine\dashboard_models.py `
    src\stock_platform\risk_engine\dashboard_service.py `
    src\stock_platform\api\v1\risk_dashboard.py `
    src\stock_platform\api\router.py `
    tests\test_risk_dashboard_service.py

git commit -m "feat(risk): add integrated risk dashboard"
```

STEP29 위험관리 기반 구축은 여기까지입니다.

다음 단계는 STEP30 전략 성과 저장과 전략 순위 산정입니다.
