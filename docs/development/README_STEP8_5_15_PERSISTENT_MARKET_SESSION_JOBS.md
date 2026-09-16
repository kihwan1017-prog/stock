# STEP 8-5-15 — 영속 Market Session Job (DB Claim 기반 Dispatcher/Reconcile)

## 1. 목표

`calendar_scheduler_recompute._DYNAMIC_JOBS`(프로세스 메모리 딕셔너리)를
DB 테이블(`operation.market_session_job`)로 대체해 **다중 인스턴스에서도
Job이 유실되지 않고, 정확히 한 인스턴스만 실행**하도록 한다. 프로세스가
재시작되거나 여러 Worker가 동시에 뜬 상태에서도 Preopen/Postclose
Recovery, 자산 Snapshot, 정산, AI 분석 Job이 중복 실행되거나 소실되지
않는 것이 핵심 목표다.

## 2. 배경 — 왜 메모리 딕셔너리로는 안 되는가

- `_DYNAMIC_JOBS`는 프로세스 단위 전역 변수라서 재시작 시 전부 사라진다.
- 여러 인스턴스(API + Worker + Scheduler 프로세스)가 뜬 환경에서는 각
  프로세스가 서로 다른 메모리 상태를 가져 Job 목록이 어긋난다.
- Admin이 "이 Job이 언제 실행됐고, 실패했는지, 몇 번 재시도했는지"를
  물어봐도 프로세스가 재시작되면 답할 수 없었다.
- STEP 8-5-14(Upbit Ambiguous Resolver)에서 이미 검증된 DB Claim 패턴을
  Session Job에도 동일하게 적용한다.

## 3. 재사용한 기존 컴포넌트

- `broker/recovery_instance_id.get_recovery_instance_identity()` —
  인스턴스 식별자(Claim 소유자 이름)
- `operation/session_timeline.TradingSessionTimelineResolver` — 지연개장/
  조기종료를 반영한 실제 Preopen/Postclose/Snapshot/Settlement/AI 시각
- `operation/calendar_repository.TradingCalendarRepository` — VERIFIED
  거래일 조회 (Reconcile에서 사용)
- `broker/recovery_scheduler_service.run_recovery_scheduler_job` — Preopen/
  Postclose Recovery 실제 실행 로직 (Handler가 그대로 재사용)
- `scheduler/service.SchedulerService.execute` — Snapshot/AI 실제 Job 실행

## 4. 신규 테이블 — `operation.market_session_job`

Job 정의 + 생명주기 상태를 함께 갖는 단일 테이블. 주요 컬럼:

- `job_key` (UNIQUE) — `{EX}:{date}:{TYPE}:rev{N}` 포맷. 같은 Revision에
  같은 Job이 두 번 만들어지는 것을 DB 레벨에서 방지한다.
- `(exchange_code, market_date, job_type, calendar_revision)` UNIQUE —
  자연키로도 유일성을 한 번 더 보장한다.
- `status_code` — `SCHEDULED / CLAIMED / RUNNING / SUCCEEDED / FAILED /
  RETRY_PENDING / SKIPPED / SUPERSEDED / CANCELLED / EXPIRED`
- `claimed_by / claimed_at / claim_expires_at / run_token` — 원자적 Claim
  전용 필드
- `attempt_count / max_attempts / next_retry_at` — 재시도/백오프
- `superseded_by_job_id / superseded_at` — Calendar Revision 변경 시 이전
  Job을 대체
- `depends_on_job_id` — AI 분석 Job이 동일 Revision Snapshot Job에 의존

## 5. 신규 테이블 — `operation.market_session_job_run`

각 실행 시도(Attempt)의 이력을 남긴다. `run_number`, `instance_id`,
`run_token`, `started_at/finished_at`, `result_code`, `lag_seconds`
(scheduled_for 대비 실제 시작 지연) 등을 기록해 Admin이 지연·실패
패턴을 추적할 수 있게 한다.

## 6. Migration

- Revision ID: `c6d7e8f9a0b1`
- Revises: `b5c6d7e8f9a0`
- 파일: `database/alembic/versions/c6d7e8f9a0b1_persistent_market_session_jobs.py`
- 두 테이블 생성 + 4개 인덱스(Due 조회, Claim 만료, Exchange/Date, Revision)
  + CHECK 제약(Revision ≥ 1, Attempt ≥ 0, Max Attempts ≥ 1) + 자기참조 FK
  (`superseded_by_job_id`, `depends_on_job_id`, `ON DELETE SET NULL`)

