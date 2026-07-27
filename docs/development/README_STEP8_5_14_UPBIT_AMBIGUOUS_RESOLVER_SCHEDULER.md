# STEP 8-5-14 — Upbit Ambiguous 주문 Resolver Scheduler (DB Claim / 분산 Lock)

## 1. 목표

STEP 8-5-12의 `UpbitAmbiguousOrderResolver.resolve_one`(원격 조회 전용)을 **자동으로**
주기 실행하는 Scheduler. DB Claim + 계좌 단위 분산 Lock으로 Multi-Worker에서도
중복 처리 없이 동작하며, 실행 이력을 영속 저장한다. **주문 재생성/재제출은
절대 수행하지 않는다.**

## 2. 재사용한 기존 컴포넌트

| 컴포넌트 | 역할 |
|---|---|
| `UpbitAmbiguousOrderResolver.resolve_one` | 원격 조회·매칭·상태 전이 (Lookup Only) |
| `DistributedRecoveryLockManager` | 계좌 단위 Fencing Lock |
| `RecoveryLockScope(USER_BROKER, uba_id, UPBIT, CRYPTO)` | Lock Scope |
| `BrokerCredentialVaultService` | Credential `VERIFIED` 게이트 |
| `UpbitRateLimitCoordinator` | Rate Limit / 418 Cooldown 게이트 |
| `get_recovery_instance_identity()` | Owner/Instance ID |

## 3. DB Claim 필드 (신규 상태값 추가 없음)

`trading.trading_order`에 4개 컬럼 추가:

- `resolver_claimed_by` (String 100)
- `resolver_claimed_at` (timestamptz)
- `resolver_claim_expires_at` (timestamptz)
- `resolver_run_token` (String 64)

기존 상태(`AMBIGUOUS_SUBMISSION`, `REMOTE_LOOKUP_PENDING`)를 그대로 사용하고,
Claim 여부는 이 4개 필드로만 판단한다 — 새 상태 `REMOTE_LOOKUP_RUNNING`을
도입하지 않았다 (상태 머신 변경 최소화).

## 4. 원자적 Claim SQL

```sql
UPDATE trading.trading_order
SET resolver_claimed_by = :owner, resolver_claimed_at = NOW(),
    resolver_claim_expires_at = NOW() + make_interval(secs => :claim_seconds),
    resolver_run_token = :run_token, updated_at = NOW()
WHERE order_id = :order_id
  AND status_code IN ('AMBIGUOUS_SUBMISSION', 'REMOTE_LOOKUP_PENDING')
  AND next_remote_lookup_at IS NOT NULL AND next_remote_lookup_at <= NOW()
  AND (resolver_claim_expires_at IS NULL OR resolver_claim_expires_at < NOW())
  AND client_order_identifier IS NOT NULL AND client_order_identifier <> ''
RETURNING order_id
```

단일 `UPDATE ... RETURNING`으로 원자성 보장 (동시 Worker 중 1개만 성공).

## 5. 후보 선택 + Fairness

`SELECT ... FOR UPDATE SKIP LOCKED`로 Due 후보를 짧게 조회한 뒤 즉시 커밋해
Row Lock을 해제하고, 계좌별 Round-Robin으로 `batch_size` 만큼 재배열한다
(`_apply_fairness`). 한 계좌가 배치를 독점하지 못하도록 계좌당
`upbit_ambiguous_max_orders_per_account_per_run` 상한을 적용한다.

## 6. 배치 실행 알고리즘

```text
run row(RUNNING) 생성 (due_count>0 인 경우만)
for order in fair_order:
  atomically claim (run_token=uuid4)
  if not claimed: continue
  acquire DistributedRecoveryLockManager lock (timeout 2s)
  if busy: defer(+5s) without attempt bump, LOCK_NOT_ACQUIRED attempt 기록
  check credential VERIFIED — 아니면 defer(+30s) without attempt
  check rate limit coordinator — blocked면 defer(wait_seconds) without attempt
  resolve_one(order_id, actor=SCHEDULER:{instance_id}, force=True)
  lock_manager.assert_owns(handle) — 실패 시 rollback, LOCK_OWNERSHIP_LOST
  release claim
  release lock
  update run counters
run row 종료 (SUCCEEDED/PARTIAL/FAILED)
audit (claimed_count==0 이고 due_count==0이면 skip)
```

주문 생성/전송 API는 이 경로에서 **호출되지 않는다** — `resolve_one`은 조회 전용.

## 7. Run History 영속화

