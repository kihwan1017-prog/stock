# STEP 09 — Scheduler와 자동매매 Runtime 정리

> 작성일: 2026-07-22  
> 목표: 스케줄러 등록 계약을 테스트·문서와 맞추고, 중복 기동·다중 인스턴스 위험을 줄인다.

---

## 1. 분석 결과

### 1.1 스케줄러 이중 경로

| 경로 | 역할 | 기동 |
|------|------|------|
| **API lifecycle** | 일손실, exit monitor, telegram, 전략 reload/approval/pipeline/performance, **outbox** | FastAPI startup |
| **AutomaticScheduler** | candidate / AI / position / equity snapshot (장후 배치) | `scripts/run_scheduler.py` 전용 |
| **RealtimeTradingScheduler** | 장전·개장·마감·장후 세션 | API/recovery로 수동 start (lifecycle은 shutdown만) |

`SCHEDULER_ENABLED`는 **AutomaticScheduler만** 게이트한다. lifecycle cron과 혼동하지 말 것.

### 1.2 AutomaticScheduler 계약 job

```text
candidate_screening_daily
ai_orchestration_daily
position_planning_daily
portfolio_equity_snapshot_daily   ← 테스트가 3개로 고정되어 실패했던 원인
```

### 1.3 다중 인스턴스

- APScheduler는 **MemoryJobStore** (분산 락 없음)
- Outbox는 `SKIP LOCKED`로 replica-safe
- lifecycle cron은 replica마다 중복 가능 → **PG advisory lock** 옵션 추가

---

## 2. 수정한 파일

| 파일 | 내용 |
|------|------|
| `scheduler/automatic.py` | `REGISTERED_JOB_IDS`, idempotent start |
| `realtime/session_scheduler.py` | `REGISTERED_JOB_IDS` |
| `scheduler/leader_lock.py` | PG `pg_try_advisory_lock` 리더 선출 |
| `common/settings.py` | `lifecycle_scheduler_enabled`, `scheduler_leader_lock_enabled` |
| `api/lifecycle.py` | outbox 항상 기동 + lifecycle cron 게이트/리더 락 |
| strategy `*_scheduler.py` (3) | `mon-fri` + timezone |
| `operation/monitoring_snapshot.py` | lifecycle 게이트·자동 워커 안내 분리 |
| `scripts/run_scheduler_job.py` | equity snapshot choice |
| 테스트·`.env.example--` | 계약 기반 테스트 |
| `docs/audit/STEP09_SCHEDULER_RUNTIME.md` | 본 문서 |

---

## 3. 주요 수정 내용

1. **테스트 계약:** “3개” 하드코딩 제거 → `REGISTERED_JOB_IDS` 집합 검증  
2. **configure 멱등:** `replace_existing=True` + 이중 configure 테스트  
3. **전략 cron:** 주말 오발 방지 (`mon-fri`, timezone)  
4. **lifecycle 게이트:** `LIFECYCLE_SCHEDULER_ENABLED`  
5. **리더 락:** `SCHEDULER_LEADER_LOCK_ENABLED=true` 시 리더만 cron (outbox 제외)  
6. **모니터링:** Automatic 비활성 ≠ API lifecycle DISABLED

---

## 4. 테스트 결과

```powershell
pytest tests/test_automatic_scheduler.py tests/test_scheduler_leader_lock.py ... -q
# → 통과

pytest -q
# → 1 failed, 540 passed, 3 skipped
```

잔여 실패:

- `test_unauthenticated_order_mutate_rejected` — 로컬 PG password (환경, STEP17)

**Scheduler 관련 실패: 0**

---

## 5. 운영 가이드

```text
# 장후 배치 워커 (API와 별도 프로세스)
python scripts/run_scheduler.py

# 다중 API replica
LIFECYCLE_SCHEDULER_ENABLED=true
SCHEDULER_LEADER_LOCK_ENABLED=true
```

Realtime 세션 스케줄러는 `/api/v1/realtime-sessions` 또는 recovery 경로에서 start.

---

## 6. 남아 있는 문제

- AutomaticScheduler를 docker-compose/NSSM 서비스로 상시 등록하는 ops 문서 보강(배포 STEP)
- RealtimeTradingScheduler를 lifecycle에 자동 편입할지 정책 결정 필요
- DB JobStore(APScheduler)는 도입하지 않음 — advisory lock으로 대체

---

## 7. 다음 단계

명령서 순서상 **STEP10 키움증권 기능 상세 검증**.

---

## 8. 권장 커밋 메시지

```text
fix(step09): align scheduler job contracts and add lifecycle leader lock
```
