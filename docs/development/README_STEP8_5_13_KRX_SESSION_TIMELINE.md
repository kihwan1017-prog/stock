# STEP 8-5-13 — KRX Trading Session Timeline (동적 Phase·Cron Fallback)

## 1. 배경 — 고정 시각 문제

기존에는 09:00/15:30 정규장 시각과 08:30/15:20/15:40/16:00·16:30 등 여러
고정 Cron/상수가 흩어져 있어, KRX 지연개장·조기종료·수능일 등 특별
거래시간 변경 요청이 반영돼도 Recovery·Snapshot·AI 분석·주문 게이트가
실제 장 시각과 어긋나는 문제가 있었다.

## 2. 목표

Calendar(거래일·특별 세션) → **Session Timeline**(Phase 경계 시각들) →
주문 게이트/Recovery/Snapshot/AI 실행까지 **하나의 동적 소스**로
연결하고, 기존 고정 Cron은 동적 Job이 없거나 실패했을 때만 동작하는
**Fallback Safety Net**으로 격하한다.

## 3. TradingSessionPhase

`operation/session_timeline.py`

| Phase | 의미 |
|---|---|
| `NON_TRADING_DAY` | 휴장일 |
| `PREOPEN` | 장전 준비 (Preopen 시각 ~ 개장) |
| `OPEN` | 정규장 운영 중 (신규 진입 허용) |
| `EXIT_ONLY` | 신규 진입 마감 ~ 장마감 (매도·위험축소만) |
| `CLOSED` | 장마감 ~ Post-close 이전 |
| `POST_CLOSE` | Post-close Recovery 이후 |
| `CALENDAR_UNAVAILABLE` | Calendar 미검증/Stale/충돌 — Fail Closed |

## 4. TradingSessionTimeline 필드

`preopen_start_at, order_entry_start_at, regular_open_at,
new_entry_cutoff_at, regular_close_at, post_close_start_at,
recovery_preopen_at, recovery_postclose_at, snapshot_at,
settlement_at, analysis_at` — 모두 `market_date` 기준 Calendar가 결정한
`regular_open_at`/`regular_close_at`에 Offset(설정값)을 더해 계산한다.

## 5. Offset 설정 (`SessionOffsetConfig` / `.env`)

| 설정 | 기본값 | 의미 |
|---|---|---|
| `krx_preopen_minutes_before_open` | 30 | Preopen 시작 |
| `krx_recovery_preopen_minutes_before_open` | 30 | Preopen Recovery |
| `krx_new_entry_cutoff_minutes_before_close` | 10 | 신규 진입 마감 |
| `krx_recovery_postclose_minutes_after_close` | 10 | Postclose Recovery |
| `krx_snapshot_minutes_after_close` | 10 | 자산 Snapshot |
| `krx_settlement_minutes_after_close` | 20 | 정산 |
| `krx_ai_analysis_minutes_after_close` | 30 | AI 분석 |
| `krx_cron_fallback_early_tolerance_minutes` | 5 | Fallback 조기 허용 |
| `krx_cron_fallback_late_tolerance_minutes` | 60 | Fallback 지연 허용 |

정규 거래일(09:00~15:30) 기준 결과값: Preopen 08:30, Cutoff 15:20,
Postclose Recovery 15:40, Snapshot 15:40, 정산 15:50, **AI 분석 16:00**.

## 6. Phase 경계 판정 (`phase_at`)

Preopen → Open(Cutoff 전) → Exit Only(Cutoff~Close) → Closed →
Post Close 순으로 우선순위 판정. Calendar `reason_code`가
`CALENDAR_UNAVAILABLE_REASONS`에 속하면 항상 `CALENDAR_UNAVAILABLE`.

## 7. 신규 진입/위험축소 판정

- `allows_new_entry` — `OPEN`일 때만 `True`
- `allows_risk_reducing` — `OPEN` 또는 `EXIT_ONLY`
- `allows_any_order(is_risk_reducing=...)` — BUY는 OPEN만, SELL/EXIT은
  OPEN·EXIT_ONLY 모두 허용

## 8. `resolve_krx_timeline` — 공통 진입점

`Cache(TTL=krx_calendar_cache_ttl_seconds) + Resolver` 조합. UPBIT는
Timeline 미적용(24시간 always-open stub)이며 KRX만 실제 Calendar를
조회한다. Calendar Day가 바뀌면(`revision` 변경) `invalidate_timeline_cache`
로 즉시 재계산.