## 7. Backfill 로직

- 오늘부터 `days_ahead`(기본 7일)까지 `operation.trading_calendar_day`에서
  `is_trading_day=true AND verified_status='VERIFIED'`인 날짜만 대상으로
  한다 — `_DYNAMIC_JOBS`에서 가져오는 것이 아니라 Calendar 원본에서 새로
  계산한다.
- 시각은 마이그레이션 시점 고정 오프셋(Preopen -30분 / Postclose +10분 /
  Snapshot +10분 / Settlement +20분 / AI +30분 — `SessionOffsetConfig`
  기본값과 동일)을 사용한다. 실제 운영 오프셋이 `.env`에서 기본값과
  다르면, 애플리케이션 기동 후 최초 Calendar 재계산에서 실제 설정 기준
  으로 다시 보정된다.
- Catch-up 조건: `scheduled_for >= NOW() - 2분` 이거나, POST_CLOSE 계열
  (Postclose/Snapshot/Settlement/AI)이면 `NOW() - 3시간` 이내까지 허용한다.
- `ON CONFLICT (job_key) DO NOTHING` — 순수 SQL만 사용해 애플리케이션
  코드 Import 없이 마이그레이션 단독으로 완결된다 (순환 Import 방지).
- AI_ANALYSIS → EQUITY_SNAPSHOT 의존관계는 별도 `UPDATE`로 동일
  `(exchange, date, revision)` Snapshot Job의 ID를 `depends_on_job_id`에
  연결한다.
- 실행 로그에 `[STEP 8-5-15] backfill: total=N, by_type=(...),
  days_ahead=7` 형태로 결과를 출력한다.

## 8. SQLAlchemy `text()` 콜론 이스케이프 주의사항

Backfill SQL에서 `job_key` 문자열을 `'...' || ':rev' || revision::text`
로 만들 때, `:rev`가 SQLAlchemy `text()`의 Bind Parameter 문법
(`:paramname`)과 겹쳐 `InvalidRequestError: A value is required for bind
parameter 'rev'`가 발생했다. `\:rev`로 이스케이프하면 컴파일된 SQL에서는
백슬래시가 제거되고 리터럴 `:rev`만 남는다. Python 문자열 자체의
`SyntaxWarning`을 피하기 위해 SQL 문자열은 raw string(`r"""..."""`)으로
선언한다.

## 9. downgrade

인덱스 → FK 순서를 고려해 `market_session_job_run` → `market_session_job`
순으로 각각 인덱스를 먼저 drop한 뒤 테이블을 drop한다. 실제
`downgrade b5c6d7e8f9a0` → `upgrade head` 왕복 테스트로 재현성을
검증했다.

## 10. Job Key / 상수

`operation/market_session_job_constants.py`:

- `MarketSessionJobType` — `KRX_PREOPEN_RECOVERY`, `KRX_POSTCLOSE_RECOVERY`,
  `KRX_EQUITY_SNAPSHOT`, `KRX_SETTLEMENT`, `KRX_AI_ANALYSIS`
- `MarketSessionJobStatus` — 10개 상태 (§4 참고)
- `MarketSessionJobResult` — Handler가 반환하는 세부 결과 코드
  (`SKIPPED_TOO_LATE`, `SKIPPED_ALREADY_EXISTS`, `SKIPPED_DEPENDENCY`,
  `SETTLEMENT_NOOP`, `DEFERRED_TO_CRON` 등)
- `LEGACY_JOB_TYPE_MAP` — 구 `CALENDAR_JOB_TYPES` → 신규 Type 매핑
  (문서/디버깅 참고용)
- `build_job_key()` — `{EX}:{date}:{TYPE}:rev{N}` (기존
  `build_job_id`와 동일 포맷 유지, 하위 호환)

## 11. Realtime Phase는 DB Job으로 승격하지 않음

