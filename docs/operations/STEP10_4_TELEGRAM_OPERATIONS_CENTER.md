# STEP 10-4 — Telegram Operations Center (Remote Operations Center)

## Architecture

```
Telegram Client
  → Polling (telegram_ops_scheduler) 또는 Webhook (/api/v1/telegram/ops)
  → TelegramCommandHandler (TelegramCommandRouter)
       → Read-only: TelegramOpsStatusService
            → OperationsCenterDashboardService (STEP 10-3 Summary 재사용)
       → Dangerous: TelegramApprovalService (60s TTL)
            → YES /confirm → ACTION_EXECUTORS → Admin Service API
            → AuditLogService (TELEGRAM_*)
  → TelegramNotificationService (notification_publisher / Outbox 경로)
       → NotificationService → TelegramSender
```

**원칙:** 자동 주문·LIVE ON·ARM ON·Scheduler 자동 Start·Runtime 자동 Resume **금지**. 위험 작업은 **2단계 승인 → Audit → 실행**.

## Components

| Module | Role |
|--------|------|
| `notification/telegram_commands.py` | `TelegramCommandHandler` — 명령 라우팅 |
| `notification/telegram_status.py` | `TelegramOpsStatusService` — 조회 응답 |
| `notification/telegram_approval_service.py` | `TelegramApprovalService` — 승인·TTL·Replay 방지 |
| `notification/telegram_operations_notifier.py` | 운영 알림 포맷·`notify_order_event` |
| `notification/telegram_polling.py` | Polling 스케줄러 |
| `api/v1/telegram_ops.py` | Webhook 엔드포인트 |

## Commands (Read-only)

| Command | 설명 |
|---------|------|
| `/start` | 환영·안내 |
| `/help` | 명령 목록 |
| `/status` | Operations Center 요약 (STEP 10-3) |
| `/system` | 프로세스·환경 |
| `/runtime` | Runtime·LIVE·ARM·Kill Switch |
| `/scheduler` | Trading Scheduler 상태 |
| `/broker` | 브로커 헬스 |
| `/account` | UBA 계정 목록 |
| `/balance` | 잔고 스냅샷 |
| `/orders` | 오늘 주문 요약 |
| `/positions` | 보유 포지션 |
| `/audit` | 최근 Audit |
| `/recovery` | Recovery·Conflict |
| `/health` | 헬스·리소스 |
| `/version` | 빌드·커밋 |
| `/ping` | 연결 확인 |

## Approval (Dangerous)

| 1단계 요청 | 2단계 승인 | 실행 |
|-----------|-----------|------|
| `/kill` | `YES` 또는 `/confirm <token>` | KillSwitchService.activate |
| `/resume` | 동일 | KillSwitchService.deactivate |
| `/pause_scheduler` | 동일 | TradingSchedulerControlService.pause |
| `/start_scheduler <uba_id>` | 동일 | TradingSchedulerControlService.start |

- **Timeout:** 60초
- **Replay 방지:** Token 1회 사용
- **Audit:** `TELEGRAM_APPROVAL_REQUESTED`, `TELEGRAM_APPROVAL_CONFIRMED`, `TELEGRAM_ACTION_EXECUTED`

## Notification

`notification_publisher` / `NotificationEventType` 확장:

- Order: SUBMITTED, FILLED, PARTIAL, CANCELLED, REJECTED
- Recovery: STARTED, FAILED, CONFLICT
- Scheduler: STARTED, PAUSED, ERROR
- Runtime: STARTED, PAUSED
- Broker: CONNECTED, DISCONNECTED, TIMEOUT
- System: START, STOP, RESTART
- Safety: KILL_SWITCH
- Conflict: RECONCILIATION_MISMATCH, SUBMISSION_UNKNOWN

헬퍼: `notify_operational_event`, `notify_order_event`

## Security

| 항목 | 정책 |
|------|------|
| Chat ID | `TELEGRAM_ALLOWED_CHAT_IDS` whitelist (비어 있으면 **전부 거부**) |
| Token | 로그·Audit에 **마스킹 없이 token 기록 금지** — event detail에만 짧은 token (운영 승인용) |
| Bot Token | env Secret, 로그 출력 금지 |
| RBAC | Telegram은 별도 DB RBAC 없음 — Chat whitelist = 운영자 게이트 |

## Dashboard 연동

`/status` → `OperationsCenterDashboardService.summary()` → `format_dashboard_summary_html()`

Admin UI와 동일 데이터 소스 (3초 TTL 캐시).

## 운영 방법

1. `.env` 설정:
   - `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
   - `TELEGRAM_ALLOWED_CHAT_IDS=<your_chat_id>`
   - `TELEGRAM_OPS_ENABLED=true`
2. 서버 기동 → `telegram_ops_scheduler` polling 시작
3. Telegram에서 `/start`, `/status`로 조회 확인
4. 위험 작업: `/kill` → `YES` (60초 이내)

Webhook 사용 시: `TELEGRAM_WEBHOOK_SECRET` + `POST /api/v1/telegram/ops`

## 장애 대응

| 증상 | 조치 |
|------|------|
| 모든 명령 "권한 없음" | `TELEGRAM_ALLOWED_CHAT_IDS`에 Chat ID 추가 후 재기동 |
| 승인 만료 | 60초 내 재요청 |
| Polling 중단 | 로그 `telegram_ops_poller` 확인, `TELEGRAM_OPS_ENABLED` |
| 알림 미수신 | `TELEGRAM_ENABLED`, `TELEGRAM_NOTIFICATION_LEVEL` 확인 |

## Tests

```bash
pytest tests/test_step10_4_telegram_operations_center.py tests/test_telegram_ops_step54.py -q
```

## Safety checklist

- [ ] 실주문 경로 호출 없음
- [ ] Broker submit 없음
- [ ] LIVE/ARM 자동 변경 없음
- [ ] Scheduler/Runtime 자동 Resume 없음
- [ ] 위험 명령 2단계 승인 필수
