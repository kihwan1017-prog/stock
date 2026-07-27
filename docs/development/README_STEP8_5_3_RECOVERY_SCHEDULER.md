# STEP 8-5-3 — Recovery Scheduler

공통 `BrokerRecoveryManager`를 기존 APScheduler lifecycle Framework에 연결해  
키움·업비트·Paper 정기 Recovery를 운영한다.

---

## 1. 기존 Scheduler 구조

- 라이브러리: **APScheduler** (`AsyncIOScheduler`)
- API lifespan (`ApplicationLifecycle`): settings → DB → auth → **Recovery** → strategy → **schedulers**
- Lifecycle cron 예: `daily_loss_monitor`, strategy reload/approval 등
- 장후 배치: `AutomaticScheduler` (별도 `scripts/run_scheduler.py`)
- Job History: `operation.job_run_history` + `JobExecutionService`
- 리더 락: `scheduler_leader_lock_enabled` 시 PG advisory lock
- Job ID 규칙: snake_case, `replace_existing=True`, `max_instances=1`, `coalesce=True`

## 2. 기존 Recovery 구조

- `BrokerRecoveryManager.recover_all` / `recover_account`
- 계좌별 `asyncio.Lock` + DB TTL Lock (`broker_recovery_account_state`)
- Adapter: Kiwoom / Upbit / Stock Paper / Crypto Paper
- Startup Recovery (timeout 150s) → Scheduler보다 선행
- ADMIN 수동: `/api/v1/admin/recovery/*`
- STEP 8-5-2: UBA Vault Credential (env fallback 금지)

## 3. 선택한 Scheduler 통합 구조

```text
ApplicationLifecycle._start_schedulers
        ↓
BrokerRecoveryScheduler (APScheduler)
        ↓
run_recovery_scheduler_job
        ↓
JobExecutionService → operation.job_run_history
        ↓
BrokerRecoveryManager.recover_all / recover_account
        ↓
계좌 Lock + Adapters
```

신규 Scheduler 엔진을 만들지 않고 lifecycle AsyncIOScheduler 패턴을 재사용한다.

## 4. Job 목록

| Job ID | Broker | Trigger (기본) | 목적 |
|--------|--------|----------------|------|
| `broker_recovery_kiwoom_preopen` | KIWOOM | Cron `30 8 * * mon-fri` Asia/Seoul | 장 시작 전 |
| `broker_recovery_kiwoom_postclose` | KIWOOM | Cron `40 15 * * mon-fri` | 장 종료 후 |
| `broker_recovery_upbit_interval` | UPBIT | Interval 20분 | 24h 경량 |
| `broker_recovery_paper_integrity` | PAPER | Interval 360분 | 정합성 |
| `broker_recovery_failed_retry` | ALL | Interval 15분 | 실패 재시도 |

설정 저장: `operation.broker_recovery_scheduler_job` (ADMIN 편집 가능)

## 5. 키움 실행 정책

- Timezone: **Asia/Seoul** (OS TZ 비의존)
- `TradingCalendarService(KRX)`로 거래일 게이트
  - DB calendar 우선
  - 없으면 주말 휴장 / 평일 `WEEKDAY_FALLBACK`
- 공휴일·임시휴장이 calendar에 없으면 **한계**로 문서화 (후속 보완)
- 휴장일: `SKIPPED_NON_TRADING_DAY` (외부 호출 생략)

## 6. 업비트 실행 정책

- Interval 기본 20분, ADMIN 변경 시 **최소 10분**
- concurrency 기본 2 (동시 폭주 방지)
- 429/network → Backoff 재시도 대상
- Credential/Manual Review → 자동 재시도 중지

## 7. Paper 실행 정책

- Stock/Crypto Paper 동일 Manager·Lock
- Interval 기본 6시간 (최소 60분)
- 외부 Credential 불필요

## 8. 계좌 Lock 재사용

Startup / ADMIN 수동 / Scheduler / Retry 모두 `BrokerRecoveryManager` → 동일 asyncio+DB Lock.  
충돌 시 `SKIPPED_LOCKED` (오류 폭탄 금지).

## 9. Startup Recovery 충돌 방지

1. Startup Recovery 선행 (기존 순서 유지)
2. 완료·타임아웃 모두 `_startup_finished_at` 기록
3. Scheduler Job는 Cooldown(`RECOVERY_SCHEDULER_STARTUP_COOLDOWN_SECONDS`, 기본 120초) 동안 `SKIPPED_COOLDOWN`

## 10. 수동 Recovery 충돌 방지

- `recover_all` 글로벌 running 플래그 → Scheduler는 `SKIPPED_BUSY`
- 계좌 Lock → `SKIPPED_LOCKED`

## 11. Retry·Backoff

계좌 상태 컬럼: `retry_count`, `next_retry_at`, `last_error_code`, `auto_retry_enabled`

