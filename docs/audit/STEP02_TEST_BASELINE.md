# STEP 02 — 테스트 실행 기준선

> 작성일: 2026-07-22  
> 목적: 현재 테스트/빌드 상태를 재현 가능하게 측정하고, 실패를 **환경 문제 vs 코드 문제**로 분류한다.  
> 본 단계에서는 서로 관련 없는 영역을 한꺼번에 수정하지 않는다.

---

## 1. 실행 환경

| 항목 | 값 |
|------|-----|
| OS | Windows 10 (build 26200) |
| Python | 3.12.10 (`.venv`) |
| Node.js | v24.18.0 |
| npm | 11.16.0 |
| FastAPI | 0.139.0 |
| SQLAlchemy | 2.0.51 |
| Alembic | 1.18.5 |
| pytest | 9.1.1 |
| httpx | 0.28.1 |
| pydantic | 2.13.4 |
| Next.js | 16.2.10 |
| React | 19.2.4 |
| Ant Design | ^6.5.1 |
| Vitest | ^4.1.10 |
| Playwright (package.json) | ^1.52.0 |
| Settings 로드 경로 | `STOCK_PLATFORM_ENV_FILE` → cwd → `E:\StockTrading\secrets\stock-platform.env` |

안전 기본(코드/문서 기대): Live off / Mock on.  
단, 로컬 secrets env가 Settings에 주입되면 테스트가 그 값을 읽을 수 있다 (아래 환경 문제 참고).

---

## 2. 실행 명령과 결과 요약

### 2.1 Backend

| 명령 | 결과 |
|------|------|
| `python -m compileall -q src` | **성공** (exit 0) |
| `pytest --collect-only -q` | **501** collected (STEP1) |
| `pytest -q` (기본 marker: `not external and not live`) | **14 failed, 484 passed, 3 skipped** (≈30s) |

### 2.2 Frontend

| 명령 | 결과 |
|------|------|
| `npm ci` | **실패** — `package.json` ↔ `package-lock.json` 불일치 |
| `npm run typecheck` (기존 `node_modules`) | **성공** |
| `npm run lint` | **실패** — 2 errors, 7 warnings |
| `npm run test` (vitest) | **2 failed, 63 passed** (26 files) |
| `npm run build` | **성공** |

> `npm ci` 실패로 CI와 동일한 clean install는 재현되지 않음.  
> typecheck/lint/test/build는 **기존 `frontend/node_modules`** 기준으로 측정.

---

## 3. Backend 실패 분류 (14)

### A. 예외 코드 매핑 불일치 — **코드 문제** (STEP5)

파일: `tests/test_api_exceptions.py` (5 failures)

| 테스트 | 기대 | 실제 |
|--------|------|------|
| `test_external_api_error_sanitizes_secrets` | `EXTERNAL_API_ERROR` | `DOMAIN_ERROR` |
| `test_kiwoom_error_maps_to_502` | `KIWOOM_API_ERROR` | `BROKER_ERROR` |
| `test_upbit_error_maps_to_502` | `UPBIT_API_ERROR` | `BROKER_ERROR` |
| `test_dart_error_maps_to_502` | `DART_API_ERROR` | `BROKER_ERROR` |
| `test_ollama_error_maps_to_502` | `OLLAMA_API_ERROR` | `BROKER_ERROR` |

근거: `exception_handlers.py`가 외부/브로커 예외를 전부 `BROKER_ERROR`(또는 catalog 미등록 시 `DOMAIN_ERROR`)로 접음.  
`error_catalog.py`에도 세분 코드가 없음.  
→ **구현이 테스트를 따라가지 못함** (테스트 약화로 통과 처리 금지).

### B. Auth Fake Repository 계약 불일치 — **코드 문제** (STEP4)

| 테스트 | 증상 |
|--------|------|
| `test_auth_signup.py::test_signup_and_login_by_email` | `FakeRepo`에 `mark_last_login` 없음 |
| `test_auth_signup.py::test_logout_revokes_refresh` | `revoke_refresh(..., reason=)` 시그니처 불일치 |
| `test_user_admin.py` (4건) | `_FakeRepo`에 `_session` 없음 — 서비스가 `_repository._session.flush()` 호출 |

근거: 서비스가 Repository private/`_session`에 의존하거나 Fake가 실계약보다 뒤처짐.

### C. Scheduler 등록 수 하드코딩 — **코드/테스트 드리프트** (STEP9)

- `test_automatic_scheduler.py::test_scheduler_registers_three_jobs`
- 기대 3 jobs, 실제에 `portfolio_equity_snapshot_daily` **추가**

→ 구현 확장 vs 테스트 미갱신. 계약 기반으로 수정 필요(개수 하드코딩 지양).

### D. Kill Switch Guard Fake 불완전 — **코드/테스트** (STEP8)

- `test_persistent_kill_switch_guard.py::test_blocks_buy_when_active`
- `FakeService`에 `active_exchange_scope()` 없음  
- 구현은 `kill_switch_guard.py`에서 scope 조회 후 차단

### E. Security defaults가 로컬 env에 오염 — **환경 문제 (+테스트 격리 부족)** (STEP3)