`operation.upbit_ambiguous_resolution_run` — trigger_type, requested_by,
instance_id, status_code, due/claimed/found/not_found/manual_review/conflict/
lock_busy/credential_blocked/rate_limited/error 카운터, result_summary(JSONB),
started_at/finished_at/duration_ms.

## 8. Migration

`b5c6d7e8f9a0` ← `a4b5c6d7e8f9`

- Claim 컬럼 4개 추가
- 인덱스: `(broker_code, status_code, next_remote_lookup_at)`,
  `(resolver_claim_expires_at)`, `(user_broker_account_id, next_remote_lookup_at)`
- Backfill (upgrade 시 1회):
  - Identifier 있는 AMBIGUOUS_SUBMISSION/REMOTE_LOOKUP_PENDING 중
    `next_remote_lookup_at IS NULL` → `COALESCE(ambiguous_since, updated_at, now()) + 2s`
  - Identifier 없는 건 → `MANUAL_REVIEW_REQUIRED` (Due Queue 제외)
  - 두 UPDATE 모두 `RETURNING`으로 영향 행 수를 카운트해 `print()`로 기록
    (실행 로그에서 확인 가능; 별도 테이블에 저장하지 않음)
- `operation.upbit_ambiguous_resolution_run` 테이블 생성

## 9. downgrade

컬럼/인덱스/테이블 모두 역순 제거. Backfill 데이터는 되돌리지 않음(상태
전이는 정보 손실 없이 재현 불가하므로 downgrade는 스키마만 원복).

## 10. Attempt 계산 원칙

`remote_lookup_attempt_count`는 **실제 Upbit API 호출 직전**에만 증가한다
(`resolve_one`에서 `client.get_order()` 호출 바로 앞). Scheduler의 Lock
busy/Credential 미검증/Rate Limit 지연 경로는 Attempt를 소모하지 않는다
(`_defer_without_attempt`).

## 11. 백오프 상한 + Jitter

`_capped_backoff_seconds(base, max_seconds, jitter_ratio=0.15)` —
`_handle_not_found`(NOT_FOUND_TRANSIENT)와 `UpbitTemporaryUnavailableError`
경로에서 지수 백오프를 `upbit_ambiguous_lookup_max_interval_seconds`로
제한하고 소량 Jitter를 더해 Thundering Herd를 방지.

## 12. Lock 정책

`DistributedRecoveryLockManager` timeout=2s (짧게) — Recovery/실주문 흐름을
막지 않기 위함. Busy면 즉시 포기하고 5초 뒤 재시도. 성공 확정 직전
`assert_owns`로 Fencing 재검증 — 상실 시 Rollback 후 미확정 상태로 종료.

## 13. Credential 게이트

`BrokerCredentialVaultService(session).status(uba_id, "UPBIT")` —
`verification_status != "VERIFIED"`면 30초 Defer, Attempt 미소모.

## 14. Rate Limit 게이트

`UpbitRateLimitCoordinator.check_allowed(uba_id, endpoint_group=infer_group(ORDER_QUERY))`
— 차단 시 `max(5s, wait_seconds)` Defer.

## 15. SubmissionAttemptResult 확장

`REMOTE_LOOKUP_STARTED/DEFERRED/CREDENTIAL_BLOCKED/RATE_LIMITED`,
`LOCK_ACQUIRED/LOCK_NOT_ACQUIRED/LOCK_OWNERSHIP_LOST`.

## 16. 설정

```
upbit_ambiguous_resolver_poll_seconds = 5       # >= 1
upbit_ambiguous_resolver_batch_size = 20        # > 0
upbit_ambiguous_resolver_claim_seconds = 60     # >= 30
upbit_ambiguous_max_orders_per_account_per_run = 5  # > 0
upbit_ambiguous_lookup_max_interval_seconds = 60    # > 0
upbit_ambiguous_resolver_run_history_days = 30      # > 0
```

기존 `upbit_ambiguous_resolver_enabled`(기본 비활성 여부는 기존 STEP 설정
유지)로 전체 On/Off.

## 17. Scheduler 등록

`UpbitAmbiguousOrderResolutionScheduler` — `IntervalTrigger(poll_seconds)`,
Job id `upbit_ambiguous_order_resolver`, `max_instances=1`, `coalesce=True`.
`lifecycle.py`의 `_start_schedulers`에서 **Leader Lock 여부와 무관하게**
Outbox와 동일 원칙으로 항상 기동(DB Claim이 중복 처리를 막아주므로).

## 18. Multi-Worker 안전성

