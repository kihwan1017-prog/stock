# README_STEP53 — Real-Time Position Exit Monitor

## 1. 목적

`PROJECT_FINAL_AUDIT.md` Critical 항목:

> PositionExitMonitor가 구현되어 있으나 실제 Lifecycle에 연결되지 않음

을 해소한다. 기존 자동매매·API·리스크 엔진은 유지하고, **실시간 청산 폴링만 Lifecycle에 연결**한다.

이번 STEP에서 Telegram 전송은 하지 않는다. 청산 이벤트는 `NotificationPublisher`로만 전달한다.

---

## 2. 컴포넌트 호출 관계

```text
ApplicationLifecycle.startup
  └─ position_exit_monitor_scheduler.start()   # Polling
       └─ PositionExitMonitorManager.check_now()
            ├─ PositionExitMonitorLoader.load()
            │    ├─ PaperPosition (qty > 0)
            │    ├─ PriceDailyService.get_latest()
            │    ├─ RiskRepository.get_policy() / Settings 비율
            │    ├─ KillSwitchService.is_active()
            │    └─ Daily Loss (realized + unrealized vs max_daily_loss)
            └─ PositionExitMonitorService.evaluate_and_exit()
                 ├─ RiskManagementEngine.evaluate_exit()
                 │    ├─ STOP_LOSS
                 │    ├─ TAKE_PROFIT
                 │    ├─ RELATIVE_LOSS
                 │    └─ TRAILING_STOP
                 ├─ (force) KILL_SWITCH / DAILY_LOSS
                 ├─ OrderExecutionService.submit(SELL)
                 └─ NotificationPublisher.publish(event)

DailyLossMonitorScheduler (기존, 유지)
  └─ DailyLossMonitor → KillSwitch 활성화 가능
       └─ 이후 ExitMonitor tick에서 KILL_SWITCH 강제 청산
```

| 컴포넌트 | 역할 |
|----------|------|
| Position / PaperPosition | 보유 수량·평단·최고가 |
| PositionRepository (레거시 in-memory) | 변경 없음 — ExitMonitor는 PaperPosition ORM 사용 |
| OrderExecutionService | 청산 LIMIT SELL + Outbox |
| RiskManagementEngine | 가격 기반 청산 판단 |
| KillSwitch | 활성 시 전 포지션 강제 청산 |
| DailyLossMonitor | 일손실 한도 → KillSwitch (기존) / ExitMonitor도 일손실 직접 검사 |
| TrailingStop / StopLoss / TakeProfit / RelativeLoss | `evaluate_exit` 내부 판단 |

Realtime Strategy Runner의 SL/TP 로직은 **제거하지 않음** (중복 허용).

---

## 3. Lifecycle 구조

| 단계 | 동작 |
|------|------|
| startup → scheduler startup | `position_exit_monitor_scheduler.start()` |
| shutdown → scheduler shutdown | `position_exit_monitor_scheduler.shutdown()` |

미연결 원인: `PositionExitMonitorService`가 정의만 되어 있고 import·기동 경로가 없었음.

---

## 4. ExitMonitor 구조

- **방식:** Polling (Event 아님)
- **주기:** `POSITION_EXIT_MONITOR_INTERVAL_SECONDS` (기본 5초)
- **활성화:** `POSITION_EXIT_MONITOR_ENABLED` (기본 true)
- **청산 주문:** `skip_risk_checks=True` (시스템 청산, 계정번호 미설정 환경 호환)
- **브로커 코드:** Paper 포지션 기준 `PAPER`

임계값 우선순위:

1. 활성 `strategy.risk_policy` (`SCHEDULER_POLICY_ID`)의 SL/TP/Trailing
2. 없으면 Settings의 `POSITION_EXIT_*_RATIO`

---

## 5. Risk Engine 연동

`RiskManagementEngine.evaluate_exit` 결과를 그대로 사용한다.

추가: `relative_loss_ratio` → 사유 `RELATIVE_LOSS`  
(기존 SL/TP/Trailing 분기 유지)

강제 청산(`force_exit_reason`)은 Kill/Daily 시에만 Risk 가격 평가를 건너뛴다.

---

## 6. Logging

| 이벤트 | 로그 키 |
|--------|---------|
| 모니터 시작 | `position_exit_monitor_started` |
| 모니터 종료 | `position_exit_monitor_stopped` |
| 포지션 검사 | `position_exit_inspect` / `position_exit_scan_*` |
| 청산 조건 발견 | `position_exit_condition_found` |
| 청산 주문 생성 | `position_exit_order_created` |
| 청산 실패 | `position_exit_order_failed` |
| 알림 적재 | `notification_published` |

---

## 7. NotificationPublisher

파일: `notification/publisher.py`

전달 이벤트:

- `STOP_LOSS` / `TAKE_PROFIT` / `TRAILING_STOP` / `RELATIVE_LOSS` / `KILL_SWITCH`
- 추가로 `DAILY_LOSS` (내부·테스트용)

Telegram/Slack 채널 호출은 **하지 않음**. 이후 STEP에서 Publisher → Sender 브리지만 추가하면 된다.

---

## 8. 변경 파일

### Backend
- `src/stock_platform/risk/models.py` — `relative_loss_ratio`
- `src/stock_platform/risk/engine.py` — RELATIVE_LOSS 판단
- `src/stock_platform/position/exit_monitor.py` — 로그·강제청산·Publisher
- `src/stock_platform/position/exit_monitor_loader.py` — 신규
- `src/stock_platform/position/exit_monitor_runtime.py` — 신규
- `src/stock_platform/position/exit_monitor_scheduler.py` — 신규
- `src/stock_platform/notification/publisher.py` — 신규
- `src/stock_platform/api/lifecycle.py` — start/shutdown 연결
- `src/stock_platform/common/settings.py` — ExitMonitor 설정
- `.env.example`
- `tests/test_position_exit_monitor_step53.py`

### API
- **변경 없음** (기존 엔드포인트 유지)

---

## 9. 테스트 방법

```powershell
cd D:\Projects\stock-platform
.\.venv\Scripts\python.exe -m pytest tests/test_position_exit_monitor_step53.py tests/test_step38_completion.py tests/test_risk_management_engine.py tests/test_application_lifecycle.py -q

cd frontend
npm run lint
npm run typecheck
npm run test
npm run build
```

커버: Stop Loss / Take Profit / Trailing / Relative Loss / Kill Switch / Daily Loss / HOLD / 주문 실패 / Lifecycle 연결 / disabled 설정.

---

## 10. 주의사항

- Realtime Strategy의 SL/TP와 ExitMonitor가 **동시에** 청산을 시도할 수 있다. Outbox idempotency key로 동일 사유·수량 중복은 완화된다.
- 시세가 없으면 평단가를 fallback으로 사용한다. 시세·종목 미존재 시 해당 심볼은 skip.
- Kill Switch 활성 시 SELL은 기존 Guard가 허용한다. ExitMonitor는 강제 청산으로 제출한다.
- Telegram 실전송은 후속 STEP.

---

## 11. 완료 체크리스트

- [x] 구조 분석·문서화
- [x] Lifecycle 연결
- [x] Polling 주기 설정화
- [x] Risk Engine 연동 + Relative Loss
- [x] NotificationPublisher (Telegram 미전송)
- [x] 테스트
- [x] lint / typecheck / build / test
