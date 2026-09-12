# stock-platform 프로젝트 인수 감사 보고서 (코드 기준)

- 작성일: 2026-07-28
- 브랜치: `release/v1.1.0` (HEAD: `3554ef8 "STEP11 completed"`)
- 원칙: README/자체 감사 문서(README_AUDIT_*.md, PROJECT_FINAL_AUDIT.md 등)는 검증되지 않은 과거 주장으로 취급하고, **실제 소스코드/마이그레이션/테스트 실행 결과만을 근거**로 작성했습니다.
- 방법: 백엔드/프론트엔드/DB/테스트/STEP 이력을 5개 하위 조사로 나눠 병렬 분석 후 종합.
- 본 작업에서 코드/파일/Git 상태는 전혀 변경하지 않았습니다 (읽기 전용 조사만 수행).

---

## 0. 먼저 정정해야 할 전제: "Cursor AI가 STEP1~11까지 했다"는 브리핑은 사실과 다릅니다

Git 로그(`bd3bc9d` 2026-07-12 ~ `3554ef8` 2026-07-28)와 저장소 내 STEP 표기를 전수 조사한 결과:

- **"STEP1~11"로 묶이는 독립된 초기 단계는 존재하지 않습니다.** 저장소에는 서로 다른 3가지 STEP 체계가 섞여 있습니다.
  1. **메인 빌드 시퀀스 (STEP1~STEP75+)**: `docs/archive/steps/README_STEP16.md` ~ `README_STEP75.md`, 루트의 `README_STEP56~64.md` 등. 브로커 연동, 리스크 엔진, 스케줄러, AI 후보 파이프라인, 프론트엔드 admin/user 콘솔, 보안 강화까지 포괄하는 실제 개발 이력입니다. `e84cbf5`(2026-07-20, v1.0.0 GA)와 `1efd7e7`(2026-07-21, v1.1.0, "STEP65-75")로 두 차례 릴리스됐습니다.
  2. **21단계 감사 워크스루**: `docs/audit/STEP01_PROJECT_ANALYSIS.md` ~ `STEP21_FINAL.md` (2026-07-19~22 작성). 예컨대 `STEP11_UPBIT.md`는 "이미 만들어진" Upbit 브로커 연동을 검증하는 문서입니다.
  3. **하위 기능군의 서브스텝**: `docs/development/README_STEP8_1~8_9C4` (브로커/계좌 격리), `docs/ai/STEP11_1~11_13` (AI 프로바이더/후보 파이프라인). 즉 "STEP11"이라는 라벨은 메인 시퀀스의 11번째 서브 단계(AI 프로바이더 아키텍처)를 가리키는 경우가 많습니다.
- **가장 결정적인 사실**: 오늘 날짜(2026-07-28)의 최신 커밋 `3554ef8 "STEP11 completed"`는 **v1.1.0(STEP65-75) 릴리스 위에 얹힌, 사후 감사/보완 커밋**입니다(1,128개 파일, ~19.7만 라인 변경). 내용은 CI 워크플로우 추가(`.github/workflows/ci.yml`), `Dockerfile`, 5개 신규 감사 리포트, `docs/ai/STEP11_*` 문서 세트, STEP8/9 서브페이즈 마이그레이션·테스트 보강입니다. 이 커밋이 참조하는 `README_ISSUES.md`는 이전 감사(`PROJECT_FINAL_AUDIT.md`, 2026-07-19)의 **51/100 NO-GO 점수**를 완화하기 위한 후속 조치이고, `README_AUDIT_01.md`는 Alembic head가 **STEP73**이라고 명시합니다.
- 소스코드 자체에도 STEP 3~73번대 주석/독스트링/파일명이 다수 박혀 있어(`ai/providers/registry.py:1` `"""STEP 11-1 — Provider Registry."""` 등), "STEP11"이 프로젝트 초입이 아니라는 것은 코드 레벨에서도 확인됩니다.

**결론**: 이 프로젝트는 "이제 막 STEP11까지 온" 초기 단계가 아니라, **이미 v1.0.0 GA / v1.1.0을 릴리스했고, 오늘 사후 보완 커밋까지 얹은 상당히 성숙한 상태**입니다. 브리핑을 그대로 믿고 "기초부터 이어받는다"는 전제로 접근하면 안 됩니다. (자세한 내용은 10번 항목 참고)

---

## 1. 프로젝트 전체 구조