`KRX_OPEN_PHASE` / `NEW_ENTRY_CUTOFF` / `MARKET_CLOSE` / `REALTIME_RESYNC`
는 특정 시각 1회성 Job이 아니라 "현재 어느 Phase인지" 상태 조회이므로
DB Job으로 만들지 않는다. 계속 `session_timeline`의 Timeline Polling(5분
주기 동기화)에 위임한다.

## 12. `MarketSessionJobService`

`operation/market_session_job_service.py` — 단일 세션 범위에서 동작하는
CRUD/생명주기 서비스. 두 그룹으로 나뉜다.

1. **ORM 기반(트랜잭션 참여용)** — `create_or_supersede_for_revision`,
   `supersede_previous_revision`, `list_for_date`, `list_jobs`,
   `health_summary`, `has_succeeded` 등. Calendar 변경 트랜잭션과 같은
   세션에서 동작해야 하므로 `flush()`만 호출하고 `commit()`은 호출자
   책임이다.
2. **원자적 SQL 기반(Dispatcher 전용)** — `try_claim`, `mark_running`,
   `finish_job`, `release_claim`, `record_run`, `select_due_job_ids`.
   각각 짧은 트랜잭션 안에서 즉시 `commit()`한다.

## 13. Catch-up 판정 — `_catchup_eligible`

Job 생성 시점에 이미 지나간 시각이라도 무조건 버리지 않는다.

- `scheduled_for >= now - 120초` — 항상 생성(약간의 지연은 정상)
- POST_CLOSE 계열(Postclose Recovery/Snapshot/Settlement/AI)이고 당일
  장마감으로부터 3시간 이내면 Catch-up 목적으로 생성 허용
- 그 외(예: Preopen Recovery가 몇 시간 지난 경우)는 생성하지 않음 —
  실행해도 의미가 없기 때문

## 14. Revision Supersede

Calendar가 변경되면(지연개장/조기종료/휴장 전환 등) 새 Revision이
발급된다. `supersede_previous_revision()`은 같은 `(exchange, date)`에서
새 Revision과 다른 Revision을 가진 `ACTIVE_JOB_STATUSES`
(`SCHEDULED/CLAIMED/RUNNING/RETRY_PENDING`) Job을 모두 `SUPERSEDED`로
전환한다. 이미 `SUCCEEDED/FAILED` 등 종료된 Job은 손대지 않는다(감사
이력 보존).

## 15. Claim — 원자적 UPDATE

```sql
UPDATE operation.market_session_job
SET status_code = 'CLAIMED', claimed_by = :owner, claimed_at = NOW(),
    claim_expires_at = NOW() + make_interval(secs => :secs),
    run_token = :run_token, updated_at = NOW()
WHERE market_session_job_id = :job_id
  AND status_code IN ('SCHEDULED', 'RETRY_PENDING')
  AND scheduled_for <= NOW()
  AND (claim_expires_at IS NULL OR claim_expires_at < NOW())
RETURNING market_session_job_id
```

DB `NOW()`만 신뢰하고, 애플리케이션 시각(`datetime.now()`)은 Claim
조건에 쓰지 않는다 — 인스턴스 간 시계 오차로 인한 이중 실행을 방지한다.
`RETURNING`이 비어 있으면(=이미 다른 인스턴스가 Claim) `None`을 반환해
호출자가 조용히 스킵한다.

## 16. Ownership 재검증 — `run_token`

Claim에 성공한 인스턴스가 실행 도중 죽거나 Claim이 만료돼 다른
인스턴스가 재Claim할 수 있다. `finish_job()`은 종료 직전
`WHERE run_token = :run_token`으로 다시 검증하며, 이미 다른 인스턴스가
가져갔다면(`run_token` 불일치) `UPDATE`가 0행을 갱신해 `False`를
반환한다 — 이 경우 Dispatcher는 `OWNERSHIP_LOST`로 기록하고 최종 상태를
덮어쓰지 않는다.

## 17. `MarketSessionJobHandler` — Protocol + Registry

`operation/market_session_job_handlers.py` — Handler는 실제 업무 로직을
호출하고 `MarketSessionJobHandlerOutcome`(result_code/summary/error/
retry_after_seconds)만 반환한다. **상태 전이 결정은 전부 Dispatcher가
한다** — Handler는 판단 재료만 제공해 관심사를 분리했다.

## 18. Handler — Preopen/Postclose Recovery

