# README_AUDIT_TEST.md — 테스트 전체 감사 보고서

| 항목 | 내용 |
|------|------|
| **감사일** | 2026-07-21 |
| **범위** | Backend `tests/` (pytest) · Frontend `frontend` (vitest) · 설정·마커·커버리지 도구 |
| **원칙** | **코드/테스트 수정 없음.** 수집·부분 실행·정적 분석만 |
| **pytest collect** | **441 tests collected** (`pytest --collect-only`) |
| **test 파일** | Backend **162** `test_*.py` · Frontend **24** `*.test.ts(x)` |

---

## 0. 인벤토리 요약

### Backend (pytest)

| 항목 | 값 |
|------|-----|
| 설정 | `pytest.ini` — `pythonpath=src`, `testpaths=tests` |
| 기본 필터 | `-m "not external and not live"` (실외 API·실계좌 제외) |
| 마커 정의 | `unit`, `integration`, `external`, `live` |
| 의존성 | `requirements.txt`: `pytest`, `pytest-asyncio` — **`pytest-cov` / `coverage` 없음** |
| conftest | `tests/conftest.py` — 마커 문서만, **공통 DB fixture 없음** |
| 부분 실행 (본 감사) | STEP65–74 전부 PASS · `test_security_step62`+`api_router`+`step74` PASS |
| 과거 릴리즈 기록 | v1.1.0: STEP65–74 **89 passed** · 전체 스위트 과거 **~340–349 passed** 기록 |

### Frontend (vitest)

| 항목 | 값 |
|------|-----|
| 설정 | `frontend/vitest.config.ts` — jsdom, `src/**/*.test.ts(x)` |
| 스크립트 | `npm test` → `vitest run` |
| 본 감사 실행 | **24 files / 55 tests — 전부 PASS** |
| E2E 도구 | Playwright / Cypress **없음** |
| coverage | vitest coverage 설정 **없음** |

### Mock / 통합 / E2E 힌트 (정적)

| 지표 | 값 |
|------|-----|
| MagicMock/patch 사용 파일 | ~30 / 162 |
| MagicMock 출현 | ~157 |
| `@pytest.mark.integration` 파일 | **1** (`test_step8_ops_smoke.py`, 참조 3) |
| `@pytest.mark.external` / `live` | **0** (필터만 존재) |
| `@pytest.mark.unit` 파일 | 6 (참조 ~29) — 대부분 테스트는 마커 없음 |
| 이름상 e2e | `test_step40_e2e_pipeline.py` (모의) |
| 동시성 패턴 (`threading`/`gather`) | **0** |
| `time.sleep`/`asyncio.sleep` 파일 | 1 |
| skip 관련 파일 | ~5 (kiwoom_rest_adapter, risk_service, step33 일부) |

---

## 1. pytest

### 1.1 구성 품질

| 항목 | 내용 |
|------|------|
| **위치** | `pytest.ini`, `tests/conftest.py`, `requirements.txt` |
| **문제** | 마커 정의는 있으나 ** practically unused**. integration=PostgreSQL이라고 문서화했으나 실제 DB fixture·마크 사용 부재. asyncio 테스트 파일 극소(~3). |
| **영향도** | High |
| **수정방법** | 공통 `db_session` fixture + 진짜 integration 스위트. 모든 신규 테스트에 마커 의무. CI job 분리(unit / integration). |

### 1.2 수집·실행

| 항목 | 내용 |
|------|------|
| **위치** | `tests/**` — **441 collected** |
| **문제** | 전체 스위트 본 감사에서 end-to-end 재실행은 시간상 부분만 수행. 수집은 성공. Starlette TestClient deprecation warning. |
| **영향도** | Low (warning) / Medium (전체 CI 게이트 미확인 시) |
| **수정방법** | CI에서 `pytest -q` 전체 + junit. `httpx`/`starlette` 버전 정리. |

### 1.3 마커 오용

| 항목 | 내용 |
|------|------|
| **위치** | `tests/test_step8_ops_smoke.py` — `@pytest.mark.integration` |
| **문제** | 문서 CMS 파일 읽기 + OpenAPI path + `/health`만. **PostgreSQL 미사용**. |
| **영향도** | High (신뢰성) |
| **수정방법** | `unit`/`smoke`로 재분류하거나 실제 DB 시나리오 추가. |

---

## 2. coverage

| 항목 | 내용 |
|------|------|
| **위치** | `requirements.txt` — pytest-cov **미포함** · venv에 `pytest_cov`/`coverage` **미설치** · 설정 파일 없음 |
| **문제** | 라인/브랜치 커버리지 수치 **측정 불가**. CI coverage gate 없음 (`TOP_100_IMPROVEMENTS`에 과제만 존재). |
| **영향도** | **Critical** (품질 가시성) |
| **수정방법** | `pytest-cov` 추가 · `--cov=stock_platform --cov-report=term-missing --cov-fail-under=…` · PR 게이트. FE는 `@vitest/coverage-v8`. |

