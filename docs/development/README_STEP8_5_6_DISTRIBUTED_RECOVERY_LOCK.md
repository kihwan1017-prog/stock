# STEP 8-5-6 — PostgreSQL 기반 다중 인스턴스 분산 Recovery Lock

## 1. 기존 Lock 구조

- 프로세스 내부 `asyncio.Lock` (`BrokerRecoveryManager._account_locks[scope_key]`)
- Soft DB lock: `operation.broker_recovery_account_state` 의 `lock_holder` / `lock_expires_at` (`RecoveryAccountLockService`)
- Scheduler `max_instances=1` (프로세스 내부 APS 보호만)

## 2. 단일 프로세스 Lock 한계

NSSM 중복 기동, 다중 Worker/서버, Startup·Scheduler·ADMIN이 서로 다른 프로세스에서 동시에 돌면 같은 계좌 Recovery가 중복 실행될 수 있다.

## 3. 비교한 Lock 방식

| 방식 | 장점 | 단점 |
|------|------|------|
| A. PG Advisory Session Lock | 세션 종료 시 자동 해제 | Recovery 전체 동안 Connection 점유, Pool 고갈 위험 |
| B. Lease Row + Heartbeat + Fencing | Owner/TTL/Fencing 저장, 짧은 Transaction | CAS·TTL·Fencing 구현 필요 |

## 4. 선택한 방식과 이유

**Atomic Lease Row Update + Heartbeat + Monotonic Fencing Token** (`operation.broker_recovery_lock`).

이유:

- 장시간 Broker API 동안 DB Connection을 점유하지 않음
- Owner·Lease·Fencing·만료를 운영 화면에서 조회 가능
- 이미 account state는 pause/retry용으로 쓰이므로 Lock은 별도 테이블로 역할 분리

## 5. Lock Scope

`RecoveryLockScope`: `account_kind` + `account_id` + `broker_code` + `market_type`

- LIVE: USER_BROKER + `user_broker_account_id`
- Paper: PAPER + `paper_account_id`
- 계좌번호·Secret·표시명 미포함

## 6. Lock Key

`rlk:` + SHA-256(`stock-platform-recovery|…`) hex 40자. Python `hash()` 미사용.

## 7. Instance Identity

`stock-platform:<hostname>:<pid>:<startup_uuid>` — 프로세스 시작 시 1회 생성. 테스트는 override 주입 가능.

## 8. DB 구조

- `operation.broker_recovery_lock` (scope unique, status check, indexes)
- `operation.broker_recovery_run` 에 `fencing_token`, `lock_scope_key`, `owner_instance_id`, `lease_id` 추가
- 기존 Lock 상태 Backfill 없음

## 9. Lock 획득

`UPDATE … WHERE status IN (FREE,RELEASED) OR (HELD AND lease_expires_at < NOW())` + `fencing_token = fencing_token + 1` RETURNING. 동시 Takeover는 하나만 성공.

결과: `ACQUIRED` | `BUSY` | `TIMEOUT` | `STALE_TAKEN_OVER`

## 10. Heartbeat

기본 30초마다 Owner+Lease+Token 일치 시에만 Lease 연장. 실패 시 `ownership_lost` + `LockOwnershipLostError`. Recovery 종료 시 Task 취소.

## 11. Lease

기본 TTL 120초. DB `NOW()` 기준.

## 12. Fencing Token

획득 시 단조 증가. Run에 저장. 성공/실패/pause 해제/Runtime Resume 전 `assert_owns`.

## 13. Stale Takeover

만료 HELD row를 새 Owner가 원자적으로 인수, token 증가.

## 14. Lock 해제

Owner+Lease+Token 일치 시에만 `RELEASED`. Ownership Lost 후 이전 Owner 해제 불가.

## 15. Ownership Lost

`LOCK_LOST` Run 상태, Pause 유지, Resume 금지, 감사 로그.

## 16. Recovery 통합

`recover_account()` → Local Lock → Distributed Lock → `_recover_account_under_lock()`. 호출자 우회 불가.

## 17. Scheduler 통합

Busy → `SKIPPED_DISTRIBUTED_LOCK` 집계 (에러율 증가 방지). `max_instances=1` 유지.

## 18. Startup 통합

Startup도 동일 `recover_all`/`recover_account` 경로. Busy는 Skip.

## 19. ADMIN 수동 Recovery 통합

동일 Manager. 단일 계좌 Busy 시 HTTP 409 + Owner 마스킹·만료 시각. 강제 해제 UI/API 없음.

## 20. Runtime Pause·Resume

Lock 획득 후 해당 계좌만 Pause. Resume는 소유권·fencing 유지 + 성공 시에만.

## 21. Credential Vault 연계

Lock 획득 → Credential 확인 → Vault 복호화 → Broker API. Credential 원문은 Lock/Audit에 기록하지 않음.

## 22. 관리자 API

- `GET /api/v1/admin/recovery/locks`
- `GET /api/v1/admin/recovery/locks/{scope_key}`

## 23. Frontend

`/admin/recovery` 에 Distributed Lock 패널 (새로고침·자동 새로고침·Run 이동). 강제 해제 버튼 없음.

## 24. Audit Log

ACQUIRED / BUSY / STALE_TAKEOVER / OWNERSHIP_LOST / RELEASED. Heartbeat 성공은 미기록.

## 25. Migration

- ID: `w0a1b2c3d4e5`
- Revises: `v9c0d1e2f3a4`
- upgrade/downgrade, single head

## 26. 변경 파일

- `database/alembic/versions/w0a1b2c3d4e5_broker_recovery_distributed_lock.py`
- `src/stock_platform/broker/recovery_distributed_lock*.py`
- `src/stock_platform/broker/recovery_instance_id.py`
- `src/stock_platform/broker/recovery_runtime.py`
- `src/stock_platform/broker/recovery_scheduler_service.py`
- `src/stock_platform/broker/recovery_entities.py`
- `src/stock_platform/api/v1/admin_recovery.py`
- `src/stock_platform/common/settings.py`
- `.env.example`
- Frontend recovery lock panel + adminApi
- tests `test_step8_5_6_*`

## 27. 테스트 결과

```text
신규 STEP 단위/CAS/Migration: 20 passed
Backend pytest: 648 passed / 0 failed / 3 skipped
Frontend Vitest: 82/82
TypeScript: 통과 (next build)
Lint: 0 errors / 기존 Warning 6
Production Build: 성공
Alembic down/up: v9c0d1e2f3a4 ↔ w0a1b2c3d4e5 성공
Alembic Head: w0a1b2c3d4e5 (single head)
```

## 28. 운영 적용

1. `alembic upgrade head` (revision `w0a1b2c3d4e5`)
2. env: `RECOVERY_DISTRIBUTED_LOCK_ENABLED=true`, Lease=120, Heartbeat=30, Acquire Timeout=5
3. 다중 Worker/NSSM 중복 시 계좌별 Busy Skip 정상
4. Stale는 Lease 만료 후 Takeover — 강제 해제 미제공 (오해제 방지)
5. Rollback: `alembic downgrade v9c0d1e2f3a4` + 분산 Lock 코드 롤백
6. 시각 기준: DB `NOW()` (OS Clock drift 완화)

## 29. 기존 Lint Warning 상태

기존 Warning 6건 유지 목표 (신규 error 0).

## 30. 남은 문제

- Advisory Lock 미사용 — Session Lock 자동 해제는 Lease TTL·Heartbeat에 의존
- 강제 Lock 해제는 별도 위험 운영 기능으로 후속 STEP
- USER는 `trading_paused` / `recovery_status` 수준만 (Owner 미노출)