### 백엔드 (`src/stock_platform`, 약 895개 .py 파일)
- 진입점: `src/stock_platform/api/main.py:146`의 `create_app()` (FastAPI 팩토리). `application_lifecycle`(`api/lifecycle.py`), `RequestContextMiddleware`, `SecurityHeadersMiddleware`, CORS, 예외 핸들러(`api/exception_handlers.py`)를 조립하고, 단일 집계 라우터 `api_router`(`api/router.py`)를 등록합니다.
- `api/router.py`(~510줄)는 `api/v1/` 아래 **148개 라우터 모듈**을 도메인별로 묶어 `_ROUTER_GROUPS`(347~508행)에 등록하는 순수 배선 파일입니다. 485행에는 `# step32_router: deprecated 무인증 paper fill 우회 — 등록 해제 (P0)`라는 명시적 폐기 주석이 있어, 과거 보안 취약 라우트를 의도적으로 제거한 흔적이 남아 있습니다.
- 레이어링은 도메인 모듈마다 일관됩니다: `entities.py`(도메인) → `models.py`(영속/pydantic) → `repository.py`(DB 접근) → `service.py`(비즈니스 로직) → `api/v1/*.py`(HTTP). `order/`, `settlement/` 등에서 확인.
- DB 레이어는 `database/base.py`, `engine.py`, `session.py`, `mixins.py`로 중앙화. Alembic 실제 체인은 `database/alembic/versions`에 **108개** 마이그레이션.
- 도메인 모듈: ai, api, auth, backtest, broker/brokers, collectors, common, database, disclosure, indicators, markets, news, notification, operation/operations, order, performance, portfolio, position, realtime, risk/risk_engine, scheduler, screener, settlement, strategy/strategy_deployment, trading.

### 프론트엔드 (`frontend/src`, Next.js 16 App Router)
- 3개 라우트 그룹: `app/(admin)/admin/*`(54개 페이지), `app/(user)/user/*`(약 40개), `app/(auth)/*`(로그인/가입/온보딩). 각 그룹 `layout.tsx`가 `AuthGuard`+`MainLayout`으로 감싸고, `(user)/layout.tsx:29-36`은 ADMIN 역할 사용자를 admin 대시보드로 강제 리다이렉트 — 실질적 RBAC 게이팅입니다.
- 페이지(`page.tsx`)는 5~20줄의 얇은 래퍼이고, 실제 로직/데이터패칭은 `features/{admin,user}/**`에 위치.
- 상태관리: 전역은 `zustand`(테마/레이아웃/인증 스토어)뿐이고, 서버 상태는 전부 `@tanstack/react-query`.
- API 클라이언트: `lib/api/apiClient.ts`(주 axios 인스턴스, 토큰 첨부/401 리프레시 큐잉), `lib/api/rootClient.ts`(prefix 없는 `/health`, `/version`용), `features/auth/api/authApi.ts`의 `authBareClient`(리프레시 루프 회피용) — 총 3개의 axios 인스턴스가 존재.

### DB
- **Alembic 마이그레이션 트리가 실질적으로 2개 존재하나, 실사용은 1개뿐입니다.** `alembic.ini:2`가 `script_location = database/alembic`로 고정되어 있어 **`database/alembic/versions/`(108개)만 실제 체인**입니다. 최상위 `alembic/versions/`(5개 파일)는 `README.md`에 스스로 "Deprecated — 적용 금지"라고 명시된 죽은 사본이며, `docs/migration-overlays/`에 참고용으로 중복 보관됩니다.
- 스키마는 Postgres 스키마 단위로 분리(`auth, market, trading, strategy, operation, news, disclosure, ai, backtest, broker, common, notification` — `bootstrap.py:10-23`).
- 시드/뷰/함수 디렉터리(`database/seeds`, `views`, `functions`, `migrations`)는 **전부 빈 디렉터리**입니다 (파일 0개).

### 테스트
- `tests/`에 256개 파일, `def test_` 1,396건, 실제 pytest 수집 결과 1,412개 테스트. 프론트엔드는 vitest 40개 파일 + Playwright e2e 스모크 1개(`smoke.spec.ts`).

---

## 2. 구현 완료 기능

이 프로젝트는 "일부만 만들어진 프로토타입"이 아니라 **실제로 DB/브로커와 연결된 상당히 넓은 범위의 기능이 동작**합니다.

