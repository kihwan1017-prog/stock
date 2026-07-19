# README_STEP54 — Telegram Operations Center

> **DEPRECATED / OUT OF SCOPE (OpenClaw only):**  
> OpenClaw integration was removed from the active project scope. (STEP57-1)  
> Telegram Ops·Publisher 경로는 유효. Admin UI는 `/admin/telegram`.

## 1. 목적

운영자가 **Telegram만으로** 자동매매 시스템 상태를 확인하고,
Kill Switch를 제어할 수 있게 한다.

- 자동매매 로직은 수정하지 않음
- Notification Layer만 구현
- Service → TelegramSender 직접 호출 금지
- **Publisher → NotificationService → TelegramSender** 경로만 사용

---

## 2. Architecture

```text
[Domain / Lifecycle / ExitMonitor / RiskAlert]
        │
        ▼
 NotificationPublisher.publish(_async)
        │
        ▼
 NotificationService.dispatch
   ├─ level filter (INFO/WARN/CRITICAL)
   ├─ NotificationHistory (in-memory)
   ├─ AuditLog (TELEGRAM_SEND)
        │
        ▼
 CompositeNotificationSender
   └─ TelegramNotificationSender  (+ LOG/Slack/Discord)

[Telegram User]
   /status /health /orders ...
        │
        ▼
 getUpdates polling  OR  POST /api/v1/telegram/webhook
        │
        ▼
 TelegramCommandHandler
   ├─ chat_id 권한 검사
   ├─ Audit (RECEIVE / COMMAND / PERMISSION_DENIED)
   ├─ TelegramOpsStatusService (조회만)
   ├─ KillSwitchService (/kill /resume)
   └─ reply via TelegramBotClient.send_html
```

---

## 3. 현재 구현 상태 (분석)

| 컴포넌트 | 상태 |
|----------|------|
| NotificationSender | ✅ ABC |
| TelegramNotificationSender | ✅ 송신 |
| NotificationService | ✅ STEP54 재구현 (전달 계층) |
| NotificationChannel | ✅ enum |
| NotificationTemplate | ❌ (미도입, 메시지 인라인) |
| NotificationHistory | ✅ 인메모리 |
| NotificationSettings | ✅ env 스냅샷 |
| NotificationPublisher | ✅ STEP53 + 전송 연결 |
| Test API | ✅ `/notification/test` → Publisher |

---

## 4. Events

`NotificationEventType`:

SYSTEM_START, SYSTEM_STOP, ORDER_SUBMITTED, ORDER_FILLED, ORDER_REJECTED,
STOP_LOSS, TAKE_PROFIT, TRAILING_STOP, RELATIVE_LOSS, KILL_SWITCH, DAILY_LOSS,
AI_ANALYSIS_COMPLETE, BACKTEST_COMPLETE, BROKER_DISCONNECTED, BROKER_RECONNECTED,
DATABASE_ERROR, SCHEDULER_ERROR

`TELEGRAM_NOTIFICATION_LEVEL`로 필터 (INFO ⊃ WARN ⊃ CRITICAL).

Lifecycle가 SYSTEM_START / SYSTEM_STOP을 publish한다.
ExitMonitor·RiskAlert는 Publisher만 사용한다.

ORDER_* / AI / BACKTEST / BROKER / DB / SCHEDULER 이벤트는 enum·Publisher 경로 준비.
호출부 연결은 자동매매 수정 없이 후속 가능 (partial).

---

## 5. Commands

| 명령 | 동작 |
|------|------|
| `/status` | Server/Version/DB/Broker/Scheduler/Jobs/Kill/DailyLoss/PnL/Orders/Positions |
| `/system` | 프로세스·환경 |
| `/health` | CPU/Memory/Disk/DB/Broker/Ollama/Scheduler |
| `/orders` | 오늘 주문 체결·미체결·취소 |
| `/positions` | 보유·평가손익·수익률 |
| `/kill` | Kill Switch 활성화 (허용 chat만) |
| `/resume` | Kill Switch 해제 |
| `/help` | 도움말 |

권한: `TELEGRAM_ALLOWED_CHAT_IDS` (+ 기본 `TELEGRAM_CHAT_ID`).

---

## 6. Settings

| Env | 설명 |
|-----|------|
| `TELEGRAM_ENABLED` | 알림 송신 on/off |
| `TELEGRAM_BOT_TOKEN` | Bot token |
| `TELEGRAM_CHAT_ID` | 기본 chat |
| `TELEGRAM_OPS_ENABLED` | 명령 polling |
| `TELEGRAM_OPS_POLL_INTERVAL_SECONDS` | polling 주기 |
| `TELEGRAM_ALLOWED_CHAT_IDS` | 허용 chat (쉼표) |
| `TELEGRAM_NOTIFICATION_LEVEL` | INFO/WARN/CRITICAL |
| `APP_VERSION` | /status Version |

Admin: `/admin/openclaw` · `/admin/env-settings` · SettingsEditor(environment).

---

## 7. API

| Method | Path | 설명 |
|--------|------|------|
| GET | `/api/v1/notification/status` | 채널·설정·이력 |
| POST | `/api/v1/notification/test` | Publisher 경유 테스트 |
| GET | `/api/v1/telegram/ops/status` | Ops 상태 (admin) |
| POST | `/api/v1/telegram/webhook` | Telegram Update 수신 |
| POST | `/api/v1/telegram/commands/test` | Admin 명령 시뮬 |

---

## 8. Audit Log

| event_type | 시점 |
|------------|------|
| TELEGRAM_SEND / NOTIFICATION_SEND | 채널 송신 |
| TELEGRAM_RECEIVE | 메시지 수신 |
| TELEGRAM_COMMAND | 명령 실행 |
| TELEGRAM_PERMISSION_DENIED | 권한 오류 |
| TELEGRAM_COMMAND_TEST | Admin 테스트 |

---

## 9. 변경 파일

### Backend
- `notification/events.py`, `history.py`, `service.py`, `publisher.py`, `runtime.py`
- `notification/telegram_*.py` (status/commands/bot_client/polling)
- `api/v1/telegram_ops.py`, `api/v1/notifications.py`
- `api/lifecycle.py`, `api/router.py`
- `risk_engine/alert.py` — Publisher만 사용
- `common/settings.py`, `operation/setting_catalog.py`, `.env.example`
- `tests/test_telegram_ops_step54.py`

### Frontend
- `features/admin/openclaw/opsCatalog.ts`
- `app/(admin)/admin/openclaw/page.tsx`

### Docs
- `README_STEP54.md`

---

## 10. Test

```powershell
cd D:\Projects\stock-platform
.\.venv\Scripts\python.exe -m pytest tests/test_telegram_ops_step54.py tests/test_position_exit_monitor_step53.py -q

cd frontend
npm run lint
npm run typecheck
npm run test
npm run build
```

커버: 송신(dispatch), 명령 수신, 권한, Kill/Resume, Status, Health, Lifecycle 연결.

---

## 11. 주의사항

- `TELEGRAM_OPS_ENABLED=true` + token/chat 설정 후에만 Bot 명령 polling 동작
- 허용 chat 미설정 시 모든 명령 거부 (안전)
- 명령 응답은 BotClient, 알림 이벤트는 반드시 Publisher
- CPU/Memory는 psutil 있으면 사용, 없으면 fallback
- 자동매매(Strategy/Execution) 코드는 변경하지 않음

---

## 12. 완료 체크리스트

- [x] 구조 분석
- [x] Event + Publisher→Service→Telegram
- [x] Bot 명령
- [x] Admin 설정 점검
- [x] Audit
- [x] 테스트 · lint/typecheck/build