- Claim: 단일 `UPDATE ... RETURNING` — DB가 원자성 보장
- Lock: Fencing Token 기반 분산 Lock — Claim 이후 실제 처리 중 Race 방지
- 두 계층 모두 실패해도 서로 다른 Worker가 동일 주문을 이중 처리 불가

## 19. Admin API — Resolver

`/api/v1/admin/upbit/ambiguous-resolver`

| Method | Path | 설명 |
|---|---|---|
| GET | `/status` | 설정값, Scheduler 상태, Queue Health, 마지막 Run |
| GET | `/runs` | Run 이력 목록 (`limit`, `offset`) |
| GET | `/runs/{run_id}` | Run 상세 |
| POST | `/run-now` | 즉시 1회 배치 실행 (Audit 기록) |

## 20. Admin API — Ambiguous Orders 확장

`/api/v1/admin/upbit/ambiguous-orders`

- `POST /{order_id}/retry-lookup` — Scheduler와 동일한 Claim 경로로 즉시 조회
  (Claim 중이면 409)
- `POST /{order_id}/release-stale-claim` — **만료된** Claim만 강제 해제
  (유효 Claim은 409 거부)
- `_order_dict`에 `resolver_claimed_by/claimed_at/claim_expires_at` 추가
  (Admin 전용 가시성, Run Token은 미노출)

## 21. USER API 안전 필드

`orders.py`에 `_safe_order_dict` 신설 — `next_remote_lookup_at`,
`last_remote_lookup_at`, `remote_lookup_attempt_count`,
`manual_review_required`(bool), `remote_order_found`(bool)만 노출.
Claim Owner/Token/분산 Lock 정보는 **절대 미노출**.

## 22. Health

`upbit_ambiguous_resolver` 컴포넌트 — enabled, claimed_count,
expired_claim_count, last_run_status/started_at/finished_at, scheduler 상태.

## 23. Frontend — Admin 패널

`UpbitAmbiguousOrdersPanel.tsx`:

- Resolver Scheduler 상태 카드 (Running/Stopped, Poll/Batch/Claim 설정,
  다음 실행 시각, 최근 실행 요약) + "지금 실행" 버튼
- 주문 테이블에 Claim 컬럼(Owner + 만료 시각) 추가
- 행 작업에 "재조회(Claim)"·"Claim 해제" 버튼 추가
- Resolver 실행 이력 테이블(Trigger/상태/Due/Claimed/Found/NotFound/
  Manual/LockBusy/Error/시작/소요시간)

## 24. Frontend — adminApi 헬퍼

`getUpbitAmbiguousResolverStatus`, `listUpbitAmbiguousResolverRuns`,
`getUpbitAmbiguousResolverRun`, `runUpbitAmbiguousResolverNow`,
`retryUpbitAmbiguousLookup`, `releaseUpbitAmbiguousStaleClaim`.

## 25. Frontend — USER 주문 화면

`BrokerOrdersView.tsx` 상태 컬럼에 AMBIGUOUS/REMOTE_LOOKUP_PENDING/
MANUAL_REVIEW_REQUIRED일 때 다음 재조회 시각(HH:mm:ss)과 시도 횟수를
부가 설명으로 표시. Claim/Lock 등 내부 정보는 표시하지 않음.

## 26. Frontend 테스트

`upbitAmbiguousResolver.test.ts` — adminApi에 Resolver 헬퍼가 노출되고
Claim/Lock 토큰 접근자나 자동 제출 API는 없음을 검증하는 계약 테스트.

## 27. Pause/Resume 정책

기존 `_pause_uba`(Identity Conflict 시 계좌 일시정지)를 그대로 재사용.
본 STEP에서는 자동 Resume을 구현하지 않음 — Resume은 관리자 수동 처리로
유지(Conservative). Blocking Ambiguous가 남아있는지 자동 판단하는 별도
자동화는 범위 밖으로 문서화.

## 28. Audit

`UPBIT_AMBIGUOUS_RESOLUTION_RUN`(배치 시작/종료, 빈 폴링은 skip),
`ADMIN_UPBIT_AMBIGUOUS_RESOLVER_RUN_NOW`,
`ADMIN_UPBIT_AMBIGUOUS_RETRY_LOOKUP`,
`ADMIN_UPBIT_AMBIGUOUS_RELEASE_STALE_CLAIM`.

## 29. 자동 재제출 금지 재확인