### 2.1 추정 커버리지 (정적 휴리스틱, 수치 아님)

| 영역 | 추정 | 근거 |
|------|------|------|
| broker/kiwoom mapper·client | 상대적 높음 | 전용 테스트 다수 |
| auth JWT/signup | 중 | unit 마커 테스트 존재 |
| order/outbox 단건 로직 | 중 | dispatcher/retry 단위 |
| api/v1 라우터 전면 | **낮음** | ~100 라우터 대비 API 테스트 소수 |
| realtime runners | **매우 낮음** | runner 테스트 0 |
| Frontend pages | **거의 0** | page 테스트 0 |

---

## 3. 누락된 테스트

### 3.1 보안 — 무인증 mutate API (Critical)

| 항목 | 내용 |
|------|------|
| **위치** | `step32_router` POSTs · `sync` · `pipelines` · `guarded_pipeline` · `strategy_runtime_switch` 등 (`README_AUDIT_API.md` 46 POST) |
| **문제** | `tests/test_security_step62.py`는 paper-executions/realtime-execution/kill-switch/jobs 등만 검사. **위 Critical 경로 401/403 테스트 없음**. |
| **영향도** | **Critical** |
| **수정방법** | 각 무인증 mutate에 “인증 없으면 401/403” + (수정 후) admin만 200 행렬 테스트. |

### 3.2 API 라우터 전면

| 항목 | 내용 |
|------|------|
| **위치** | `src/stock_platform/api/v1/*` (~98) vs `tests/test_api_*` 소수 |
| **문제** | 서비스 단위는 있어도 HTTP 계약·권한·스키마 검증 누락 다수. |
| **영향도** | High |
| **수정방법** | 라우터별 최소: unauth / auth / validation 스모크 테이블. |

### 3.3 Realtime runners / WS / Outbox claim

| 항목 | 내용 |
|------|------|
| **위치** | `realtime/*_runner.py`, `broker/kiwoom/ws_*`, `order/outbox_repository.claim_batch` |
| **문제** | 메시지 shape·단건 로직만. start/stop·재연결·SKIP LOCKED 경쟁 미검증. |
| **영향도** | High |
| **수정방법** | 가짜 clock + 이중 워커 claim 테스트 · WS reconnect 시나리오. |

### 3.4 Frontend 페이지·플로우

| 항목 | 내용 |
|------|------|
| **위치** | `frontend/src/app/**/page.tsx` (~53) vs vitest 24 (helpers 중심) |
| **문제** | 라우트·폼·권한 가드·API 연동 테스트 없음. |
| **영향도** | High |
| **수정방법** | 핵심 페이지 RTL + Playwright E2E (login→portfolio→order). |

### 3.5 DB Integration

| 항목 | 내용 |
|------|------|
| **위치** | conftest / alembic 적용 DB |
| **문제** | 진짜 PostgreSQL fixture·트랜잭션 롤백 패턴 부재. |
| **영향도** | High |
| **수정방법** | testcontainers 또는 로컬 DB + `@pytest.mark.integration` 전용 job. |

---

## 4. 실패 가능 테스트 (Flaky / Brittle)

| 항목 | 내용 |
|------|------|
| **위치** | skip: `test_kiwoom_rest_adapter.py`, `test_risk_service.py`, `tests/step33/test_*` · sleep 사용 파일 1 · 시간/환경 의존 가능 lifecycle mock 테스트 |
| **문제** | (1) skip된 테스트는 회귀 사각 (2) 환경(경로·OpenAPI prod 비활성)·시간대 의존 시 간헐 실패 가능 (3) MagicMock 과다 시 구현 변경에 brittle |
| **영향도** | Medium |
| **수정방법** | skip 사유 티켓화·제거 또는 xfail+기한. 시간 `freezegun`. mock을 fake/in-memory repo로 치환. |

### 4.1 환경 민감

| 항목 | 내용 |
|------|------|
| **위치** | `test_step8_ops_smoke` OpenAPI — prod에서 docs/`openapi.json` 비활성 시 실패 가능 (`main.py` hide_docs) |
| **문제** | APP_ENV=production으로 돌리면 OpenAPI 테스트 깨질 수 있음. |
| **영향도** | Medium |
| **수정방법** | 테스트용 settings fixture로 non-prod 고정. |

---

## 5. Mock 과다 사용

| 항목 | 내용 |
|------|------|
| **위치** | 상위: `test_step68_user_news` (MagicMock~30) · step72 (~25) · `test_application_lifecycle` (~21) · step71/69/73/telegram/monitoring/step65–67 |
| **문제** | User STEP 서비스 테스트가 repo 전체를 MagicMock → **실제 SQL/FK/트랜잭션 미검증**. “integration” 이름(step74)도 Mock+401 스모크. |
| **영향도** | High |
| **수정방법** | 계층 분리: (a) 순수 단위는 fake (b) repository는 DB integration (c) API는 TestClient+DB. Mock은 외부 HTTP(키움/업비트)에 한정. |