`_KiwoomRecoveryHandlerBase`를 공유하며 기존
`run_recovery_scheduler_job(job_id, trigger_type="MARKET_SESSION_JOB")`을
그대로 호출한다.

- Preopen: 이미 정규장이 열렸으면(`now >= regular_open_at`)
  `SKIPPED_TOO_LATE`로 즉시 반환하고 Recovery를 호출하지 않는다.
- Postclose: `krx_cron_fallback_late_tolerance_minutes`(기본 60분)를
  초과했으면 마찬가지로 `SKIPPED_TOO_LATE`.

## 19. Handler — Equity Snapshot

`JobRunRepository.list_recent(job_name="portfolio_equity_snapshot",
status_code="SUCCESS")`로 당일 이미 성공한 실행이 있는지 먼저 확인해
`SKIPPED_ALREADY_EXISTS`로 중복 실행을 막는다. 없으면
`SchedulerService.execute(job_name="portfolio_equity_snapshot", ...,
trigger_type="MARKET_SESSION_JOB")`를 호출한다.

## 20. Handler — Settlement

정산 자동화가 아직 구현되지 않았으므로 감사 목적의 No-op
(`SETTLEMENT_NOOP`)만 반환한다. 실제 정산 로직은 STEP 8-5-16 이후
검토 대상으로 문서에 명시했다.

## 21. Handler — AI Analysis

`depends_on_job_id`(Snapshot Job)를 조회해:

- 아직 `ACTIVE_JOB_STATUSES`(진행 중)면 `RETRY`(30초 뒤 재시도)
- `FAILED/SKIPPED/EXPIRED/CANCELLED`로 끝났으면 `SKIPPED_DEPENDENCY`
- `SUCCEEDED`면 `SchedulerService.execute(job_name="ai_orchestration",
  ..., trigger_type="MARKET_SESSION_JOB")` 호출

## 22. `MarketSessionJobDispatcher`

폴링 → Claim → Handler 실행 → 최종화의 4단계로 구성되며, 각 단계는
서로 다른(짧은) DB 세션을 사용한다 — Handler가 원격 API 호출로 오래
걸릴 수 있어 Claim Row Lock을 오래 들고 있지 않기 위함이다.

- `run_once(batch_size)` — Due Job ID들을 조회 후 순차 처리
- `_process_one` — Claim → `mark_running` → Handler 호출 → `_finalize`
- `_finalize` — 결과 코드에 따라 `SUCCEEDED/SKIPPED/RETRY_PENDING/FAILED`
  결정, `run_token` 재검증 후 `finish_job` + `record_run`
- `run_now(job_id, actor)` — Admin 즉시 실행. `scheduled_for`를 무시하고
  강제 Claim(`_force_claim`)한다.

## 23. 재시도 백오프

`_compute_backoff_seconds(attempt, base, maximum)` — 지수 백오프
(`base * 2^(attempt-1)`, `maximum`으로 상한). 기본값:
`market_session_job_retry_base_seconds=30`,
`market_session_job_retry_max_seconds=600`,
`market_session_job_max_attempts=3`. `max_attempts` 도달 시 `FAILED`로
확정한다.

## 24. `MarketSessionJobReconciliationService`

`operation/market_session_job_reconcile.py` — 다음 두 가지를 주기적으로
수행한다.

1. **누락 Job 보정** — `market_session_job_reconcile_days_ahead`(기본
   7일) 범위의 VERIFIED 거래일을 순회하며
   `create_or_supersede_for_revision`을 호출한다. 이미 있으면
   자연스럽게 Skip된다(멱등).
2. **만료 Claim 정리** — `claim_expires_at`이 10분(`_EXPIRE_GRACE`)
   이상 지난 `CLAIMED/RUNNING` Job을 `EXPIRED`로 전환한다. Dispatcher가
   종료 처리 중인 찰나의 경합을 피하기 위한 유예시간이다.

## 25. 보존(Retention)

`purge_old_jobs(retention_days, run_retention_days)` — 종료 상태
(`SUCCEEDED/SUPERSEDED/EXPIRED/CANCELLED/SKIPPED`)인 Job 중
`retention_days`(기본 90일)보다 오래된 것과, `run_retention_days`(기본
90일)보다 오래된 Run 이력을 삭제한다. Reconcile Scheduler 주기마다
`maybe_purge()`로 함께 실행되며 별도 배치는 두지 않는다(과설계 방지).