- **브로커 연동**: `broker/kiwoom/*`(클라이언트, WS 클라이언트, 계좌 동기화, 체결 파서), `broker/upbit/*`(주문 클라이언트, 레이트리밋, 모호 주문 해소) — 실제 API 클라이언트 코드로 스텁이 아닙니다.
- **주문/체결**: `order/outbox_*`(아웃박스 패턴: dispatcher/worker/펜싱), `order/execution_service.py`, `order/state_machine.py`.
- **리스크 관리**: `risk_engine/*`(킬스위치, 일일 손실 모니터, 포지션 한도) — 73개 파일에서 임포트되는 핵심 인프라. `risk/`(주문 단위 사이징/평가, `RiskManagementEngine`) — 별개 목적으로 둘 다 실사용.
- **정산**: `settlement/*`(entities, service, runner, broker_adapter, 라이브/페이퍼 어댑터).
- **AI 파이프라인**: `ai/candidate_assessment`, `candidate_consensus`, `candidate_lifecycle`, `candidate_promotion`, `candidate_recommendation_queue`, `document_analysis`, `execution`, `market_analysis`, `prompt`, `providers`(Claude/OpenAI/Gemini/Ollama/OpenAI호환 다중 프로바이더 레지스트리), `review` — 서비스 파일이 1,000줄대로 큰 편이지만 실제 로직으로 채워져 있음.
- **운영/스케줄러**: `operation/`(캘린더, 잡 스케줄링, 대시보드, 감사, 설정) — 103개 파일에서 참조.
- **프론트엔드 admin/user 콘솔**: 계좌, 배치, 대시보드, 공시, 회원, 뉴스, 주문, 포트폴리오, 리스크, 역할, 스케줄러, 전략, 트레이딩 페이지가 대부분 `useQuery`/`useMutation`으로 실제 API와 연결됨(94개 page.tsx 중 61개가 직접 쿼리 훅 호출, 나머지도 대부분 `features/*` 뷰 컴포넌트를 통해 연결).
- **인증**: `AuthGuard` + 역할 기반 리다이렉트, 토큰 리프레시 큐잉(단일 flight), `localStorage`/`sessionStorage` 선택적 영속화.
- **CI/CD**: `.github/workflows/ci.yml`이 실제 Postgres 서비스 컨테이너를 띄우고 `alembic upgrade head` → `pytest --cov=stock_platform --cov-fail-under=25` → 프론트 `test/typecheck/lint/build`를 수행 — 오늘자 커밋에서 신규 추가됨.

---

## 3. 미완료 기능 (실제 코드/TODO 기준)

프론트엔드 TODO는 대부분 "백엔드 엔드포인트 부재"를 정직하게 명시하고 있고, 실제로 백엔드에 해당 라우트가 없음을 교차 검증했습니다.

| 위치 | 내용 |
|---|---|
| `app/(user)/user/strategies/page.tsx:1003,1009` | 전략 배포 삭제 기능 비활성 — `DELETE /api/v1/strategy-deployments/{id}` 백엔드 라우트 없음 (확인됨) |
| `app/(user)/user/strategies/page.tsx:1277,1282` | 포트폴리오 최적화 비활성 — `POST /api/v1/portfolio-optimize` 없음 (확인됨) |
| `app/(user)/user/auto-trading/page.tsx:363` | 킬스위치 활성/비활성 버튼 주석 처리 (admin 전용 배선 대기) |
| `app/(user)/user/auto-trading/page.tsx:528` | 자동매매 스케줄 CRUD 스텁 — `GET/POST/DELETE /api/v1/user/auto-trading/schedules` 없음 (확인됨) |
| `app/(admin)/admin/indicators/page.tsx:51` | 지표 파라미터 설정 CRUD API 없음 |
| `app/(user)/user/news/page.tsx:259,503` | AI 뉴스 요약 "준비 중" 플레이스홀더 (뉴스 목록 자체는 실동작) |
| `app/(user)/user/trading/page.tsx:863` | 실시간 시세 SSE/WS 스트리밍 미구현, 폴링으로 대체 중 |

백엔드 쪽은 TODO/FIXME/XXX/HACK 마커가 **전무**했습니다(895개 파일 grep 결과 0건). 이는 규모 대비 이례적으로 깨끗한데, 핸드오프 전에 정리됐거나 원래 습관적으로 남기지 않았을 가능성이 있습니다 — 미완료 여부를 주석에 의존해 파악할 수 없다는 뜻이므로 신규 라우트/도메인 부재 여부는 라우터 등록 목록(`api/router.py`)과 프론트 TODO 교차검증으로 파악해야 합니다.

또한 `ai/providers/mock_provider.py`의 `MockAIProvider`가 정식 등록된 선택 가능 프로바이더입니다(`registry.py:106-113`, `provider_id == "mock"`). 기능 결함은 아니지만, 운영 설정이 잘못되면 AI 응답이 조용히 목(mock)으로 나갈 수 있어 프로덕션 설정 값을 확인할 필요가 있습니다.

