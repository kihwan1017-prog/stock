# STEP 8-5-8 — Upbit API Rate Limit 및 Retry-After 정밀 처리

## 1. 기존 Upbit Retry 구조

| 경로 | 이전 동작 |
|------|-----------|
| `broker/upbit/market/client.py` | tenacity + sliding window, Remaining-Req 로그만 |
| `broker/upbit/private_client.py` | sliding window, 418/429 단순 raise |
| `broker/upbit/order_client.py` | limiter/retry/header 파싱 없음 |
| `common/rate_limit.py` | 앱 **인바운드** API 보호용 (업비트 무관) |

## 2. 발견한 Retry 구현 목록

- Quotation: tenacity exponential (유지, 418은 Ban 예외로 재시도 제외)
- Private: AsyncSlidingWindowRateLimiter
- Order: 없음 → `execute_upbit_http_with_policy` 통합
- Recovery / Conflict Refresh / Credential Verify: 개별 try/except → 공통 예외·Coordinator 연계

## 3. 업비트 Header 구조

지원: `Remaining-Req`, `Retry-After`, `Date`

## 4. Remaining-Req 파싱

`UpbitRateLimitHeaderParser` — `group=…; min=…; sec=…` 키-값 정규식, 순서·공백 비의존. 잘못된 숫자는 `parse_ok=False`.

## 5. Retry-After 파싱

- 초(정수/소수), HTTP-date
- 음수 → 0, 상한 `UPBIT_RETRY_AFTER_MAX_SECONDS`(기본 300)
- `Date` Header 우선 기준 시각, timezone-aware

## 6. 오류 분류

`UpbitApiError` 계층: Authentication / Permission / InvalidRequest / InsufficientFunds / OrderNotFound / RateLimit / BanOrBlock(418) / TemporaryUnavailable / Network / AmbiguousOrderResult

## 7. Endpoint·작업 분류

`PUBLIC_MARKET_DATA`, `PRIVATE_ACCOUNT_READ`, `ORDER_CREATE`, `ORDER_CANCEL`, `ORDER_QUERY`, `EXECUTION_QUERY`, `RECOVERY_QUERY`, `CREDENTIAL_VERIFY`

Group: `default` / `market` / `order` / `account` (응답 Header group 동적 반영)

## 8. Retry 정책

`UpbitRetryPolicyResolver`: 조회=RETRY(최대 Attempt), 418=PAUSE_ACCOUNT, 주문 생성 429=DEFER(재전송 금지), 주문 생성/취소 불명확=REFRESH_REMOTE_STATE

## 9. 주문 생성 안전성

업비트 멱등 키 미적용 전제. Timeout/5xx/연결 오류 → `UpbitAmbiguousOrderResultError`, 동일 POST 자동 재전송 금지. Recovery·주문 조회로 판별.

## 10. 주문 취소 안전성

불명확 시 `REFRESH_REMOTE_STATE` — 외부 상태 조회 후 정규화. 무한 재시도 없음.

## 11. Backoff 계산

우선순위: Retry-After → Remaining-Req 임박 → 지수 Backoff + bounded jitter

## 12. Rate Limit Coordinator

`UpbitRateLimitCoordinator` — 프로세스 메모리 초단기 throttle + 긴 Cooldown/418만 PostgreSQL persist (Redis 없음)

## 13. 계좌·Group 격리

Key: `credential_scope(UBA|PUBLIC) + uba_id + endpoint_group`. USER A 429가 USER B를 막지 않음. Public market scope 분리.

## 14. PostgreSQL Cooldown

테이블 `operation.upbit_api_rate_limit_state` — Scope+Group Unique, Secret 미저장

## 15. HTTP 429

Cooldown 설정, 조회는 Attempt 내 Retry, 주문 생성은 즉시 재전송 금지·DEFER

## 16. HTTP 418

`BAN_OR_BLOCKED` — 해당 계좌 Pause/Manual Review, 타 계좌 영향 없음, 짧은 재시도 금지

## 17. HTTP 5xx