## 26. `MarketSessionJobScheduler`

`upbit_ambiguous_resolution_scheduler`와 동일 원칙 — DB Claim 기반이라
Leader Lock 없이 다중 인스턴스가 모두 기동해도 안전하다.

- Dispatch Job — `market_session_job_dispatcher_poll_seconds`(기본 5초)
  주기 `IntervalTrigger`, `max_instances=1`, `coalesce=True`
- Reconcile Job — `market_session_job_reconcile_interval_seconds`(기본
  300초) 주기, `market_session_job_reconcile_enabled=False`면 등록하지
  않음
- `market_session_job_enabled=False`면 Scheduler 자체를 기동하지 않음

## 27. `calendar_scheduler_recompute` 리팩터링

`recompute_krx_session_jobs(..., session: Session | None = None)` —
`session`이 주어지면(=Calendar 변경 트랜잭션) 그 세션을 그대로 사용하고
`commit()`을 호출하지 않는다(호출자 책임). `session=None`이면(Admin
단독 강제 재계산 등) 새 세션을 열어 즉시 commit·close한다.

`_DYNAMIC_JOBS`는 더 이상 Source of Truth가 아니며, `_mirror_to_memory`
가 생성된 Job만 참고용으로 반영하는 **Deprecated 메모리 미러**로
남는다. `list_dynamic_jobs()` / `scheduler_recompute_failure_count()`
함수도 하위 호환을 위해 유지하되 문서/코드 주석에 Deprecated임을
명시했다.

## 28. `calendar_change_service.apply()` 트랜잭션 통합

`apply()`가 자신의 SQLAlchemy 세션(`self._session`)을
`recompute_krx_session_jobs(..., session=self._session)`으로 전달한다
— Calendar 변경과 Job 영속화가 하나의 트랜잭션으로 묶여, Job 생성이
실패해도 Calendar 자체는 롤백되지 않고 기존처럼
`APPLIED_WITH_SCHEDULER_ERROR`로 표시된다(부분 실패 허용 정책 유지).

## 29. Cron Fallback → Wakeup 위임

`broker/recovery_scheduler_service.krx_cron_fallback_gate`와
`scheduler/automatic.py`의 `_krx_session_cron_gate` 모두
`market_session_job_enabled + market_session_cron_wakeup_enabled`가
켜져 있으면, 고정 Cron(08:30/15:40 등)이 더 이상 Recovery/Snapshot/AI를
**직접 실행하지 않는다**. 대신 `MarketSessionJobService.ensure_wakeup()`
으로 DB Job 존재/기상만 보장하고, 실제 실행은 Dispatcher(Poller)가
담당한다.

## 30. 무한 위임 루프 방지 — `trigger_type`

Dispatcher의 Handler가 `run_recovery_scheduler_job(...,
trigger_type="MARKET_SESSION_JOB")`을 호출하면 내부에서
`krx_cron_fallback_gate(..., trigger_type="MARKET_SESSION_JOB")`도
호출된다. 이때 `trigger_type == "MARKET_SESSION_JOB"`이면 위임 블록을
건너뛰고 정상적으로 실제 실행 경로로 진행한다 — 그렇지 않으면
Dispatcher → Handler → Gate → 위임 → Dispatcher로 무한 루프가 발생한다.

## 31. `ensure_wakeup` 동작

- Active(`SCHEDULED/CLAIMED/RUNNING/RETRY_PENDING`) Job이 전혀 없으면
  다음 Revision으로 즉시 `SCHEDULED` Job을 새로 만든다(`payload:
  {"created_by": "cron_wakeup"}`).
- `SCHEDULED`인데 아직 미래 시각이면 `scheduled_for = NOW()`로 앞당겨
  Poller가 다음 주기에 바로 집어가게 한다.
- 이미 `CLAIMED/RUNNING`이거나 방금 깨웠으면 `NOOP`.
- 위임 실패(DB 예외 등) 시 로그만 남기고 `None`을 반환해 상위 호출자가
  레거시 직접 실행으로 Fail Open하도록 설계했다(Recovery 누락 방지가
  최우선).

## 32. 신규 설정 (`settings.py` + `.env.example`)