---

## 4. 기술부채

- **함수 내부 지연 임포트 581건**: `grep -rn "^\s{4,}from stock_platform"` 결과. 예: `ai/candidate_assessment/service.py:975`, `ai/execution/runner.py:565,1058` 등. 전형적으로 순환 임포트를 피하기 위한 우회 패턴이며, 이 정도 규모(581건)는 구조적 냄새로 봐야 합니다.
- **광범위한 `except Exception`**: 429건, 특정 지점이 아니라 전반에 퍼져 있어 예외 처리 정책이 일관되지 않습니다.
- **1,000줄 이상 대형 파일 다수**: `ai/candidate_promotion/service.py`(1,571), `operation/ops_monitoring/service.py`(1,449), `ai/candidate_recommendation_queue/service.py`(1,401), `trading/upbit_live_ops_inspection_service.py`(1,394), `ai/candidate_consensus/service.py`(1,211), `ai/candidate_assessment/service.py`(1,191), `ai/candidate_lifecycle/service.py`(1,117), `broker/recovery_conflict_service.py`(1,101) 등 — 특히 `ai/*` 서비스 파일들이 일관되게 크며, god-class 후보로 리팩터링 검토 대상입니다.
- **프론트 API 클라이언트 파일 비대화**: `features/admin/api/adminApi.ts`(3,718줄), `features/user/api/userApi.ts`(2,371줄) — 모든 API 호출과 타입이 파일 하나에 몰려 있고, 리소스별 모듈 관례가 없습니다. 게다가 어드민 쪽은 `getJson/postJson/...` 헬퍼를 쓰는데 유저 쪽(171개 호출부)은 `apiClient.get/post`를 직접 호출하는 등 두 파일이 같은 문제를 다른 방식으로 풀고 있습니다.
- **백엔드 에러 응답 계약 불일치(간접 증거)**: 프론트 `lib/api/apiError.ts`가 FastAPI `detail`, `{code,message,request_id}`, `{ok:false,error:{...}}` 세 가지 형태를 모두 방어적으로 처리 — 이는 백엔드 엔드포인트마다 에러 응답 포맷이 통일돼 있지 않다는 정황 증거입니다.
- **DB: FK `ondelete` 정책 비일관**: 총 144개 FK 중 `ondelete='CASCADE'`는 10개뿐, 나머지는 기본 `NO ACTION` — 캐스케이드 삭제 정책이 도메인 전략이 아니라 케이스별로 결정된 것으로 보입니다.
- **DB: soft-delete 공용 mixin 부재**: `database/mixins.py`에는 `TimestampMixin`만 존재하고 `deleted_at`은 4개 마이그레이션·26개 소스 파일에 개별 구현 — 새 테이블 추가 시 개발자가 매번 기억해서 추가해야 하는 구조.
- **STEP 넘버링이 파일명/주석에 광범위하게 박혀 있음**: 신규 합류자 입장에서 "STEP" 문자열이 코드/테스트/문서 전반에 흩어져 있어(`STEP3~73`), 이를 별도 정리 문서 없이 코드만 보고 전체 이력을 재구성하기 어렵습니다.

---

## 5. 중복 코드

### 백엔드
- **`broker/` vs `brokers/`**: `brokers/`(복수형, 11개 파일)는 `brokers/__init__.py`가 스스로 "시세 REST 호환 래퍼(STEP6), 실구현은 `broker.*.market`으로 이전"이라고 명시. 이 패키지를 임포트하는 곳은 자기 자신뿐(`src/` 전체에서 외부 참조 0건) — **죽은 코드**.
- **`risk/` vs `risk_engine/`**: 이름은 비슷하지만 **둘 다 실사용, 중복이 아님**. `risk/`는 주문 단위 사이징(`RiskManagementEngine`, `RiskService`), `risk_engine/`은 계좌 단위 실시간 트레이딩 가드(킬스위치, 일일 손실, 포지션 한도) — 각각 다른 73/여러 파일에서 임포트됨. 단, `risk/legacy_gate.py`의 `InMemoryRiskGate`는 자체 문서화된 **레거시**(구 `/risk/check` 전용)입니다.
- **`operation/` vs `operations/`**: `operation/`(단수, 103개 파일에서 참조 — 실사용)과 `operations/rehearsal/`(라이브 전환 리허설 CLI 툴, `scripts/run_operation_rehearsal.py`에서만 호출) — 이름은 헷갈리지만 둘 다 실존하는 별개 목적 코드이며 중복은 아닙니다.
- **`trading/execution_entities.py`의 `execution` 테이블**(실제 체결) vs **`ai/execution/entities.py`의 `execution_request/run/result/event`**(AI 비용 추적) — 같은 단어를 다른 도메인에서 사용, 혼동 소지.

