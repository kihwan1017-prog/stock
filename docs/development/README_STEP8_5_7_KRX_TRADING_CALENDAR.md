# STEP 8-5-7 — KRX 거래일 캘린더 실데이터 적용 및 WEEKDAY_FALLBACK 제거

## 1. 기존 Calendar 구조

- `operation.trading_calendar_day` + `TradingCalendarService`
- DB miss 시 평일 → `WEEKDAY_FALLBACK` (거래일로 간주)
- 사용처: Recovery Scheduler(Kiwoom), Realtime Session, Guarded Pipeline, Admin evaluate API

## 2. WEEKDAY_FALLBACK 문제점

공휴일·대체공휴일·연말 휴장·임시 휴장을 평일로 오판 → LIVE Recovery/주문이 휴장일에 실행될 수 있음.

## 3. 조사한 데이터 원천

| 원천 | 평가 |
|------|------|
| 키움 API 거래일 | 프로젝트에 안정적 엔드포인트 미확인 |
| HTML 스크래핑 | 금지 |
| 큐레이션 공휴일 + 주말/평일 생성 | 채택 |
| ADMIN 수동 등록 | 임시휴장·특별세션 보완 |

## 4. 선택한 데이터 원천과 이유

**CURATED_KR_HOLIDAY (2024–2028) + GENERATED_WEEKDAY/WEEKEND**.

공식 스크래핑 없이 재현 가능. Sync 후 VERIFIED 적재. 임시 휴장은 ADMIN 수동.

## 5. DB 구조

기존 `operation.trading_calendar_day` 확장 (중복 테이블 미생성):

- session_type, 세션 시각, timezone, closure_reason
- source_type/reference/updated_at
- verified_status/by/at

신규 `operation.trading_calendar_sync_run`

## 6. 거래일 상태와 Session 유형

- VERIFIED / UNVERIFIED / STALE / MISSING / CONFLICT
- CLOSED / REGULAR / DELAYED_OPEN / EARLY_CLOSE / SPECIAL_SESSION

## 7. 데이터 적재 범위

- 과거: Sync `past_years` (기본 1)
- 미래: `KRX_CALENDAR_REQUIRED_FUTURE_DAYS` (기본 60 **달력일**)

## 8. TradingCalendarService

DB VERIFIED만 LIVE 허용. Asia/Seoul. `require_live_order_session`, Coverage, USER status.

## 9. Fallback 제거·제한

기본 `KRX_CALENDAR_ALLOW_WEEKDAY_FALLBACK=false`. true여도 `live_allowed=false` + 경고 Audit.

## 10. Recovery Scheduler 연계

- 휴장 → `SKIPPED_MARKET_CLOSED`
- Calendar 미적재/미검증 → `SKIPPED_CALENDAR_UNAVAILABLE`

## 11. 주문 안전 검사

Kiwoom+KRX LIVE: Calendar Fail Closed. Paper/Upbit 영향 없음. 리스크 감소(청산) 주문은 calendar block 제외.

## 12. Runtime 연계

KRX 세션: 휴장/Calendar 장애 시 Skip. Upbit·Paper 무영향.

## 13–14. Calendar Sync / Scheduler

`TradingCalendarSyncService`, Jobs: `krx_trading_calendar_sync`, `krx_trading_calendar_coverage_check`. 분산 Lock scope `KRX_CALENDAR/SYNC`.

## 15–17. API / Frontend / Health

- ADMIN `/api/v1/admin/market-calendar*`
- USER `/api/v1/user/market-calendar/status`
- Admin Scheduler 화면 Calendar 패널, User Dashboard 장 상태
- SystemHealth `krx_trading_calendar` — Coverage 부족 시 DEGRADED

## 18. 감사 로그

Sync 시작/완료/실패, Fallback 사용, Coverage 부족, LIVE 차단, 수동 수정/검증.

## 19. Migration

`x1b2c3d4e5f6` ← `w0a1b2c3d4e5`

## 20. 초기 적재

```powershell
alembic upgrade head
.\ops\sync_krx_trading_calendar.ps1
```

## 21. 변경 파일

(calendar_* / admin_market_calendar / order_guard / recovery_scheduler / lifecycle / frontend / ops / tests / docs)

## 22. 테스트 결과

```text
신규 STEP 단위: 15+ passed (calendar service / sync / scheduler classify)
Backend pytest: 658 passed / 0 failed / 3 skipped
Frontend Vitest: 83/83
TypeScript: 통과 (next build)
Lint: 0 errors / 기존 Warning 6
Production Build: 성공
Alembic down/up: w0a1b2c3d4e5 ↔ x1b2c3d4e5f6 성공
Alembic Head: x1b2c3d4e5f6 (single head)
```

## 23. 운영 적용

Migration → Sync → Coverage 확인 → 서버 재시작 → Scheduler/Health 확인

## 24. 기존 Lint Warning

6건 유지 목표

## 25. 남은 문제

- 임시휴장·수능일은 수동 등록 필요
- 큐레이션 연도 주기적 갱신 필요
- 고정 Cron(08:30/15:40) + Session Type 메타 (당일 동적 Job은 후속)