## 9. Phase 변경 Audit

동일 Phase가 유지되는 동안은 기록하지 않고, 실제 전환 시에만
`KRX_SESSION_PHASE_CHANGED` Audit 이벤트를 남긴다(프로세스 최초 관측은
제외).

## 10. 주문 게이트 — `realtime/safety_guard.py`

기존 `trading_start_time`/`trading_end_time` 고정 비교를 제거하고
`resolve_krx_timeline` + `allows_any_order`로 대체. Timeline 조회
실패 시 `CALENDAR_UNAVAILABLE`로 **Fail Closed**(주문 차단).
`trading_start_time`/`trading_end_time` 필드는 하위호환용으로 남아있으나
KRX LIVE 판정에는 더 이상 사용하지 않는다.

## 11. Risk Engine — `risk_engine/rules.py`

거래시간 규칙이 동일한 Timeline Phase 판정을 사용해 BUY는 OPEN 외
차단, SELL은 EXIT_ONLY까지 허용한다.

## 12. Calendar Service 연계

`operation/calendar_service.py`에 `resolve_timeline()` 헬퍼를 추가해
`TradingCalendarService.evaluate()` 결과(Decision)를 Timeline으로
변환한다. `is_regular_session_exit_only()` / 유저 상태 조회 API 모두
이 경로를 재사용한다.

## 13. Broker Recovery Cron Fallback

`broker/recovery_scheduler_service.py::krx_cron_fallback_gate` —
08:30(Preopen)/15:40(Postclose) 고정 Cron 실행 직전 Timeline과 비교해
`SKIPPED_TOO_EARLY`/`SKIPPED_TOO_LATE`/`SKIPPED_NON_TRADING_DAY`/
`SKIPPED_CALENDAR_UNAVAILABLE` 중 하나면 스킵하고 사유를 반환한다.
판정 로직은 `krx_cron_fallback_timing()`(순수 함수)로 추출해 아래
Snapshot/AI 게이트와 공유한다.

## 14. Snapshot/AI 고정 Cron → Timeline Fallback 게이트 (본 STEP 추가분)

`scheduler/automatic.py::_krx_session_cron_gate` — `portfolio_equity_snapshot`
/`ai_orchestration` 실행 직전 다음을 순서대로 판정:

1. `scheduler_exchange_code != "KRX"` 또는 `krx_cron_fallback_enabled=False`
   → 게이트 미적용(그대로 실행)
2. Timeline 해석 실패 → 기존 Calendar 게이트가 없던 Job이므로
   Fail Closed 대신 그대로 실행(운영 연속성 우선)
3. 비거래일/Calendar 미검증 → `SKIPPED_NON_TRADING_DAY` /
   `SKIPPED_CALENDAR_UNAVAILABLE`
4. `krx_cron_fallback_timing()` 결과가 `TOO_EARLY`/`TOO_LATE` →
   `SKIPPED_TOO_EARLY`/`SKIPPED_TOO_LATE`
5. 같은 날 목표 시각 이후 `SUCCESS` 실행 이력(`JobRunRepository`)이
   있으면 → `SKIPPED_ALREADY_EXECUTED`
6. 위 조건에 모두 해당하지 않으면 `None` 반환 → 고정 Cron이 정상 실행
   (Fallback Safety Net 역할)

`gate_timeline_field`로 Snapshot은 `snapshot_at`, AI는 `analysis_at`을
비교 대상으로 사용한다. **동적 SNAPSHOT/AI_ANALYSIS Job(§16)이
Primary**이며, 이 고정 Cron(기본 15:40/16:30)은 동적 Job 미등록·미기동
(Scheduler 재기동, 등록 실패 등) 상황의 Fallback이다.

## 15. Admin 수동 즉시실행은 게이트 예외

`run_job_now()`로 관리자가 명시적으로 Snapshot/AI를 즉시 실행하면
`force=True`가 전달되어 `_krx_session_cron_gate`를 건너뛴다 — 관리자가
의도적으로 요청한 실행을 시각 불일치로 막지 않기 위함.

## 16. 동적 SNAPSHOT/AI_ANALYSIS Job — `calendar_scheduler_recompute`