### 프론트엔드
- **axios 인스턴스 3개**(`apiClient`, `rootClient`, `authBareClient`) — 의도된 분리지만 baseURL/timeout 설정을 3곳에서 동기화해야 함.
- **`JsonValue` 타입 3중 정의**: `types/common.ts:15-21`(정식 재귀 타입, 그러나 저장소 전체에서 **0회 참조**돼 사실상 죽은 코드), `features/admin/api/adminApi.ts:6`과 `features/user/api/userApi.ts:6`에 각각 `export type JsonValue = unknown;`로 재정의.
- **요청 래퍼 컨벤션 불일치**: adminApi.ts는 `getJson/postJson/...` 헬퍼, userApi.ts는 `apiClient` 직접 호출 — 같은 문제를 다르게 해결.

---

## 6. 사용되지 않는 코드

- `src/stock_platform/brokers/`(패키지 전체) — 자기 참조 외 임포트 0건, 죽은 코드로 확정.
- `src/stock_platform/risk/legacy_gate.py`의 `InMemoryRiskGate` — 자체 문서화된 폐기 예정, 구 엔드포인트 전용.
- `src/stock_platform/position/calculator.py`, `position/models.py` — grep 결과 `src/` 내 다른 곳에서 임포트되지 않음. 유일하게 참조하는 곳은 폐기 대상 테스트(`tests/step32/test_position.py`)뿐.
- `src/stock_platform/indicators/simple.py`(sma/ema/rsi) — `src/` 전체에서 임포트되지 않는 고아 코드. 실제 지표 파이프라인은 `indicators_engine`/`indicator_service`.
- `src/stock_platform/screener/service.py`의 `filter_candidates()` — 독스트링에 스스로 "레거시 IndicatorValue 필터(STEP34 호환)"라고 명시. 실사용 경로는 별도 `evaluate()` 메서드.
- 프론트: `features/dashboard/components/DashboardWelcome.tsx`, `FoundationChecklist.tsx`, `SystemStatusPlaceholder.tsx` — 어디서도 임포트되지 않는 초기 스캐폴딩 잔재("STEP41 Foundation" 하드코딩 문구 포함), 실제 admin/user 대시보드로 대체됨.
- 프론트: `hooks/useHydrated.ts` — export만 되고 참조처 없음.
- 프론트: `types/common.ts` 전체 — 저장소 어디서도 임포트되지 않음.
- **테스트**: `tests/step32/`, `tests/step33/`, `tests/step34/`(총 7개 파일) — 위에서 나열한 죽은 프로덕션 코드(`legacy_gate`, `position.calculator`, `indicators.simple`, 구 `screener.filter_candidates`)만 테스트하며, `step33`은 파일 2개 전부 `pytest.mark.skip` 처리돼 실행조차 안 됩니다. 삭제해도 실제 커버리지 손실이 없다는 것이 조사 결과입니다.
- **DB**: `database/seeds/`, `views/`, `functions/`, `migrations/` 디렉터리 — 전부 빈 폴더. 문서상 언급되더라도 실제로는 아무 파일도 없음. 최상위 `alembic/versions/`(5개 파일)도 스스로 "적용 금지"라고 명시된 비활성 사본.
- **DB 스키마**: `bootstrap.py`가 선언한 12개 스키마 중 `broker`, `common` 2개는 실제로 어떤 마이그레이션에서도 사용되지 않음(브로커 관련 테이블은 전부 `trading` 스키마에 생성됨) — 문서(코드)와 실제 구현의 괴리.

---

## 7. FE / BE 불일치

전반적으로는 정합성이 나쁘지 않은 편입니다(별도 조사 결론). 다만:

- 프론트 base URL(`NEXT_PUBLIC_API_BASE_URL` + `NEXT_PUBLIC_API_PREFIX=/api/v1`)과 백엔드 라우터 prefix(`orders.py:22 prefix="/api/v1/orders"` 등)는 표본 검증 결과 일치.
- `/health`, `/version`은 `/api/v1` 밖에 있고, 프론트는 이를 위해 별도 `rootClient`를 정확히 사용 중 — 의도적 설계로 확인됨.
- 위 3번 항목의 TODO들(전략배포 삭제, 포트폴리오 최적화, 자동매매 스케줄 CRUD)은 **프론트가 잘못 짐작한 게 아니라 실제로 백엔드에 해당 라우트가 없는** 것으로 확인됐습니다 — 이 부분들이 FE/BE 간 실질적 갭입니다.
- 에러 응답 포맷이 엔드포인트마다 다른 것으로 추정되며(4번 기술부채 참고), 프론트가 이를 방어 코드로 흡수하고 있습니다 — 백엔드에서 에러 응답 스키마를 표준화하지 않은 상태로 보입니다.
- raw `fetch()` 우회 호출은 없음 — 모든 네트워크 호출이 인증/리프레시 처리가 되는 axios 인스턴스를 통과합니다(양호).

