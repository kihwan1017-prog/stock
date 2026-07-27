# STEP 8-5-11 — KRX 임시휴장·수능일·특별 거래시간 운영 보완

## 1. 기존 Calendar 운영 구조

```text
큐레이션 공휴일 2024~2028
+ 주말·평일 자동 생성 (TradingCalendarSyncService)
+ 관리자 수동 수정·검증
+ LIVE Fail Closed (VERIFIED only)
```

핵심 구성:

| 구성요소 | 역할 |
|---------|------|
| `operation.trading_calendar_day` | 일자별 거래/세션 |
| `operation.trading_calendar_sync_run` | Sync 이력 |
| `TradingCalendarService` | evaluate / session / LIVE guard |
| `TradingCalendarSyncService` | 생성·Coverage |
| Admin `/api/v1/admin/market-calendar` | 관리 |
| User `/api/v1/user/market-calendar/status` | 조회 |
| Recovery Scheduler | 휴장 시 `SKIPPED_MARKET_CLOSED` |
| Order Guard | `require_live_order_session` |

## 2. 기존 수동 수정 방식

STEP 8-5-7 Admin `PUT /{exchange}/{date}` 가 Calendar Row를 **직접 upsert/update** 했다.
Verify도 Repository `verify_day` 직접 갱신이었다.
이전 값 History·Revision·승인 흐름이 없었다.

## 3. 발견한 고정 거래시간

| 시각 | 위치 | 비고 |
|------|------|------|
| 09:00~15:30 | `calendar_constants.DEFAULT_KRX_*`, `calendar_service` fallback | DB 세션 없을 때만 |
| 08:00 / 개장-30분 | `is_preopen` | 이번 STEP에서 `preopen_at` 우선 |
| 08:30 | Recovery seed cron `30 8 * * mon-fri` | `broker_recovery_kiwoom_preopen` |
| 15:40 | Recovery seed `40 15 * * mon-fri` | `broker_recovery_kiwoom_postclose` |
| 15:40 | `scheduler_equity_snapshot_*` settings | 장후 자산 |
| 16:00~ | `scheduler_ai_hour=16` | AI 후보 |
| 09:00~15:20 | `risk_engine` / `realtime.safety_models` | 안전 기본값 |
| 09:00~15:30 | `scheduler/market_session.py`, `realtime/runtime.py` | 레거시 기본 |

`08:30` 하드코딩 문자열은 코드에 없고, Recovery Cron `30 8` 로 존재한다.

## 4. 변경 요청 모델

테이블: `operation.trading_calendar_change_request`

직접 UPDATE 대신 **요청 → 검증 → 승인 → 적용** 경로만 Calendar를 변경한다.

## 5. 변경 요청 상태

`DRAFT`, `PENDING_REVIEW`, `APPROVED`, `REJECTED`, `APPLIED`, `APPLIED_WITH_SCHEDULER_ERROR`, `SUPERSEDED`, `CANCELLED`, `FAILED`, `CONFLICT`

## 6. 변경 유형

`FULL_DAY_CLOSE`, `OPEN_DAY_OVERRIDE`, `DELAYED_OPEN`, `EARLY_CLOSE`, `SPECIAL_SESSION`, `SESSION_TIME_CHANGE`, `HOLIDAY_NAME_CHANGE`, `SOURCE_CORRECTION`, `VERIFICATION_CHANGE`, `ROLLBACK`

상수: `calendar_change_constants.py`

## 7. 승인 권한

- Admin API `require_admin` + DB Role 재검증(기존 deps)
- 요청자·승인자 기록
- `KRX_CALENDAR_REQUIRE_SEPARATE_APPROVER` (기본 `false`)
  - `true`이면 동일 사용자 승인 거부

## 8. 충돌 검증

동일 날짜 ACTIVE 요청에 대해:

- 동일 `change_type` 중복 → `CONFLICT`
- `FULL_DAY_CLOSE` vs 개장형 변경 충돌 → `CONFLICT`
- 자동 덮어쓰기 금지

## 9. Calendar Revision

`trading_calendar_day.revision` (초기 backfill=1)
Apply 시 +1. `expected_revision` 불일치 → 409 `revision_conflict`

## 10. History

`operation.trading_calendar_day_history`

before/after snapshot, change_request_id, applied_by/at, emergency, source

## 11. 적용 원자성

단일 Session Transaction:

1. 상태 확인 (Idempotent APPLIED)
2. Revision 비교
3. 값 검증
4. History insert
5. Day update + request APPLIED
6. Cache invalidate + Scheduler recompute
7. Commit (API 계층)

적용 중 외부 Broker API 호출 없음.

## 12. 수능일

`is_trading_day=true`, `session_type=DELAYED_OPEN`, open/close 변경.
하드코딩 날짜 없음 — Change Request / Import / 큐레이션으로 관리.

## 13. 임시휴장

`is_trading_day=false`, `CLOSED`, `closure_reason`·`source_reference` 필수, VERIFIED.
주문 Fail Closed, Recovery `SKIPPED_MARKET_CLOSED`, Health는 coverage와 별도 특별 세션 플래그.

## 14. 조기 종료

`EARLY_CLOSE` + close < 정상. `is_regular_session`이 DB close 시각 사용.

## 15. 특별 세션

`SPECIAL_SESSION` + open/close. USER 안내 메시지 생성.

## 16. Scheduler 동적 처리

**방식 A + C 병행**

- A: Apply 후 DateTrigger 동적 Job (`calendar_scheduler_recompute.py`)
- C: 기존 Recovery Cron 유지, 실행 시 Calendar 거래일 검사