- 비재시도: credential_*, vault_unavailable, manual_review, 계좌 정지 등
- 재시도: network/timeout/429 — 지수 Backoff + jitter, `max_retries` 초과 시 중지
- `broker_recovery_failed_retry` Job가 due 계좌만 처리

## 12. Rate Limit

- Job별 concurrency 상한 (1–10)
- APScheduler `max_instances=1`
- Upbit Interval 하한 10분
- 429는 error code `rate_limit`로 분류 후 Backoff

## 13. Credential Vault 연계

- UBA LIVE: Adapter가 Vault 필수 (env fallback 금지)
- Credential 실패 → pause 유지 + auto_retry 중지
- SYSTEM_SHARED: UBA 없는 운영 슬롯만

## 14. Runtime pause·resume

- Recovery 중 `trading_paused=true` (기존 Lock)
- 성공·정합성 OK·Manual Review 없음 → `keep_paused=false`로 재개
- 실패/Conflict → pause 유지
- 주문 가드: `require_order_safety` / Recovery pause (기존)

## 15. 관리자 API

| Method | Path |
|--------|------|
| GET | `/api/v1/admin/recovery/scheduler/status` |
| GET | `/api/v1/admin/recovery/scheduler/jobs` |
| PUT | `/api/v1/admin/recovery/scheduler/jobs/{job_id}` |
| POST | `.../enable` / `.../disable` |
| POST | `.../run` (즉시 실행, force) |
| GET | `/api/v1/admin/recovery/scheduler/runs` |

`require_admin` + 감사 로그.

## 16. Frontend

- `/admin/recovery`에 `RecoverySchedulerPanel` 연결
- Job 목록·활성/비활성·즉시 실행·설정 수정·실행 이력
- Mock 없음

## 17. env 동기화 API 잔여 처리

조사 결과:

- `POST /api/v1/broker/kiwoom/account/sync`
- `POST /api/v1/broker/upbit/account/sync`

→ **SYSTEM_SHARED env로 스냅샷만 동기화**. UBA Vault로 Secret 복사 API **없음**.

조치:

- docstring에 SYSTEM_SHARED 전용·UBA 복사 금지 명시
- 응답에서 secret 계열 키 방어적 제거
- 제거(410)하지 않음 — 운영 공용 스냅샷에 필요

## 18. DB 변경

- 신규: `operation.broker_recovery_scheduler_job` (+ 시드 5건)
- 확장: `operation.broker_recovery_account_state` retry 컬럼 4개
- 계좌 상세 이력은 기존 `broker_recovery_run` 재사용 (중복 테이블 없음)
- Scheduler Job Run: 기존 `job_run_history` (`job_group=RECOVERY`)

## 19. Migration ID

- **`u8b9c0d1e2f3`**
- down: `t7a8b9c0d1e2`
- 파일: `database/alembic/versions/u8b9c0d1e2f3_broker_recovery_scheduler.py`

## 20. 감사 로그

- Job enable/disable/update
- ADMIN 즉시 실행  
Secret/Master Key 미기록.

## 21. 변경 파일 (주요)

- `broker/recovery_scheduler.py`, `recovery_scheduler_service.py`, `recovery_scheduler_models.py`
- `broker/recovery_runtime.py`, `recovery_account_state.py`
- `api/lifecycle.py`, `api/v1/admin_recovery_scheduler.py`
- `api/v1/kiwoom_account_sync.py`, `upbit_account.py` (문서·마스킹)
- Frontend: `RecoverySchedulerPanel`, adminApi, recovery page
- Migration `u8b9c0d1e2f3`

## 22. 테스트 결과

| 항목 | 결과 |
|------|------|
| Backend unit (8-5-3) | 통과 |
| Migration down/up | 통과 |
| Vitest | 76/76 |
| TypeScript | 통과 |
| Lint | error 0 / Warning 6 (기존) |
| Production Build | 성공 |

## 23. 운영 적용 방법

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
# RECOVERY_SCHEDULER_ENABLED=true (기본)
# RECOVERY_SCHEDULER_STARTUP_COOLDOWN_SECONDS=120
# 서버 재시작 (NSSM/ops)
```

ADMIN `/admin/recovery`에서 Job 활성·주기 확인 후 즉시 실행 스모크.

## 24. 기존 Lint Warning 상태

6건 유지 (onboarding / watchlist / AuthGuard / tokenStorage). 신규 Warning 없음.

## 25. 남은 문제

- KRX 공휴일: calendar 미적재 시 WEEKDAY_FALLBACK (임시 한계)
- Key Rotation dual-read (8-5-2 잔여)
- 다중 인스턴스 분산 Lock 강화는 STEP 8-5-6 범위
- Upbit Retry-After 헤더 정밀 파싱은 후속 보강 가능
- AutomaticScheduler(장후 워커)와 Recovery Job는 분리 — Recovery는 API lifecycle만