---

## 8. DB 구조 문제

- **마이그레이션 이원화**: 최상위 `alembic/versions/`(비활성, 5개)와 `database/alembic/versions/`(실사용, 108개)가 공존. `alembic.ini`가 후자만 로드하므로 실질적 충돌은 없지만, 신규 개발자가 잘못된 디렉터리에서 `alembic upgrade head`를 실행하거나 그 파일들을 수정하려 시도할 위험이 있습니다.
- **모델-마이그레이션 드리프트**: `database/alembic/env.py`가 autogenerate 대상 메타데이터에 포함시키려 명시적으로 임포트하는 모델 목록에서 **11개 모델 파일(약 35개 테이블)이 누락**되어 있습니다 — `ai/document_analysis`, `ai/execution`, `ai/market_analysis`, `ai/prompt`, `ai/providers/management_entities`, `ai/recommendation_models`, `auth/preference_models`, `broker/recovery_account_state`, `broker/recovery_conflict_entities`, `notification/inbox_models`, `risk_engine/user_risk_entities`, `strategy_deployment/definition_entities`. 이미 이들에 대한 실제 마이그레이션은 존재하므로 당장 DB가 깨지진 않지만, **앞으로 이 11개 파일을 수정해도 `alembic revision --autogenerate`가 변경을 감지하지 못하는 잠재적 함정**입니다.
- **스키마 선언과 실제 사용의 불일치**: `broker`, `common` 스키마가 `bootstrap.py`에 선언돼 있으나 실제로는 어떤 마이그레이션도 사용하지 않음(브로커 테이블은 `trading` 스키마 소속).
- **PK 타입은 일관됨**: UUID PK는 전혀 없고 전부 `BigInteger`(Identity) 또는 일부 `String`(idempotency_key 등) — 일관성은 있으나 UUID 기반 분산 식별이 필요해질 경우 리팩터링 비용이 큽니다.
- **네이티브 ENUM 미사용**: 모든 상태/타입 필드가 `String(N)` + `server_default` 방식 — 일관되지만 DB 레벨 값 제약이 약함.
- **FK `ondelete` 정책 비일관** (4번 기술부채와 동일 항목, 144개 중 10개만 CASCADE).
- **XOR 계좌 링크 패턴에 CHECK 제약 없음**: `user_broker_account_id`/`paper_account_id` 같은 쌍은 "둘 중 하나만 설정"이라는 의도가 있어 보이나(양쪽 다 nullable), 이를 강제하는 DB 레벨 CHECK 제약은 표본 조사에서 발견되지 않음 — 애플리케이션 로직에만 의존.
- **soft-delete 공용 mixin 부재** (4번과 동일).
- **자동생성 마이그레이션 오기재**: `86706db6ba99_create_job_run_history_table.py`(사실상 no-op, 실제 생성은 `8fe17ae5b326`), `234f43fd1557_create_news_article_and_summary_tables.py`(파일명은 news지만 실제로는 `strategy.risk_policy`/`position_plan` 생성) — 기능적 문제는 아니지만 파일명만 보고 이력을 추적하면 혼란을 줄 수 있습니다.
- **seeds/views/functions 디렉터리는 전부 빈 폴더** — DB 관련 문서에 이 디렉터리들이 마치 채워진 것처럼 언급돼 있다면 그 문서는 신뢰하면 안 됩니다.

---

## 9. 테스트 현황