## 17. Scheduler 재계산

Apply 후 `recompute_krx_session_jobs`.
실패 시 요청 상태 `APPLIED_WITH_SCHEDULER_ERROR`.

## 18. Runtime 연계

Cache invalidate로 stale session 제거.
`is_regular_session` / Runtime bridge는 최신 evaluate 결과 사용.

## 19. 주문 Guard

`require_live_order_session`이 DB revision과 Cache revision 불일치 시 invalidate 후 Fail Closed.

## 20. Cache

프로세스 메모리 Cache. Key=`exchange+date`, TTL 기본 2초 (`KRX_CALENDAR_CACHE_TTL_SECONDS`).
Redis 미도입. 다중 인스턴스 최대 지연 ≈ TTL.

## 21. Source Metadata

`CURATED_KR_HOLIDAY`, `GENERATED_WEEKDAY`, `KRX_OFFICIAL_NOTICE`, `GOVERNMENT_NOTICE`, `ADMIN_MANUAL`, `EMERGENCY_ADMIN`

USER API에 내부 Source/요청자 미노출.

## 22. Import

```text
python -m stock_platform.operation.krx_calendar_change_cli preview-import --file <json> [--commit]
ops/import_krx_calendar_changes.ps1 -File <path> [-Commit]
```

DRAFT 요청만 생성. 즉시 Calendar 덮어쓰기 금지.

## 23. Rollback

`POST .../{exchange}/{date}/rollback` → ROLLBACK Change Request (History snapshot).
이력 삭제 없음. Apply로 새 Revision.

## 24. 관리자 API

- `GET/POST /change-requests`
- `POST .../submit|approve|reject|apply|cancel`
- `GET .../{ex}/{date}/history`
- `POST .../{ex}/{date}/rollback`
- `GET /change-health`
- 레거시 `PUT` → Change Request 경유 (직접 UPDATE 차단)
- `verify` → `VERIFICATION_CHANGE` 경유

## 25. USER API

기존 `/status` 유지 + `status_message`, `is_special_session`, `closure_reason`(공개 사유).
요청자·승인자·Request ID 미포함.

## 26. Frontend

- Admin `MarketCalendarPanel`: 목록(Revision·특별 표시), 변경 요청 생성/Submit/Approve/Reject/Apply/Cancel, Diff(상세 JSON), 긴급 Modal
- USER Dashboard: API `status_message` 기반 안내

## 27. 운영 Health

Admin Health `krx_trading_calendar`에 pending/conflict/today_special/today_revision 추가.
Public Health에 변경 요청 상세 미노출.

## 28. Audit

`CALENDAR_CHANGE_REQUEST_*`, `CALENDAR_CHANGE_EMERGENCY_APPLIED`, `CALENDAR_DIRECT_UPDATE_REDIRECTED` 등.
민감 인증정보 미기록.

## 29. Migration

- ID: `z3d4e5f6a7b8`
- Revises: `y2c3d4e5f6a7`
- 테이블: change_request, day_history
- Day 컬럼: revision, active_change_request_id, last_changed_at
- 기존 VERIFIED 유지, revision=1 backfill

## 30. 운영 Script

- `ops/check_krx_special_sessions.ps1`
- `ops/import_krx_calendar_changes.ps1`
- `python -m stock_platform.operation.krx_calendar_change_cli`

## 31. 변경 파일 (주요)

- `database/alembic/versions/z3d4e5f6a7b8_krx_calendar_change_request.py`
- `src/stock_platform/operation/calendar_change_*.py`
- `calendar_cache.py`, `calendar_scheduler_recompute.py`, `krx_calendar_change_cli.py`
- `api/v1/admin_market_calendar.py`, `calendar_service.py`, `health_service.py`, `settings.py`
- `frontend/.../MarketCalendarPanel.tsx`, `adminApi.ts`, dashboard
- `tests/test_step8_5_11_krx_special_session.py`
- `ops/*.ps1`, `.env.example`

## 32. 테스트 결과

```text
Backend pytest: 705 passed / 0 failed / 3 skipped
Frontend Vitest: 84/84
TypeScript: 통과
Lint: 0 errors / 0 warnings
Production Build: 성공
Alembic down/up (z3d4e5f6a7b8 ↔ y2c3d4e5f6a7): 성공
Alembic Head: z3d4e5f6a7b8 (single head)
```

(신규 STEP 테스트: `tests/test_step8_5_11_krx_special_session.py` 14 passed)

## 33. 운영 적용

```powershell
# Migration
alembic upgrade head

# 점검
python -m stock_platform.operation.krx_calendar_change_cli pending
.\ops\check_krx_special_sessions.ps1

# Import (Apply 아님)
.\ops\import_krx_calendar_changes.ps1 -File .\path\changes.json -Commit
```

환경 변수:

```text
KRX_CALENDAR_REQUIRE_SEPARATE_APPROVER=false
KRX_CALENDAR_CACHE_TTL_SECONDS=2.0
```

## 34. 남은 문제

- Recovery 기본 Cron(08:30/15:40)은 유지. 수능일·조기종료는 동적 Job으로 보완하나, Cron Job 자체 disable 정책은 운영자가 Admin에서 조정 가능.
- risk/realtime safety 모델의 고정 09:00~15:20는 Calendar와 완전 단일화되지 않음 (후속).
- Redis NOTIFY 미도입 — 다중 인스턴스 Cache 지연 ≈ TTL.
- 복잡한 CSV 업로드 UI 미구현 (CLI Import만).
