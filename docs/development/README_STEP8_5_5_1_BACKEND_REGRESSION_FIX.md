# STEP 8-5-5-1 — Backend 전체 회귀 오류 정리

## 목표

```text
전체 Backend pytest → failed = 0
```

최초 상태: `614 passed / 14 failed / 3 skipped`  
최종 상태: `628 passed / 0 failed / 3 skipped`

## 1. 실패 14건 목록과 분류

| # | 테스트 | 분류 | STEP 8-5-5 연관 | 수정 |
|---|--------|------|-----------------|------|
| 1–6 | `test_position_exit_monitor_step53` exit 조건들 | C Fixture | 간접(Session 계약) | Fixture가 생성자로 Session 주입 |
| 7 | `test_lifecycle_starts_exit_monitor_scheduler` | B+C | 간접(Recovery Scheduler) | APS 수정 + Scheduler start patch |
| 8 | `test_step38_completion::test_exit_monitor_submits_stop_loss` | C Fixture | 간접 | Session 명시 주입 |
| 9 | `test_step8_1_migration_integration` | C Fixture | 무관(Head 하드코딩) | ScriptDirectory Head |
| 10 | `test_step8_2_migration_integration` | C | 무관 | 동일 |
| 11 | `test_step8_3_migration_integration` | C | 무관 | 동일 |
| 12 | `test_step8_4_migration_integration` | C | 무관 | 동일 |
| 13 | `test_telegram_ops_step54::test_lifecycle_starts_telegram_ops_scheduler` | B | 무관(8-5-3 APS) | APS 수정 + patch |
| 14 | `test_trading_guards::test_require_order_safety_runs_kill_then_risk` | C Fixture | 무관(Pause 가드) | `session.scalar→None` |

범주 요약:

- A. STEP 8-5-5 회귀: **0**
- B. 기존 구현 오류: **1** (`recovery_scheduler` next_run_time)
- C. 테스트 Fixture/격리: **13** (Exit Session, Migration Head, MagicMock Pause, Lifecycle patch)
- D. 외부 환경 필수: **0**

## 2. Exit Monitor `_session`

### 원인

운영 코드 `PositionExitMonitorService.__init__(session)`는 `_session`을 올바히 주입한다.
단위 테스트는 `__new__`로 생성자를 우회해 `_session` 없이 `evaluate_and_exit`를 호출했다.
청산 제출 경로에서 `self._session.get(PaperAccount, …)`가 AttributeError를 내고 `submitted=False`가 되었다.

임시 `_session` 속성 추가는 하지 않았다. Fixture가 **생성자 계약**을 따르도록 수정했다.

### 수정

- `tests/test_position_exit_monitor_step53.py` — `PositionExitMonitorService(session, …)`
- `tests/test_step38_completion.py` — 동일

## 3. Migration Head

### 원인

DB `operation.alembic_version`은 `v9c0d1e2f3a4`인데, 테스트가 과거 STEP Revision 문자열과 동등 비교했다.

### 수정

- `tests/migration_helpers.py` — `ScriptDirectory.get_heads()`로 단일 Head 검증
- STEP8-1~4 테스트: Head 일치 + 해당 STEP Revision이 history에 존재 + 스키마 검증 유지

검증: `alembic heads` → `v9c0d1e2f3a4` (single)

## 4. Recovery Scheduler APS

### 원인

`configure()`가 Scheduler `start()` 전에 `aps_job.next_run_time`에 접근했다.
Pending Job에는 해당 속성이 없어 `AttributeError` → Lifecycle Scheduler 기동 실패.

### 수정

`getattr(aps_job, "next_run_time", None)` + trigger `get_next_fire_time` fallback.
Lifecycle 단위 테스트는 `broker_recovery_scheduler.start`를 patch해 격리.

## 5. DB Pause / trading_guards

### 원인

실DB Pause 잔존이 아니라, 단위 테스트 `MagicMock` session의 `scalar()`가 Truthy Mock을 반환해
`is_trading_paused=True`로 오판했다.

### 수정

`session.scalar.return_value = None`으로 Pause 미존재를 명시.

## 6. Runtime Registry 격리

별도 실패는 없었으나 Lifecycle 테스트에서 Recovery Scheduler 기동 실패가 Registry와 무관한
연쇄 실패를 냈다. APS 수정으로 해소.

## 7. Kill Switch 범위

| 범위 | 상태 |
|------|------|
| SYSTEM/GLOBAL | 구현 (`pause_all` 연계) |
| Exchange scope 토큰 | 구현(reason 파싱) |
| USER | 미구현 (별도 Kill Switch 없음) |
| ACCOUNT | Recovery/Conflict Pause 경로로 구현 |
| BROKER | 미구현 |
| MARKET | 미구현 |

## 8. realtime_strategy_runner

- 시세 구독 → MA 신호 → Signal Bus 발행
- **직접 주문 API 호출 없음**
- 인메모리 `_positions`는 `exchange/symbol` 키 (계좌 비포함)
- 주문은 `realtime_execution_runner` + `REALTIME_PAPER_ACCOUNT_ID` Paper 경로
- Scope Registry와 자동 중복 실행 없음
- LIVE Scope 없는 주문·env LIVE 계좌 fallback은 이 Runner에 없음 (Paper 전용 설정)

후속: Scope Registry와 완전 통합은 별도 STEP.

## 9. 변경 파일

운영:

- `src/stock_platform/broker/recovery_scheduler.py`

테스트:

- `tests/test_position_exit_monitor_step53.py`
- `tests/test_step38_completion.py`
- `tests/test_trading_guards.py`
- `tests/test_telegram_ops_step54.py`
- `tests/test_step8_{1,2,3,4}_migration_integration.py`
- `tests/migration_helpers.py` (신규)

추가 Skip: **0** / 삭제 테스트: **0**

## 10. 최종 결과

```text
628 passed, 3 skipped, 0 failed
Frontend Vitest 80/80
TypeScript 통과
Lint 0 errors / Warning 6
Production Build 성공
Migration Head: v9c0d1e2f3a4
```
