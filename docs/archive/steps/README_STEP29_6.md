# STEP29-6 Telegram·Slack 위험 알림

위험 이벤트 알림을 애플리케이션 로그, Telegram Bot API,
Slack Incoming Webhook으로 동시에 전송합니다.

하나의 채널이 실패해도 나머지 채널은 계속 전송합니다.

## Telegram 설정

```dotenv
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=BotFather에서_발급한_토큰
TELEGRAM_CHAT_ID=알림을_받을_채팅_ID
```

Telegram Bot API의 `sendMessage` 메서드를 사용합니다.

```text
POST https://api.telegram.org/bot{TOKEN}/sendMessage
```

Bot Token은 Git에 커밋하지 마세요.

## Slack 설정

```dotenv
SLACK_ENABLED=true
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
```

Slack Incoming Webhook은 발급된 고유 URL에 JSON 메시지를
HTTP POST하는 방식입니다.

Webhook URL은 비밀번호와 동일하게 취급하고 Git에 커밋하지
마세요.

## 알림 전송 구조

```text
Risk Event
  ↓
CompositeNotificationSender
  ├─ Application Log
  ├─ Telegram
  └─ Slack
```

## 기존 Daily Loss Monitor 연결

STEP29-4의 다음 파일을 교체합니다.

```text
src/stock_platform/risk_engine/alert.py
```

기존 `LoggingRiskAlertNotifier` 이름은 유지되지만 내부적으로
로그·Telegram·Slack 복합 알림을 사용합니다.

## API

테스트 알림:

```text
POST /api/v1/notification/test
```

```json
{
  "title": "자동매매 알림 테스트",
  "message": "Telegram과 Slack 연결을 확인합니다.",
  "detail": {
    "broker": "KIWOOM",
    "environment": "MOCK"
  }
}
```

상태 조회:

```text
GET /api/v1/notification/status
```

상태 항목:

```text
enabled
configured
sent_count
failed_count
last_sent_at
last_error
```

## router.py

```python
from stock_platform.api.v1.notifications import (
    router as notifications_router,
)

api_router.include_router(
    notifications_router
)
```

## 적용 파일

```text
src/stock_platform/notification/__init__.py
src/stock_platform/notification/models.py
src/stock_platform/notification/base.py
src/stock_platform/notification/logging_sender.py
src/stock_platform/notification/telegram_sender.py
src/stock_platform/notification/slack_sender.py
src/stock_platform/notification/composite.py
src/stock_platform/notification/runtime.py
src/stock_platform/risk_engine/alert.py
src/stock_platform/api/v1/notifications.py
tests/test_notification_senders.py
tests/test_composite_notification_sender.py
```

신규 테이블과 Alembic 작업은 없습니다.

## 테스트

```powershell
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_notification_senders.py `
    tests\test_composite_notification_sender.py `
    tests\test_daily_loss_monitor.py `
    -q
```

## 실제 전송 테스트

서버를 재시작한 후:

```text
POST /api/v1/notification/test
```

Telegram과 Slack 중 사용하지 않는 채널은 `ENABLED=false`로
설정하세요.

## Git 커밋

```powershell
git add `
    README_STEP29_6.md `
    src\stock_platform\notification `
    src\stock_platform\risk_engine\alert.py `
    src\stock_platform\api\v1\notifications.py `
    src\stock_platform\api\router.py `
    tests\test_notification_senders.py `
    tests\test_composite_notification_sender.py

git commit -m "feat(notification): add Telegram and Slack risk alerts"
```

다음 단계는 STEP29-7 위험관리 통합 운영 대시보드입니다.