Calendar 변경(신규 등록/변경요청 승인/Rollback) 시
`recompute_krx_session_jobs()`가 해당 일자 Timeline의 7개 경계
(`PREOPEN_RECOVERY, MARKET_OPEN, NEW_ENTRY_CUTOFF, MARKET_CLOSE,
POST_CLOSE_RECOVERY, SNAPSHOT, AI_ANALYSIS`)를 계산해 1회성
`DateTrigger` Job으로 `broker_recovery_scheduler`(APScheduler)에
등록한다. 이미 지난 시각은 `SKIPPED_ALREADY_PASSED`로 메타만 기록.
동일 날짜의 이전 Revision Job은 삭제 대신 `SUPERSEDED`로 표시한다.

**운영 주의**: `_DYNAMIC_JOBS` 레지스트리는 프로세스 메모리 내 딕셔너리로,
DB에 영속화되지 않는다. Scheduler 프로세스가 재시작되면 목록이
초기화되므로(단, 이미 예약된 `DateTrigger`가 APScheduler 자체
persist job store를 쓰지 않는 한 재기동 시 재등록 필요), Calendar
변경 발생 시 또는 Admin "Job 재계산" 버튼으로 재생성해야 한다. 다중
Worker 환경에서는 이 레지스트리가 인스턴스별로 분리된다는 점도 알고
있어야 한다(§30 남은 문제 참고).

## 17. Job 분류 — SESSION_DEPENDENT vs DATE_DEPENDENT/TIME_OF_DAY_ONLY

`SESSION_DEPENDENT_JOB_NAMES = {"portfolio_equity_snapshot",
"ai_orchestration"}` — 위 §14 게이트 적용 대상.

`candidate_screening`(16:10)·`position_planning`(17:00)은 특정 장
이벤트가 아니라 "매 평일 지정 시각" 정책(TIME_OF_DAY_ONLY)이므로
`day_of_week=mon-fri` 조건만 유지하고 Timeline 게이트를 적용하지
않는다 — 코드 주석(`automatic.py` 모듈 docstring)으로 명시.

## 18. Admin API

`api/v1/admin_market_calendar.py`

| Method | Path | 설명 |
|---|---|---|
| GET | `/{exchange}/{date}/timeline` | Timeline 전체 필드 + `current_phase` + `next_transition_at/phase` |
| GET | `/{exchange}/{date}/jobs` | 해당 일자 동적 Job 목록(`list_dynamic_jobs` 필터) |
| POST | `/{exchange}/{date}/recompute-jobs` | Timeline 기준 동적 Job 강제 재계산(Audit 기록) |

## 19. User API 확장

`/user/market-calendar/status` 응답에 `phase, new_entry_cutoff_at,
next_transition_at, next_transition_phase, is_delayed_open,
is_early_close, new_entry_allowed, risk_reducing_allowed` 필드 추가.
기존 `is_trading_day, regular_open_at, regular_close_at,
calendar_available, status_message` 등은 유지.

## 20. Frontend Admin — Session Timeline 패널

`frontend/src/features/admin/market/MarketCalendarPanel.tsx` 상단에
`Session Timeline (STEP 8-5-13)` Card 추가:

- 날짜 선택(`DatePicker`) + 새로고침 + **Job 재계산**(POST) 버튼
- `Descriptions`로 Current Phase(Tag)/Calendar Revision/Session
  Type/Reason Code/Pre-open Recovery/Regular Open/New Entry
  Cutoff/Regular Close/Post-close Recovery/Snapshot/AI Analysis/
  다음 전환 표시
- Regular Open/Close가 09:00/15:30 기본값과 다르면
  `TimelineTimeField`가 강조 표시("기본값과 다름")
- 동적 Job 목록 Table(Job Type/상태/실행 예정/Rev) + 변경 요청 이력
  섹션으로 이동하는 링크
- Force OPEN/강제 주문 버튼 **없음**(요구사항)

`adminApi.ts` 추가 함수: `getAdminMarketCalendarTimeline(exchange,
date)`, `getAdminMarketCalendarJobs(exchange, date)`,
`recomputeAdminMarketCalendarJobs(exchange, date)`.

## 21. Frontend User — 공용 Phase 메시지

`frontend/src/features/user/market/sessionPhaseMessages.ts` — Phase별
한글 라벨/설명/Alert Tone을 매핑하는 순수 함수 모듈(시간 계산 없음).
`useMarketSessionStatus.ts` Hook이 `/user/market-calendar/status`를
조회해 `status` + `phaseMessage`를 함께 반환하고,
`MarketSessionBanner.tsx`가 이를 Ant Design `Alert`로 렌더링한다
(특별세션/지연개장/조기종료 Tag 포함).

## 22. Frontend User — 적용 화면

