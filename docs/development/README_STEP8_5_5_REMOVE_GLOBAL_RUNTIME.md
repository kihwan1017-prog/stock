# STEP 8-5-5 — 레거시 전역 Runtime 슬롯 완전 제거

## 1. 기존 Runtime 구조

STEP 8-3에서 `scope_key`와 `_runtimes` dict를 추가했지만, 실제 호출은
레거시 전역 슬롯(`_runtime` / `_strategy`)과 기본 `KRX` 단일 로드에 의존했다.

## 2. 발견된 전역 Runtime 목록

| 위치 | 심볼 | 역할 |
|------|------|------|
| `strategy_deployment/runtime_manager.py` | `_runtime`, `_strategy` | 전역 단일 전략 슬롯 |
| `runtime_manager.initialize(market_code=KRX)` | Startup | 기본 KRX 단일 로드 |
| `reload_scheduler` | unscoped `reload()` | 기본 시장만 재로드 |
| `switch_service` | 직접 `_runtime` 쓰기 | Scope 무시 교체 |
| `dynamic_strategy_adapter` | `get_strategy()` | Scope 없는 평가 |
| `api/v1/strategy_runtime.py` | `/reload?market_code=KRX` | 기본 KRX API |

(참고: `broker_recovery_manager`, `realtime_strategy_runner` 등은 다른 도메인
싱글톤이며 전략 Scope Registry와 별개.)

## 3. 전역 Runtime 문제점

- 동일 공개 전략을 여러 계좌가 써도 상태 혼입
- Recovery/Kill Switch가 전역에 영향을 줄 위험
- 계좌 없는 SYSTEM 전략이 기본 실행될 수 있음

## 4. 선택한 Scope 모델

`StrategyRuntimeScope` (불변):

- `user_id`
- `account_kind` (`PAPER` | `USER_BROKER`)
- `account_id`
- `strategy_id`
- `strategy_version`
- `market_type`
- `broker_code`

## 5. Scope Key 구성

```text
user:{id}|paper:{id}|sid:{id}|ver:{version}|type:{MARKET}|broker:{CODE}
user:{id}|uba:{id}|sid:{id}|ver:{version}|type:{MARKET}|broker:{CODE}
```

계좌번호·Secret 원문 미포함.

## 6. Runtime Registry

`DynamicStrategyRuntimeManager._runtimes: dict[scope_key, ScopedRuntimeEntry]`

API: create/reload/pause/resume/stop, account/user/strategy 단위 조회,
`shutdown_all()`. Scope 없는 `get_strategy`/`get_runtime`은
`RuntimeScopeRequiredError`.

## 7. Runtime 생성 조건

활성 `account_strategy_link` + 활성 전략 정의 + 계좌 소유권/활성 +
(LIVE) Vault Credential VERIFIED + Recovery Pause/Kill Switch 확인.

## 8. Startup 초기화

`bootstrap_scoped_runtimes()` — 링크별 Scope 생성. **기본 KRX 단일 Runtime 미생성.**
한 Scope 실패는 다른 Scope를 중단하지 않음.

## 9. Recovery 연계

`recover_account` 시작 시 해당 계좌 Runtime Pause.
성공 시 Resume, 실패/Manual Review 시 Pause 유지.

## 10. Credential Vault 연계

LIVE 링크 Bootstrap 시 `assert_live_order_allowed`. 원문 Credential은 Runtime에 보관하지 않음.

## 11. Kill Switch 연계

시스템 Kill Switch Activate → `pause_all(reason=kill_switch)`.
계좌 Pause는 Recovery/Conflict 경로로 격리.

## 12. Scheduler 연계

`StrategyRuntimeReloadScheduler`는 등록된 전체 Scope만 `reload_all_scopes`.
기본 KRX `reload()` 제거.

## 13. 주문 실행

주문 가드·Outbox는 기존 `user_broker_account_id` / Paper `account_id` 격리 유지.
Runtime Scope의 계좌와 불일치 시 주문 경로에서 Recovery Pause로 차단.