- **규모**: 256개 파일, `def test_` 1,396건, 실제 `pytest --collect-only` 결과 1,412개 수집(1개는 기본 마커 필터로 제외). **반드시 프로젝트 `.venv`의 Python을 사용해야 합니다** — 시스템 Python으로 실행하면 의존성 부재로 171건의 수집 오류가 발생하며, 이는 코드 문제가 아니라 인터프리터 선택 문제입니다. 이 함정이 문서화돼 있지 않습니다.
- **안전하게 실행 가능한 부분집합(DB/네트워크 불필요, 22개 테스트) 실행 결과: 전부 통과.** 단, 전체 스위트는 실행하지 않았습니다 — `common/settings.py`가 sqlite 폴백 없이 항상 실제 `postgresql://...` URL로 귀결되고(820~826행), 실제로 `localhost:5432`에 리스닝 중인 서버가 발견됐습니다(`.env.example`의 `stock_app`/`stock_platform`과 동일 이름). `@pytest.mark.integration`이 붙은 10개 파일은 기본 필터에서 제외되지 않아 이 DB에 실제로 접속을 시도합니다. 이게 버릴 수 있는 개발용 DB인지 확인되지 않아, 전체 스위트 실행은 위험 판단하에 보류했습니다. **직접 실행 전 이 DB의 정체를 먼저 확인하시길 권합니다.**
- **모듈별 커버리지**: 29개 백엔드 모듈 중 `portfolio`, `strategy`만 참조 테스트 파일이 0건으로 보이지만, 둘 다 STEP56에서 의도적으로 비운 스텁 패키지(`portfolio/__init__.py`, `strategy/__init__.py`의 독스트링에 명시)이고, 실제 로직은 각각 `backtest.portfolio_service`/`trading.portfolio_snapshot_service`, `strategy_deployment`로 이전돼 그쪽에서 충분히 테스트되고 있습니다. 즉 **모듈명만 보고 "테스트 없음"으로 착각하기 쉬운 함정**이며, 실질적으로 완전히 미검증인 백엔드 모듈은 없습니다.
- **테스트 품질**: `assert True` 같은 형식적 테스트는 0건. 리스크 엔진(`test_risk_management_engine.py`)처럼 `Decimal` 계산값을 정확히 검증하는 테스트, DB 세션을 mock하되 서비스 로직의 실제 분기/연산을 검증하는 패턴(`test_admin_dashboard_summary.py`)이 주류입니다. HTTP 상태코드만 확인하고 끝나는 테스트는 19건 중 사실상 1건(`test_step8_ops_smoke.py`의 헬스체크, 의도된 라이브니스 스모크)뿐입니다. 전반적으로 **형식적이지 않은 실질적 테스트**로 평가됩니다.
- **CI**: `.github/workflows/ci.yml`이 실제 `postgres:16-alpine` 서비스 컨테이너로 `alembic upgrade head` 후 `pytest --cov=stock_platform --cov-fail-under=25 -m "not external and not live"`를 실행하고, 프론트는 별도 job에서 test/typecheck/lint/build를 수행합니다 — **이 CI 워크플로우 자체가 오늘자 커밋에서 신규 추가**됐습니다.
- **주의**: 저장소 내 `README_AUDIT_TEST.md`는 "pytest-cov 미설치, 커버리지 게이트 없음"이라고 적혀 있으나, 이는 **현재 사실과 다릅니다**(`.venv`에 `pytest-cov 7.1.0` 설치돼 있고 CI가 `--cov-fail-under=25`로 게이트를 걸고 있음) — README 문서가 최신 상태를 반영하지 못하는 구체적 사례입니다.
- **정체된 스냅샷**: 저장소 루트의 `.coverage` 파일(2026-07-21자, 오래됨)을 읽어보면 당시 기준 전체 라인 커버리지 39%(27,701문 중 16,780 미실행)였습니다. `strategy_deployment/runtime_manager.py` 5%, `trading/execution_sync_service.py`/`paper_e2e_service.py` 0% 등 — 다만 일주일 이상 지난 스냅샷이라 현재값과 다를 수 있습니다. 최신 커버리지는 CI 실행 결과를 확인하시길 권합니다.
- **삭제 권장 대상**: `tests/step32/`, `tests/step33/`, `tests/step34/`(총 7개 파일) — 죽은 프로덕션 코드(6번 항목)만 검증하며, `step33`은 전부 skip 처리돼 사실상 실행되지 않습니다. 삭제해도 실질 커버리지 손실이 없습니다.
- **프론트엔드 테스트**: vitest 40개 파일 중 대부분(37개)은 순수 유틸/헬퍼 함수 테스트이고, 실제 컴포넌트 테스트는 3개(`StatusBadge`, `AppSidebar`, `LoginForm`)뿐. 페이지 단위/통합 테스트는 없음. E2E는 `smoke.spec.ts` 1개(로그인 페이지 렌더링만 확인)뿐이며, README에 "CI 게이트에 연결하지 않은 P2 스캐폴드"라고 스스로 명시돼 있습니다. **결론: 비즈니스 로직(계산/포맷터)은 어느 정도 검증되지만, 실제 화면 렌더링과 사용자 플로우는 사실상 미검증**입니다.

