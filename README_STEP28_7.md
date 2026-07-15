# STEP28-7 제한된 실거래 전환 절차

이 단계는 실거래를 자동으로 켜지 않습니다.

환경변수 검사, Paper 검증 확인, 위험한도 확인, 별도 승인 문구,
DB 승인 기록까지 모두 충족해야 실거래 전환 승인이 활성화됩니다.

## 신규 테이블

```text
operation.live_trading_transition
```

## Alembic 등록

`database/alembic/env.py`:

```python
from stock_platform.broker import live_transition_entities as live_transition_entities  # noqa: F401
```

## 마이그레이션

```powershell
alembic revision --autogenerate `
    -m "create live trading transition table"

alembic upgrade head --sql
alembic upgrade head
```

예상하지 않은 삭제 작업이 있으면 적용하지 마세요.

## 초기 실거래 제한

첫 실거래 검증에서는 코드상 다음 상한을 적용합니다.

```text
주문 1건 최대금액: 100,000원
일일 최대손실: 300,000원
```

더 낮게 시작하는 것을 권장합니다.

```json
{
  "max_order_amount": 10000,
  "max_daily_loss": 50000,
  "paper_validation_approved": true
}
```

## 전환 검사

```text
POST /api/v1/broker/live-transition/validate
```

검사 항목:

```text
KIWOOM_USE_MOCK=false
KIWOOM_LIVE_ORDER_ENABLED=true
계좌번호 설정
App Key/Secret 설정
주문체결 WebSocket 설정
자동 전략·주문 시작 비활성화
Paper 검증 승인
최대 주문금액
일일 최대손실
```

## 전환 요청

```text
POST /api/v1/broker/live-transition/request
```

```json
{
  "requested_by": "operator",
  "max_order_amount": 10000,
  "max_daily_loss": 50000,
  "paper_validation_approved": true
}
```

## 수동 승인

```text
POST /api/v1/broker/live-transition/{transition_id}/approve
```

승인 문구는 정확히 다음과 같습니다.

```text
ENABLE KIWOOM LIVE TRADING
```

```json
{
  "approved_by": "operator",
  "approval_phrase": "ENABLE KIWOOM LIVE TRADING"
}
```

승인 문구 원문은 저장하지 않고 SHA-256 해시만 저장합니다.

## 즉시 비활성화

```text
POST /api/v1/broker/live-transition/{transition_id}/disable
```

```json
{
  "reason": "manual emergency stop"
}
```

## 활성 승인 확인

```text
GET /api/v1/broker/live-transition/active
```

## router.py

```python
from stock_platform.api.v1.live_trading_transition import (
    router as live_trading_transition_router,
)

api_router.include_router(
    live_trading_transition_router
)
```

## 반드시 유지할 초기 운영 원칙

실거래 승인을 만들더라도 다음은 자동으로 바뀌지 않습니다.

```text
Broker runtime의 Adapter
실시간 주문 실행기의 mode
자동 복구의 전략·주문 자동 시작
```

따라서 실거래 전환은 별도 코드 변경과 재시작이 필요합니다.

초기 실거래에서 유지할 설정:

```dotenv
KIWOOM_RECOVERY_START_TRADING=false
```

운영 순서:

```text
1. 서버 시작
2. 계좌 동기화
3. 미체결 동기화
4. 주문체결 WebSocket 확인
5. 수동으로 1주 또는 최소수량 주문
6. 주문 접수 확인
7. 체결 이벤트 확인
8. 계좌·보유종목 재동기화
9. 즉시 실거래 승인 비활성화
10. 로그와 DB 검증
```

## 테스트

```powershell
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_live_trading_transition_service.py `
    -q
```

## Git 커밋

```powershell
git add `
    README_STEP28_7.md `
    database\alembic\env.py `
    database\alembic\versions `
    src\stock_platform\broker\live_transition_models.py `
    src\stock_platform\broker\live_transition_entities.py `
    src\stock_platform\broker\live_transition_service.py `
    src\stock_platform\broker\live_transition_guard.py `
    src\stock_platform\api\v1\live_trading_transition.py `
    src\stock_platform\api\router.py `
    tests\test_live_trading_transition_service.py

git commit -m "feat(broker): add controlled live trading transition"
```

STEP28 브로커 및 계좌 연동 기반은 여기까지입니다.

다음 단계는 STEP29 실시간 위험 모니터링과 긴급정지입니다.