## 14. Exit Monitor

포지션 `account_id`별 임계값·주문. Recovery Pause Paper 계좌는 Exit 스킵.

## 15. Realtime

시장 데이터 Runner는 공유 가능. 동적 전략 Adapter는 `scope_key` 필수.
전략 State는 Scope Entry에만 보관.

## 16. Paper Runtime

`account_kind=PAPER`, `broker_code=PAPER`로 LIVE와 분리.

## 17. USER API

- `GET /api/v1/user/runtimes`
- `GET /api/v1/user/runtimes/{scope_key}`
- `GET /api/v1/user/accounts/{account_id}/runtimes`

## 18. ADMIN API

- `GET /api/v1/admin/runtimes`
- `GET /api/v1/admin/runtimes/{scope_key}`
- `POST .../pause|resume|reload|stop`
- 레거시 `/strategy-runtime/status|reload`는 Registry 집계/전체 Reload로 전환

## 19. Frontend

- ADMIN `/admin/trading` — `AdminRuntimePanel`
- USER `/user/strategies` — 내 Scope Runtime 목록

## 20. 제거한 레거시 코드

- `_runtime` / `_strategy` 전역 슬롯
- Scope 없는 get fallback
- Startup 기본 KRX 단일 initialize
- Switch의 전역 슬롯 직접 쓰기
- Reload Scheduler의 unscoped KRX reload

## 21. 남은 호환 코드

- `/api/v1/strategy-runtime/*` 경로 유지 (동작은 Scope Registry)
- `status()["runtime"]=None` 필드 유지 (전역 슬롯 없음 표시)
- `realtime_strategy_runner` (고정 MA Runner) — 별도 도메인, 동적 Registry와 분리

## 22. DB 변경 및 Migration

**Migration 없음** — 메모리 Registry + 기존 `account_strategy_link` /
`strategy_deployment` / recovery account state 재사용.

선행 head: `v9c0d1e2f3a4`

## 23. 감사 로그

`STRATEGY_RUNTIME_CREATED|CREATE_FAILED|PAUSE|RESUME|RELOAD|STOP`,
Kill Switch Activate 시 `runtimes_paused` 기록.

## 24. 변경 파일

- `runtime_scope.py`, `runtime_models.py`, `runtime_manager.py`
- `runtime_loader.py`, `runtime_bootstrap.py`, `reload_scheduler.py`
- `switch_service.py`, `lifecycle.py`, `recovery_runtime.py`
- `api/v1/admin_runtimes.py`, `user_runtimes.py`, `strategy_runtime.py`
- Frontend Admin/User Runtime UI
- `tests/test_step8_5_5_scoped_runtime.py`

## 25. 전체 테스트 결과

STEP 8-5-5 직후: `614 passed / 14 failed / 3 skipped`  
→ **STEP 8-5-5-1**에서 회귀 정리: `628 passed / 0 failed / 3 skipped`

상세: [README_STEP8_5_5_1_BACKEND_REGRESSION_FIX.md](README_STEP8_5_5_1_BACKEND_REGRESSION_FIX.md)

## 26. 운영 적용 방법

Migration 없음. 배포 후 API 재시작:

```powershell
# API 프로세스 재시작 — Startup이 account_strategy_link 기준으로 Scope Runtime bootstrap
```

활성 계좌-전략 연결이 없으면 Runtime 0개로 기동 (정상).

## 27. 기존 Lint Warning 상태

기존 6건 유지 목표.

## 28. 남은 문제

- KRX Calendar `WEEKDAY_FALLBACK`
- Upbit `Retry-After` 정밀 파싱
- 다중 인스턴스 분산 Lock 강화 (STEP 8-5-6)
- 기존 Lint Warning 6건
- `realtime_strategy_runner` 고정 전략과 Scope Registry 완전 통합은 후속 과제