---

## 10. "STEP11" 구현 상태

앞서 0번 항목에서 설명한 대로, "STEP11"은 단일한 의미가 아니라 문맥에 따라 최소 3가지를 가리킬 수 있습니다.

1. **메인 빌드 시퀀스의 서브페이즈로서 STEP11** (`docs/ai/STEP11_1_AI_PROVIDER_ARCHITECTURE.md` ~ `STEP11_13_*`): **완료됨.** AI 프로바이더 레지스트리(`ai/providers/registry.py`, Claude/OpenAI/Gemini/Ollama/호환 프로바이더 + Mock), 후보 평가/합의/승격/추천큐/생애주기 파이프라인이 실제 서비스 코드로 구현돼 있고 19개 테스트 파일에서 검증됩니다.
2. **21단계 감사 워크스루의 STEP11** (`docs/audit/STEP11_UPBIT.md`): Upbit 브로커 연동을 검증하는 감사 스텝이며, 대상인 Upbit 연동 자체는 `broker/upbit/*`로 구현·테스트(관련 테스트 다수, `broker` 모듈이 테스트 참조 1위인 65개 파일)돼 있습니다.
3. **오늘자 최신 커밋 "STEP11 completed" (`3554ef8`)**: 이건 새 기능 구현이 아니라 **v1.1.0 릴리스 이후의 사후 보완/감사 대응 커밋**입니다. 이전 감사에서 지적된 P0급 문제(무인증 뮤테이션 엔드포인트, FK 누락, CI/CD 부재)를 완화하는 작업이며, CI 워크플로우 신설이 그 핵심 산출물입니다.

**종합 평가**: "STEP11"이라는 라벨이 가리키는 실질 작업(AI 프로바이더 아키텍처, Upbit 연동 검증, 혹은 오늘의 사후 보완)은 모두 **구현/완료된 상태**로 확인됩니다. 다만 브리핑에서 말한 "STEP1~11까지가 프로젝트의 전부"라는 프레이밍은 저장소 실태와 맞지 않으며, 실제로는 STEP65~75까지 진행되어 v1.1.0으로 릴리스된 뒤, 오늘 추가 보완 커밋이 올라온 상태입니다. 인수인계 문서나 지시사항에 있는 "STEP11까지"라는 표현을 그대로 신뢰하지 마시고, 이 저장소를 이미 상당 부분 완성된 프로덕트로 다루시길 권합니다.

---

## 부록: 새 리드 개발자를 위한 즉시 참고 사항

- **테스트 실행 시 반드시 `.venv`의 Python을 사용하세요.** 시스템 Python은 의존성이 없어 다수의 수집 오류가 발생합니다.
- **전체 pytest 스위트를 그냥 실행하지 마세요.** `localhost:5432`의 Postgres에 실제로 접속을 시도하는 `@pytest.mark.integration` 테스트가 기본 필터에 걸러지지 않습니다. 이 DB가 무엇인지 먼저 확인하세요.
- **`alembic upgrade head`는 저장소 루트에서 실행해도 자동으로 `database/alembic`을 사용합니다**(alembic.ini 설정). 최상위 `alembic/versions/`는 만지지 마세요 — 죽은 사본입니다.
- **`README_AUDIT_*.md`, `PROJECT_FINAL_AUDIT.md` 등 자체 감사 문서는 작성 시점이 제각각이고 이미 사실과 어긋나는 부분(예: 커버리지 도구 "미설치" 주장)이 확인됐습니다.** 코드/CI 결과를 항상 우선하세요.
- `tests/step32/33/34`, `src/stock_platform/brokers/`, `risk/legacy_gate.py`, `position/calculator.py`, `indicators/simple.py`, 프론트 `features/dashboard/{DashboardWelcome,FoundationChecklist,SystemStatusPlaceholder}.tsx`, `hooks/useHydrated.ts`, `types/common.ts`는 삭제해도 안전해 보이는 죽은 코드 후보입니다(단, 실제 삭제 전 각 항목을 재확인하시길 권합니다 — 이 보고서는 분석만 수행했고 삭제는 하지 않았습니다).

---

*본 보고서는 별도 지시에 따라 프로젝트 저장소 안에 보관되어 Cursor AI 등 향후 세션에서 참조할 수 있도록 저장되었습니다. Git에 커밋되지는 않았으며(스테이징/커밋 여부는 사용자가 별도로 결정), 필요 시 `git add docs/audit/README_AUDIT_CODE_20260728.md`로 추가할 수 있습니다.*