```
market_session_job_enabled=true
market_session_job_dispatcher_poll_seconds=5
market_session_job_batch_size=20
market_session_job_claim_seconds=120
market_session_job_reconcile_enabled=true
market_session_job_reconcile_interval_seconds=300
market_session_job_reconcile_days_ahead=7
market_session_job_max_attempts=3
market_session_job_retry_base_seconds=30
market_session_job_retry_max_seconds=600
market_session_job_retention_days=90
market_session_job_run_retention_days=90
market_session_cron_wakeup_enabled=true
```

값 검증(`_validate_market_session_job_settings`)이 양수/최소값 조건을
기동 시점에 강제한다.

## 33. Lifecycle 통합

`api/lifecycle.py`에서 `market_session_job_scheduler.start()`를 다른
Recovery/Session Scheduler와 같은 시점에 시작하고,
`await market_session_job_scheduler.shutdown()`을 정상 종료 경로에
포함했다.

## 34. Admin API

`api/v1/admin_market_session_jobs.py` — prefix
`/api/v1/admin/market-session-jobs`, 전부 `require_admin` 필요:

- `GET ""` — 목록(exchange/date/status/type 필터, limit/offset)
- `GET "/health"` — 상태별 카운트, Due/Running/Failed/Superseded, 평균
  Lag, Dispatcher Instance ID, Scheduler 등록/다음 실행 시각
- `POST "/reconcile"` — Reason 필수, 누락 Job 보정 + 만료 Claim 정리
- `GET "/{job_id}"`, `GET "/{job_id}/runs"` — 단건/이력 조회
- `POST "/{job_id}/run-now"` — 즉시 실행(강제 Claim), 이미 활성 Claim이면
  409
- `POST "/{job_id}/retry"` — `FAILED/RETRY_PENDING/EXPIRED/SKIPPED`에서만
  가능, 즉시 `SCHEDULED`로 재예약
- `POST "/{job_id}/cancel"` — 종료 상태가 아니면 `CANCELLED`로 전환
- `POST "/{job_id}/release-stale-claim"` — 만료된 Claim만 해제(멱등,
  아니면 `NOT_STALE_OR_NOT_CLAIMED`)

모든 변경 액션은 `AuditLogService.record()`로 감사 이벤트를 남긴다.

## 35. 기존 Calendar Jobs 엔드포인트 갱신

`admin_market_calendar.py`의
`GET /{exchange_code}/{calendar_date}/jobs`가 이제 DB
(`MarketSessionJobService.list_for_date`)를 우선 조회한다. 조회 실패
시에만(예외적 상황) `list_dynamic_jobs()` 메모리 미러로 Fallback한다.
Admin 프론트(`MarketCalendarPanel`)의 기존 컬럼(`job_id/status/run_at/
revision`)과 하위 호환되도록 DB Dict에 동일 이름 필드를 추가로
병기했다. 응답에 `"source": "DB" | "MEMORY_FALLBACK"`를 포함해 어느
경로로 응답했는지 구분할 수 있다.

## 36. Calendar 변경 Health에 Job 요약 추가

`GET /market-calendar/health`(Change Request Health) 응답에
`market_session_jobs` 키로 `MarketSessionJobService.health_summary()`
결과(Due/Running/Failed/Superseded/평균 Lag)를 함께 내려 Admin
Dashboard에서 한 번에 확인할 수 있게 했다.

## 37. USER 소프트 상태 — `snapshot_ready` / `analysis_ready`

`TradingCalendarService.user_status()`에 두 boolean 필드를 추가했다.
당일 `KRX_EQUITY_SNAPSHOT` / `KRX_AI_ANALYSIS` Job이 (가장 최근
Revision 기준) `SUCCEEDED`인지만 확인하며, **Job ID 등 내부 식별자는
절대 노출하지 않는다**. 조회 실패 시 조용히 `False`로 Fail-safe한다.

## 38. Frontend — Admin 패널

`frontend/src/features/admin/market/MarketSessionJobsPanel.tsx` —
`MarketCalendarPanel` 내부에 섹션으로 포함했다. Health 카드(Due/Running/
Failed/Superseded/평균 Lag/Scheduler 상태), 상태 필터가 있는 Job
테이블, Reconcile/즉시실행/재시도/Claim 해제/취소 액션(모두 사유 입력
모달 경유)을 제공한다.