`(user)/user/dashboard/page.tsx`(기존 개별 Calendar Alert 로직을
`MarketSessionBanner`로 교체), `(user)/user/strategies/page.tsx`
상단에 배너 추가. `trades` 페이지는 `orders`로의 redirect-only
페이지라 배너 대상에서 제외.

## 23. 하나의 소스 원칙

Dashboard·전략 화면 모두 `useMarketSessionStatus` 한 Hook만
호출하고, 시간 비교 로직을 중복 구현하지 않는다. Admin 패널은 별도로
`getAdminMarketCalendarTimeline`을 사용하지만 동일한 Backend
`TradingSessionTimeline.to_dict()` 스키마를 공유한다.

## 24. 테스트 — Backend

`tests/test_step8_5_13_session_timeline.py` (32 tests): Alembic 단일
head, Resolver 정규/지연개장/조기종료/휴일/Calendar 미검증·Stale,
Phase 경계, 신규진입/위험축소 판정, next_transition, Reason Code
매핑, Risk Engine 거래시간 규칙, Safety Guard BUY/SELL 차단·허용,
Upbit 미영향, Cron Fallback(조기/지연/기실행/비활성/Unknown Job),
Calendar Service 연계, Timeline Cache 무효화, `krx_cron_fallback_timing`
경계값, Automatic Scheduler 게이트(비거래일/Calendar 미검증) 등.

## 25. 테스트 — Frontend

`sessionPhaseMessages.test.ts`(신규, 7 tests) — 알려진 7개 Phase 매핑,
Unknown Phase 안전 기본값, null/undefined 처리, `formatSessionPhaseLabel`
/`sessionPhaseAlertType`/`isNewEntryBlockedPhase` 개별 동작.
`marketCalendar.test.ts`(기존) — Admin Calendar API 존재 및 USER
동기화 API 부재 검증, 변경 없음.

## 26. Migration

없음(Timeline은 순수 계산 — 신규 컬럼 불필요). Alembic Head 유지:
`a4b5c6d7e8f9`.

## 27. 설정 파일

`.env.example`에 STEP 8-5-13 Offset/Fallback 설정 이미 반영됨
(`krx_preopen_minutes_before_open` 등 §5 표 전체 + `krx_dynamic_session_jobs_enabled`,
`paper_stock_follow_krx_calendar`). 이번 STEP에서 신규 설정 추가
없음(기존 값 재사용).

## 28. 변경 파일 (본 STEP — Frontend + Cron Gate + 문서)

주요 Backend:
- `operation/session_timeline.py`, `calendar_service.py`, `calendar_scheduler_recompute.py`
- `calendar_change_constants.py` — SNAPSHOT/AI_ANALYSIS/NEW_ENTRY_CUTOFF Job Type 추가
- `realtime/safety_guard.py`, `realtime/session_scheduler.py` — Timeline Phase 동기화·동적 DateTrigger
- `risk_engine/rules.py`, `risk_engine/order_guard.py`
- `broker/recovery_scheduler_service.py`, `scheduler/automatic.py`
- `api/v1/admin_market_calendar.py`
- `.env.example`, `common/settings.py`
- `tests/test_step8_5_13_session_timeline.py`

Frontend:
- `adminApi.ts`, `MarketCalendarPanel.tsx` — Session Timeline 패널
- `features/user/market/sessionPhaseMessages.ts`, `useMarketSessionStatus.ts`,
  `MarketSessionBanner.tsx`, dashboard/strategies 배너
- `docs/development/README_STEP8_5_13_KRX_SESSION_TIMELINE.md`(이 문서),
  `docs/development/README.md`, `docs/README.md` 인덱스 갱신

## 29. 테스트 결과

```text
Backend pytest: 754 passed / 0 failed / 3 skipped
Frontend Vitest: 91 passed (35 files)
TypeScript (tsc --noEmit): 통과
ESLint: 0 errors / 0 warnings
Production Build: 성공
Alembic Head: a4b5c6d7e8f9 (single head)
Migration: 없음
```

신규 Backend: `tests/test_step8_5_13_session_timeline.py`
Frontend: `sessionPhaseMessages.test.ts` 포함. 기존 Skip 3개 유지, 신규 Skip 없음.

## 30. 남은 문제 / 후속 과제

- Snapshot/AI 고정 Cron 스킵 사유(`SKIPPED_TOO_EARLY` 등)가 현재
  `logger.info`로만 기록되고 `job_run_history` 테이블에는 저장되지
  않아 Admin Job 이력 API/화면에서 스킵 사유를 조회할 수 없음(로그
  Aggregator 필요). Recovery Cron Fallback(§13)도 동일한 제약.