`resolve_one`은 STEP 8-5-12부터 조회/매칭/상태 전이만 수행하며 주문
생성·전송 API를 호출하지 않는다. 본 STEP에서 추가된 Scheduler/Service
어디에도 Order Create/Submit 호출이 없다 (코드 검토 + 테스트로 보증).

## 30. 변경 파일

- `broker/upbit/ambiguous_constants.py` — Attempt 타입 확장
- `broker/upbit/ambiguous_resolver.py` — Attempt 지연 증가, 백오프 Cap+Jitter
- `broker/upbit/ambiguous_resolution_entities.py` (신규) — Run 이력 Entity
- `broker/upbit/ambiguous_resolution_service.py` (신규) — 배치 로직
- `broker/upbit/ambiguous_resolution_scheduler.py` (신규) — APScheduler 등록
- `order/entities.py` — Claim 컬럼 + 인덱스
- `common/settings.py`, `.env.example` — Resolver 설정 6종
- `api/lifecycle.py` — Scheduler 기동/종료
- `api/v1/admin_upbit_ambiguous_resolver.py` (신규)
- `api/v1/admin_upbit_ambiguous_orders.py` — retry-lookup/release-stale-claim
- `api/v1/orders.py` — `_safe_order_dict`
- `api/router.py` — Router 등록
- `operation/health_service.py` — `upbit_ambiguous_resolver` 컴포넌트
- `database/alembic/env.py` — 신규 Entity 등록
- `database/alembic/versions/b5c6d7e8f9a0_upbit_ambiguous_resolver_claim.py` (신규)
- FE: `UpbitAmbiguousOrdersPanel.tsx`, `adminApi.ts`, `BrokerOrdersView.tsx`,
  `userApi.ts`(TradeOrder 필드), `upbitAmbiguousResolver.test.ts`(신규)
- `tests/test_step8_5_14_upbit_ambiguous_resolver_scheduler.py` (신규)
- `tests/test_step8_5_12_upbit_order_idempotency.py` — Head 검증 문구 조정

## 31. 테스트 결과

```text
Backend pytest: 768 passed / 0 failed / 3 skipped
Frontend Vitest: 92 passed (36 files)
TypeScript: 통과
Lint: 0 errors / 0 warnings
Production Build: 성공
Alembic Head: b5c6d7e8f9a0 (single)
Migration down/up: a4b5c6d7e8f9 ↔ b5c6d7e8f9a0 성공
Backfill (검증 DB): due_scheduled=0, manual_review_no_identifier=0
```

신규: `tests/test_step8_5_14_upbit_ambiguous_resolver_scheduler.py` (14)

## 32. 신규 테스트 커버리지

- Claim 배타성 + 만료 후 재Claim (실 PostgreSQL 통합 테스트)
- Lock busy → Attempt 미증가 + LOCK_NOT_ACQUIRED 기록 + Lock release 미호출
- Lock ownership 상실 → rollback + 미확정 종료
- Attempt는 실제 API 호출 직전에만 증가 (Deferred 경로는 미증가)
- Fairness 계좌당 상한 / 배치 크기 준수
- Run History 카운터 영속화 (SUCCEEDED/PARTIAL 판정)
- Scheduler Disabled / No-Due 시 Run Row 미생성
- Release Stale Claim (유효 Claim 거부 / 만료 Claim만 해제)

## 33. 운영 적용

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
```

배포 후 `UPBIT_AMBIGUOUS_RESOLVER_ENABLED=true`로 전환해야 Scheduler가
실제로 기동한다 (기존 설정값 유지 시 비활성).

## 34. 모니터링 포인트

- `/api/v1/admin/upbit/ambiguous-resolver/status`의 `queue.oldest_ambiguous_since`
- `expired_claim_count` > 0 지속 시 Worker 비정상 종료 의심 → Release Stale Claim
- `lock_busy_count`/`credential_blocked_count` 급증 시 계좌 상태 점검

## 35. 알려진 제약

- Claim 만료(`resolver_claim_expires_at`) 이후에도 이전 Worker가 살아있다면
  이론상 이중 처리 가능 — 분산 Lock의 Fencing Token이 2차 방어선.
- Run History는 `upbit_ambiguous_resolver_run_history_days` 설정값이
  존재하지만 본 STEP에서는 자동 정리(Retention Job)를 구현하지 않음 —
  후속 STEP 과제로 남김.

## 36. 남은 과제 (8-5-15 범위, 착수하지 않음)

- Run History Retention 자동 정리 Job
- Resolver Run 상세(단건) Admin UI 뷰
- Identity Conflict 이후 자동 Resume 판단 로직