### 5.1 허용되는 Mock

| 영역 | 판정 |
|------|------|
| 외부 브로커 HTTP/WS | Mock/VCR 적절 |
| Ollama/LLM | Mock 적절 |
| 시계열 대량 수집 | Mock/fixture 적절 |

---

## 6. Integration Test 부족

| 항목 | 내용 |
|------|------|
| **위치** | 마커 1파일뿐 · TestClient 파일 ~26 (대부분 앱 기동+권한 스모크) · DB 세션 기반 테스트 사실상 0 |
| **문제** | PostgreSQL·Alembic·실제 커밋/롤백·인덱스/FK 위반을 검증하지 않음. DB 감사에서 지적한 `paper_order` account 부재 등은 테스트로 잡히지 않음. |
| **영향도** | **Critical** (데이터 계층 신뢰) |
| **수정방법** | CI `integration` job: migrate → pytest -m integration. 최소: auth signup/login, paper account+fill, watchlist FK, outbox claim. |

### 이름만 Integration

| 파일 | 실제 |
|------|------|
| `test_step74_user_integration_audit.py` | TestClient 401 + MagicMock 서비스 |
| `test_step8_ops_smoke.py` (@integration) | 파일/OpenAPI/health |

---

## 7. E2E 부족

| 항목 | 내용 |
|------|------|
| **위치** | `tests/test_step40_e2e_pipeline.py` — docstring **“모의 컴포넌트”**, MagicMock 세션 · Frontend Playwright **0** |
| **문제** | 시장→지표→주문→체결→리포트 **실제 E2E 없음**. UI E2E 없음. |
| **영향도** | **High** |
| **수정방법** | (BE) TestClient+DB 시나리오 1개 이상 명명 `e2e_`. (FE) Playwright: login, watchlist, paper order. 모의 story는 `unit`/`story`로 개명. |

---

## 8. Race Condition

| 항목 | 내용 |
|------|------|
| **위치** | `order/outbox_repository.claim_batch` (`FOR UPDATE SKIP LOCKED`) · `outbox_scheduler` · realtime runners start/stop · Kiwoom WS reconnect · kill-switch vs order submit |
| **문제** | 동시성 테스트 **0건**. 단일 스레드 dispatcher/retry만. 이중 워커 중복 claim·신호 유실·킬스위치 레이스 미검증. |
| **영향도** | **High** (프로덕션 장애 유형) |
| **수정방법** | 두 스레드/async task가 동일 outbox claim → 중복 없음 assert. kill-switch 활성 중 submit 거부 경쟁. WS 중복 login 처리. |

---

## 영역별 테스트 밀도 (요약)

| 패키지 | 전용 테스트 밀도 | 판정 |
|--------|------------------|------|
| broker/kiwoom·upbit | 높음 | OK (단위) |
| ai/candidate | 높음 | OK (단위) |
| auth | 중 | JWT/signup 양호, 전 API 행렬 부족 |
| order/trading | 중 | 서비스 양호, claim/동시성 부족 |
| risk_engine | 중 | 단건 OK |
| api/v1 | 낮음 | **보안·계약 테스트 부족** |
| realtime runners | 매우 낮음 | **갭** |
| notification | 낮음 | 갭 |
| frontend pages | 매우 낮음 | **갭** |

---

## 본 감사 실행 결과 (증거)

| 명령 | 결과 |
|------|------|
| `pytest --collect-only` | **441 collected** |
| `pytest` STEP65–74 (10 files) | **PASS** (89개 수준) |
| `pytest` security/api/step74 sample | **PASS** |
| `npm test` (vitest) | **24 files / 55 tests PASS** |
| `import pytest_cov` / `coverage` | **미설치** |

---

## 우선순위 백로그

1. **P0** — `pytest-cov` 도입 + CI fail-under · Critical 무인증 API 401/403 테스트 추가  
2. **P1** — 진짜 DB integration fixture · outbox SKIP LOCKED 동시성 · step40/step8 명명·마커 정정  
3. **P2** — Playwright E2E · realtime runner/WS 테스트 · User STEP Mock→DB 치환  
4. **P3** — 마커 전면 적용 · skip 정리 · Starlette TestClient warning 해소  

---

## 결론

테스트 **양(441 + FE 55)** 은 상당하나, **질적 편향**이 크다: 단위·MagicMock·브로커 매퍼에 치우치고, **커버리지 측정 부재 · DB integration 부재 · 허위 E2E · 보안 회귀 공백 · Race 미검증 · FE 페이지/E2E 부재**가 핵심 부채다.

본 문서는 감사 전용이며 **테스트/코드 변경을 포함하지 않는다.**