- `calendar_scheduler_recompute._DYNAMIC_JOBS`가 프로세스 메모리
  전역 상태라 다중 Worker/재기동 환경에서 목록이 일관되지 않을 수
  있음(§16) — DB 영속화는 범위 밖으로 후속 STEP 후보.
- Admin Timeline 패널에 "Fallback Cron 상태" 별도 표시는 Backend가
  Fallback 스킵 이력을 API로 노출하지 않아 미포함(§30-1과 동일 원인).
- `trades` 페이지는 `orders`로의 redirect뿐이라 배너 미적용(§22).

## 31. 운영 체크리스트

1. 특별 거래일 변경요청 승인 시 Admin "Job 재계산" 버튼으로 동적
   Job을 즉시 갱신(Scheduler 프로세스가 재시작되지 않았다면 Calendar
   승인 경로에서 자동 recompute도 함께 실행됨).
2. Scheduler 워커(`scripts/run_scheduler.py`) 재기동 후에는 당일
   동적 Job이 비어 있을 수 있으므로 Admin Timeline 패널에서 확인 후
   필요 시 재계산.
3. `krx_cron_fallback_enabled=false`로 설정하면 Snapshot/AI/Recovery
   고정 Cron이 Timeline 무관하게 항상 실행됨(비상 시 임시 조치).

## 32. 고정 시각 인벤토리 — 제거/유지 조사 (§F)

| 고정 시각 | 위치 | 상태 | 비고 |
|---|---|---|---|
| **09:00** | 정규장 개장 기본값 | **유지(기본값)** | Calendar가 지연개장 지정 시 Timeline이 실제 개장시각으로 대체. Frontend는 09:00과 다르면 강조 표시 |
| **08:30** | `broker_recovery_kiwoom_preopen` DB 시드 Cron | **유지 + Fallback 격하** | Timeline `recovery_preopen_at`(개장 30분 전) 동적 Job이 Primary, 고정 08:30 Cron은 `krx_cron_fallback_gate`로 게이트(§13) |
| **15:20** | 신규진입 마감(Cutoff) 기본값 | **유지(파생값, Cron 아님)** | `krx_new_entry_cutoff_minutes_before_close=10` → 15:30 기준 15:20. 별도 Cron 없이 Timeline 필드로만 존재 |
| **15:30** | 정규장 종료 기본값 | **유지(기본값)** | 조기종료 지정 시 Timeline이 실제 종료시각 반영 |
| **15:40** | `portfolio_equity_snapshot_daily` 고정 Cron + `broker_recovery_kiwoom_postclose` DB 시드 Cron | **유지 + Fallback 격하** | Snapshot 동적 Job(`snapshot_at`=Close+10)이 Primary, 고정 15:40은 §14/§13 게이트 적용 |
| **16:00** | AI 분석 Timeline 파생값(`analysis_at`=Close+30) | **신규 Primary 목표 시각** | 동적 AI_ANALYSIS Job이 이 시각에 실행 — 이번 STEP에서 Snapshot/AI 게이트의 기준점으로 확정 |
| **16:30** | `ai_orchestration_daily` 고정 Cron(`scheduler_ai_hour/minute`) | **유지 + Fallback 격하** | §14 게이트: 16:00 동적 Job이 이미 성공했으면 `SKIPPED_ALREADY_EXECUTED`, 게이트 통과 시에만 16:30에 실행 |
| **17:00** | `position_planning_daily` 고정 Cron | **유지(TIME_OF_DAY_ONLY, 게이트 미적용)** | 장 이벤트 종속이 아닌 정책성 고정 시각 — §17 |
| **16:10** | `candidate_screening_daily` 고정 Cron | **유지(TIME_OF_DAY_ONLY, 게이트 미적용)** | 상동 |

## 33. 결론

Calendar(단일 진실 소스) → Session Timeline(Phase·경계 시각 계산) →
{주문 게이트, Risk Engine, Recovery Cron, Snapshot/AI Cron, Admin/User
Frontend}까지 하나의 계산 경로로 일원화했다. 기존 고정 Cron/상수는
삭제하지 않고 **Fallback Safety Net**으로 남겨, 동적 Job 등록 실패나
Scheduler 재기동 같은 예외 상황에서도 최소 1회 실행이 보장되도록
했다.