## 39. Frontend — adminApi 헬퍼

`adminApi.ts`에 `listAdminMarketSessionJobs`,
`getAdminMarketSessionJobHealth`, `getAdminMarketSessionJob`,
`getAdminMarketSessionJobRuns`, `reconcileAdminMarketSessionJobs`,
`runNowAdminMarketSessionJob`, `retryAdminMarketSessionJob`,
`cancelAdminMarketSessionJob`,
`releaseStaleClaimAdminMarketSessionJob`를 추가했다.

## 40. Frontend — USER 배너

`MarketSessionBanner`가 `snapshot_ready` / `analysis_ready`이면 각각
"오늘 자산 스냅샷 완료" / "오늘 AI 분석 완료" Tag를 표시한다(Job ID
등은 노출하지 않는 순수 안내 메시지).

## 41. 신규 테스트

`tests/test_step8_5_15_persistent_market_session_jobs.py`:

- Migration Head 검증(`c6d7e8f9a0b1`)
- 순수 함수: `build_job_key` 포맷, `_catchup_eligible` (미래/과거/
  POST_CLOSE 유예창 안/밖)
- Preopen Handler가 이미 개장 이후면 `SKIPPED_TOO_LATE`로 실제 Recovery
  호출을 하지 않는지(Mock)
- Cron Gate가 `SCHEDULER` Trigger에서는 위임하고, `MARKET_SESSION_JOB`
  Trigger에서는 위임하지 않는지(무한 루프 방지, Mock)
- Reconcile이 VERIFIED 거래일만 처리하고 미검증 일자는 Skip하는지(Mock)
- 실제 PostgreSQL(Migration 적용) 대상 통합 테스트 5종
  (`@pytest.mark.integration`):
  - Job Key UNIQUE 제약 위반 시 `IntegrityError`
  - Claim 배타성 + `run_token` 불일치 시 종료 거부(Ownership Lost) +
    `RETRY_PENDING` 재Claim
  - Revision Supersede(이전 5개 SUPERSEDED, 신규 5개 SCHEDULED)
  - Dispatcher `select_due_job_ids`가 미래 Job을 제외하는지
  - Admin `release_stale_claim`(멱등 + 실제 만료 Claim 해제)

또한 STEP 8-5-15 변경으로 깨진 기존 테스트를 최소한으로 보정했다:

- `test_step8_5_13_session_timeline.py` — `_automatic_settings()` 기본값에
  `market_session_job_enabled=False`를 추가해 기존 레거시 직접 실행
  경로 테스트를 그대로 유지하고, 위임 동작 검증용 신규 테스트
  (`test_automatic_gate_delegates_to_market_session_job_when_enabled`)를
  별도로 추가했다.
- `test_step8_5_14_upbit_ambiguous_resolver_scheduler.py` — Alembic Head가
  `c6d7e8f9a0b1`로 전진했으므로 하드코딩 비교 대신
  `assert_revision_exists(alembic_current_head())`로 완화했다(Head
  Revision을 매 STEP마다 하드코딩하지 않는 관례로 통일).

## 42. 검증 결과 / 남은 과제

```text
Backend pytest: 784 passed / 0 failed / 3 skipped
Frontend Vitest: 94 passed (37 files)
TypeScript: 통과
Lint: 0 errors / 0 warnings
Production Build: 성공
Alembic Head: c6d7e8f9a0b1 (single)
Migration down/up: b5c6d7e8f9a0 ↔ c6d7e8f9a0b1 성공
Backfill: total=25
  (KRX_PREOPEN_RECOVERY=5, KRX_POSTCLOSE_RECOVERY=5,
   KRX_EQUITY_SNAPSHOT=5, KRX_SETTLEMENT=5, KRX_AI_ANALYSIS=5)
```

남은 과제(8-5-16 이후, 이번 STEP에서는 착수하지 않음):
- `KRX_SETTLEMENT` 실제 정산 자동화(현재는 감사용 No-op)
- Admin Job 상세 화면에서 Run 이력(`/{job_id}/runs`) 타임라인 UI
- Reconcile 대상 거래소를 KRX 외로 확장할 경우의 일반화
- Dispatcher 배치 처리 병렬화(현재는 순차 처리)