- `test_step40_recovery_security.py::test_security_defaults`
- `get_settings().kiwoom_live_order_enabled` 가 **True**로 관측되어 실패
- 테스트가 머신 secrets env를 그대로 로드 → **실계좌 키 불필요하나 운영 env 값이 단위 테스트에 유입**

권장: 테스트에서 `get_settings.cache_clear()` + 안전 env monkeypatch / 전용 test settings.

### Skip (3) — 기술부채

1. `test_kiwoom_rest_adapter.py` — 생성자 변경으로 skip  
2–3. `test_risk_service.py` (2) — RiskService API 제거로 skip  

---

## 4. Frontend 실패 분류

### A. `npm ci` 불가 — **환경/의존성 문제** (STEP15)

```
Missing: @playwright/test@1.61.1 from lock file
Missing: playwright@1.61.1 from lock file
Missing: playwright-core@1.61.1 from lock file
Missing: fsevents@2.3.2 from lock file
```

- `package.json`: `@playwright/test: ^1.52.0`
- lockfile 내 next 쪽 참조는 `^1.51.1` 등 — **lock 미동기화**
- CI(`npm ci`)도 동일하게 깨질 가능성 높음

### B. ESLint — **코드 문제** (STEP15/16)

| 등급 | 위치 | 규칙 |
|------|------|------|
| error | `user/profile/page.tsx` | `react-hooks/set-state-in-effect` |
| error | `user/trades/page.tsx` | `react-hooks/set-state-in-effect` |
| warning ×7 | watchlist, AuthGuard, tokenStorage 등 | exhaustive-deps / unused-vars |

### C. Vitest — **코드 문제** (STEP15/16)

| 테스트 | 내용 |
|--------|------|
| `LoginForm.test.tsx` | login 호출 2번째 인자 redirect가 `undefined` (기대 `/admin/dashboard`) |
| `roles.test.ts` | viewer의 `/admin/dashboard` next → 기대 `/user/dashboard`, 실제 `/forbidden` |

typecheck·production build는 통과 → **타입/번들은 건재, 단위 테스트·lint·lock이 기준선 미달**.

---

## 5. 오류 유형별 집계

| 유형 | BE | FE | 비고 |
|------|----|----|------|
| 구현↔테스트 계약 불일치 | 12 | 2 | Auth Fake, 예외코드, scheduler, kill switch, roles/login |
| 환경/설정 오염 | 1 | — | secrets env → Settings |
| 의존성/lock | — | `npm ci` | Playwright lock drift |
| Lint | — | 2 err | setState in effect |
| Skip(기술부채) | 3 | — | 어댑터/RiskService |
| 통과 | 484 | typecheck·build·63 tests | |

실계좌 API 키를 요구하는 실패는 **없음**.

---

## 6. 수정 우선순위 (후속 STEP 매핑)

| 순위 | 항목 | STEP |
|------|------|------|
| P0 | Settings/테스트 격리 (`kiwoom_live` 오염 차단) | STEP3 |
| P0 | Auth Repository 계약 + Fake 정렬, `_session` 제거 | STEP4 |
| P0 | 예외 코드 세분화 (`EXTERNAL/KIWOOM/UPBIT/DART/OLLAMA`) | STEP5 |
| P1 | Kill Switch Fake/`active_exchange_scope` | STEP8 |
| P1 | AutomaticScheduler job 계약 테스트 | STEP9 |
| P1 | `package-lock.json` 동기화 + `npm ci` 복구 | STEP15 |
| P1 | FE lint/vitest 2건 | STEP15–16 |
| P2 | skip된 Kiwoom/Risk 테스트 재작성 | STEP10 / STEP8 |

---

## 7. 재현 절차

```powershell
# Backend
cd D:\Projects\stock-platform
.\.venv\Scripts\python.exe -m compileall -q src
.\.venv\Scripts\python.exe -m pytest -q

# Frontend (현재: node_modules 존재 시)
cd frontend
npm ci          # 현재 실패 예상 — STEP15에서 lock 수정
npm run typecheck
npm run lint
npm run test
npm run build
```

기준선 스냅샷(본 문서 작성 시점):

- Backend: **484 / 501 실행분 중 통과** (14 fail + 3 skip)
- Frontend vitest: **63 / 65 통과**
- Frontend build/typecheck: **통과**
- Frontend lint / npm ci: **실패**

---

## 8. STEP2 완료 판정

| 조건 | 상태 |
|------|------|
| 분석·측정 완료 | ✅ |
| 환경 vs 코드 분류 | ✅ |
| 재현 명령 기록 | ✅ |
| 무관 영역 일괄 수정 안 함 | ✅ |
| 모든 테스트 녹색 | ❌ (의도적으로 수정 보류 — 후속 STEP) |

**STEP2 목표(기준선 확립)는 달성.**  
실패 자체는 후속 단계 입력 데이터이며, 여기서 테스트를 약화하거나 삭제하지 않았다.

---

## 9. 권장 커밋 메시지

```text
docs(step02): record backend and frontend test baseline
```
