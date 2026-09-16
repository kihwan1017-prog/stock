# STEP 10-2 — Scheduler 및 운영 상태 재시작 정책·영속화

## 기존 문제 원인

| 항목 | 원인 |
|------|------|
| Scheduler desired | `trading_scheduler_control.py` 프로세스 메모리 (`_DESIRED_STATE=PAUSE` 기본값) |
| 재시작 후 PAUSE | uvicorn/프로세스 재시작 시 모듈 재로드 → 메모리 초기화 |
| actual state | `realtime_trading_scheduler.scheduler.running` (APScheduler in-memory) |
| Startup | lifecycle가 Trading Scheduler를 자동 start 하지 않음 |
| LIVE/ARM | DB `trading.user_broker_account`에 영속 — **재시작 시 자동 OFF 없었음** |

## 상태별 Source of Truth

| 상태 | SoT | 영속화 | Startup 정책 |
|------|-----|--------|--------------|
| Trading Scheduler desired | `operation.runtime_control_state` | DB | DB 로드 후 조건부 복원 |
| Trading Scheduler actual | APScheduler `running` | 메모리 | desired=RUN + 안전조건 시 start |
| Runtime (runners) | in-process | 메모리 | **강제 paused** |
| Strategy Runtime | `DynamicStrategyRuntimeManager` | 메모리 | bootstrap 후 **pause_all** |
| LIVE | `user_broker_account.live_order_enabled` | DB | **강제 OFF** |
| ARM | `user_broker_account.live_armed` | DB | **강제 OFF, TTL 갱신 금지** |
| Recovery Scheduler | settings + APScheduler | env/메모리 | 기존 lifecycle start 유지 |
| Account Pause | `broker_recovery_account_state` / risk | DB | **유지** |
| Kill Switch | `trading.kill_switch` | DB | **유지** |

## desired / actual 분리

- `desired_state`: 운영자 의도 (DB `operation.runtime_control_state`)
- `actual_state`: 프로세스 APScheduler 실행 여부
- `blocked_reason`: desired=RUN 이지만 actual=PAUSED 인 사유
- `health`: RUNNING / PAUSED / BLOCKED

예: `desired=RUN`, `actual=PAUSED`, `blocked_reason=KILL_SWITCH_ACTIVE`

## Scheduler 조건부 복원 (Startup Phase 2)

`desired=RUN` 일 때만 평가. **LIVE/ARM OFF 필수** (Fail Closed).

차단 조건:

- Migration not at head
- Kill Switch active
- Broker health CRITICAL
- Submission Unknown > 0
- Strategy scopes / runners active
- LIVE 또는 ARM ON

복원 성공 시 `realtime_trading_scheduler.start()` — **주문 API 호출 없음**.

## LIVE / ARM Fail Closed

Startup Phase 1:

1. DB에서 scheduler desired 로드 → 메모리 hydrate
2. `live_order_enabled=true` → **OFF** + `LIVE_STARTUP_FORCED_OFF` Audit
3. `live_armed=true` → `LiveArmService.disarm` (TTL **갱신 없음**) + `ARM_STARTUP_FORCED_OFF` Audit

## uvicorn reload vs 운영 서비스

| 환경 | 동작 |
|------|------|
| 개발 `--reload` | 자식 프로세스 재생성 → Startup policy 재실행 (DB SoT) |
| 운영 NSSM/서비스 | 단일 lifecycle, DB desired 기준 복원 |
| 비정상 종료 | actual=PAUSED, desired=DB 유지 |

Shutdown 시 desired를 PAUSE로 **저장하지 않음** (운영자 의도 보존).

## API

| Method | Path | 설명 |
|--------|------|------|
| GET | `/api/v1/admin/trading-scheduler/status` | desired/actual/health/blocked_reason/persisted |
| POST | `/api/v1/admin/trading-scheduler/start` | gates + DB persist + version |
| POST | `/api/v1/admin/trading-scheduler/pause` | DB persist + idempotent |

## Audit 이벤트

- `TRADING_SCHEDULER_DESIRED_STATE_CHANGED`
- `TRADING_SCHEDULER_STARTUP_RESTORE_ATTEMPTED` / `RESTORED` / `BLOCKED`
- `LIVE_STARTUP_FORCED_OFF` / `ARM_STARTUP_FORCED_OFF`
- `RUNTIME_STARTUP_FORCED_PAUSED` / `STRATEGY_RUNTIME_STARTUP_FORCED_IDLE`
- `RECOVERY_STARTUP_RESTORED` / `RECOVERY_STARTUP_RESTORE_FAILED`

## Migration

- ID: `t0a1b2c3d4e5`
- Table: `operation.runtime_control_state`
- Seed: `TRADING_SCHEDULER` / `desired=PAUSE`

## Rollback

```powershell
.venv\Scripts\alembic -c alembic.ini downgrade s8c9d0e1f2a3
```

코드 rollback: lifecycle phase1/2 호출 제거 → 메모리-only 동작 복귀.

## Rehearsal (실주문 0)

| 시나리오 | 기대 |
|----------|------|
| A desired=PAUSE → 재시작 | actual=PAUSED |
| B desired=RUN, 안전조건 OK | actual=RUNNING, 주문 0 |
| C desired=RUN, Kill Switch | actual=PAUSED, blocked_reason |
| D 이전 LIVE/ARM ON fixture | Startup 후 OFF |
| E Kill Switch active | 복원 차단 |

## order 250 백필

STEP 10-1 범위. `fill-sync`는 read-only가 아니며 DB mutation 가능. **본 STEP에서 자동 실행하지 않음** — 운영자 별도 승인.

## 운영 체크리스트

- [ ] Migration `t0a1b2c3d4e5` 적용
- [ ] 재시작 후 LIVE/ARM OFF 확인
- [ ] `GET .../trading-scheduler/status` → `persisted=true`
- [ ] desired=RUN 시 `blocked_reason` 확인
- [ ] 실주문 0

## STEP 10-1 연결

Post-fill/Snapshot 안정화(STEP 10-1)와 독립. Scheduler RUN이어도 LIVE=false/ARM=false면 주문 경로 차단.