조회: 제한 Retry. 주문: Ambiguous → 원격 조회/Recovery. Kill Switch가 아닌 계좌·Broker 범위 보호

## 18. Recovery 연계

429 → adapter `DEFERRED_RATE_LIMIT` + `next_retry_at` → account state는 CHECK 호환 `FAILED`로 정규화. 긴 Retry-After는 Lock을 길게 점유하지 않고 DEFER 후 해제. 418 → `MANUAL_REVIEW`

## 19. Scheduler 연계

`next_retry_reason=DEFERRED_RATE_LIMIT` 시 지수 Backoff로 `next_retry_at` 덮어쓰지 않음. 418은 auto_retry 중단

## 20. Conflict Refresh

429/418/503 → `RecoveryConflictError` + Admin HTTP 429/423/503, Conflict 오해결 방지

## 21. Credential Verify

Rate Limit/418을 `credential_invalid`로 저장하지 않음. Admin HTTP 429/423 매핑

## 22. 관리자 API

- `GET /api/v1/admin/upbit/rate-limits`
- `GET /api/v1/admin/upbit/rate-limits/{uba_id}`
- `POST /api/v1/admin/upbit/rate-limits/{uba_id}/recheck` (강제 해제 없음)

## 23. USER API

- `GET /api/v1/user/upbit/rate-limits/{uba_id}` 요약
- `GET /api/v1/user/accounts` 에 `upbit_api_status` 등 요약 필드

## 24. Frontend

`/admin/upbit` Rate Limit 패널 실조회·Recheck. USER 계좌 목록에 요청 제한/관리자 확인 Tag·Alert

## 25. 운영 Health

Monitoring overview `broker.upbit.rate_limit` — cooldown/418/longest/last_rate_limit_at

## 26. 감사 로그

`ADMIN_UPBIT_RATE_LIMIT_RECHECK`, HTTP 정책 경로 audit_hook (정상 요청마다 기록하지 않음). Secret/JWT 미기록

## 27. 설정

`.env.example` — `UPBIT_RETRY_*`, `UPBIT_RATE_LIMIT_*`, `UPBIT_418_*`. Settings validation 포함

## 28. Migration

- ID: `y2c3d4e5f6a7` (revises `x1b2c3d4e5f6`)
- `operation.upbit_api_rate_limit_state`
- `broker_recovery_account_state.next_retry_reason`, `rate_limit_endpoint_group`

## 29. 변경 파일 (요약)

- `src/stock_platform/broker/upbit/rate_limit_*.py`, `exceptions.py`
- `order_client.py`, `private_client.py`, `market/client.py`
- `recovery_adapters/upbit.py`, `recovery_runtime.py`, `recovery_scheduler_service.py`, `recovery_conflict_service.py`
- `api/v1/admin_upbit_rate_limits.py`, router, conflicts, credentials, user_accounts
- `operation/monitoring_snapshot.py`, settings, `.env.example`
- Frontend admin/user upbit·accounts
- Migration `y2c3d4e5f6a7_*`
- `tests/test_step8_5_8_upbit_rate_limit.py`

## 30. 테스트 결과

- Backend pytest: **681 passed / 0 failed / 3 skipped** (신규 STEP 테스트 포함)
- Frontend Vitest: **83/83**
- TypeScript: 통과
- Lint: **0 errors / Warning 6** (기존과 동일)
- Production Build: 성공
- Alembic: `y2c3d4e5f6a7` single head, down/up 검증 완료

## 31. 운영 적용

```text
alembic upgrade head
# 필요 시 .env에 UPBIT_RETRY_* / COORDINATOR 반영 후 API·Scheduler 재시작
```

## 32. 기존 Lint Warning 상태

기존 Warning 6건 유지 목표 (완화 금지)

## 33. 남은 문제

- 업비트 주문 멱등 키 미지원 전제 — Ambiguous는 Recovery 의존
- 메모리 Coordinator는 인스턴스 로컬; 긴 Cooldown만 PG 공유
- Quotation tenacity와 Coordinator 이중 계층 (의도: 단기 재시도 + 공용 Cooldown)
