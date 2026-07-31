# stock-platform 전체 시스템 정밀 감사 보고서

> 작성일: 2026-07-22 | 대상 브랜치: release/v1.1.0 | 방법: 코드 근거 기반 정밀 분석 (Frontend→API→Service→Repository→DB/외부API 실제 호출 흐름 추적, 코드 수정 없음)

**상태 범례**: ✅완료 | 🟡일부구현 | ❌미구현 | 🔌구현됐지만연결안됨 | ⚠구조/보안개선필요 | ♻중복구현 | 🧪테스트만존재 | 🎭Mock만존재
**심각도**: P0(실거래손실·보안침해·중복주문 가능) / P1(핵심 자동매매 프로세스 중단) / P2(일부 기능오류·운영장애) / P3(품질개선). 보안이슈는 Critical/High/Medium/Low 별도 표기.

---

## 1. 경영진 요약

이 프로젝트는 **개별 구성요소(키움 어댑터, 업비트 어댑터, 리스크 엔진, 킬스위치, 인증/RBAC, 지표엔진, 스케줄러)의 코드 품질은 전반적으로 높다.** JWT 발급/재사용탐지, 킬스위치→주문차단 경로, DB 정밀도(Numeric)·시간대(TIMESTAMPTZ)·중복방지(Unique+Upsert) 등 금융시스템의 기본기는 대부분 충실히 구현되어 있다.

그러나 **"부품은 있지만 배선이 끊어진" 문제가 시스템 전반에 반복적으로 나타난다.**

1. **업비트 자동매매는 사실상 사용자에게 도달하지 않는다.** 매매화면이 `broker_code`를 전송하지 않아 업비트를 선택해도 항상 키움으로 라우팅되고(P0), 자동매매 스케줄러·후보생성·사용자 자동매매 화면이 모두 `KRX` 하드코딩이라 코인 24시간 자동매매 경로 자체가 존재하지 않는다.
2. **일반 회원은 자동매매/후보조회/백테스트를 실제로 쓸 수 없다.** 해당 화면들이 호출하는 백엔드 API가 라우터 전체 `require_admin`이라, 실제 서비스 목표인 "사용자 자동매매"의 핵심 기능이 회원 계정으로는 403이 난다(P0).
3. **리스크 엔진을 완전히 우회하는 주문 경로가 존재한다.** `/api/v1/broker/orders`는 킬스위치·포지션한도·일일손실 검사를 전혀 거치지 않고 관리자 인증만으로 주문을 실행할 수 있다. 현재는 인메모리 Paper 어댑터로 배선되어 즉시 피해는 없으나, "실거래 전환 검증용"이라는 설계 의도 자체가 위험하다(P0).
4. **Paper 주문 체결/취소/거부 API에 소유권 검증이 없다.** `order_id`만 알면 타인의 모의투자 주문을 조작할 수 있다(IDOR, P0).
5. **Paper 체결이 원자적이지 않다.** 잔고 검증 없이 주문이 먼저 FILLED로 커밋되고, 이후 계좌 갱신이 실패해도 롤백되지 않아 "체결완료로 기록됐지만 잔고는 그대로"인 데이터 불일치가 발생할 수 있다(P0).

이 5가지가 P0로, **즉시 조치가 필요**하다. 이 외에도 키움 실거래 4중 안전장치를 우회하는 정정/취소 라우트(P1), 백테스트와 실전략의 로직 분기(P1), 브로커별 잔고·손익 통합뷰 부재(P1) 등 핵심 프로세스에 영향을 주는 P1 이슈가 다수 확인됐다. 반면 킬스위치→주문차단, JWT/RBAC, DB 무결성, TypeScript/빌드 상태는 감사 대상 중 가장 견고한 영역으로 확인됐다.

---

## 2. 프로젝트 전체 구조

### 2.1 구조 개요

| 계층 | 경로 | 비고 |
|---|---|---|
| Backend 진입점 | `src/stock_platform/api/main.py`, `router.py`, `lifecycle.py` | FastAPI, `api/v1/` 약 110개 라우트 |
| 브로커 어댑터 | `broker/{kiwoom,upbit,paper}/`, `broker/paper_adapter.py` | 시세 클라이언트는 `brokers/{kiwoom,upbit}/`(단수 broker와 역할 분리) |
| 리스크 | `risk/`(포지션 사이징) vs `risk_engine/`(킬스위치·한도·런타임 안전장치) | 이름은 비슷하나 책임 분리, 둘 다 실사용 |
| 주문 | `order/`(상태머신·아웃박스·멱등성), `trading/`(Paper 엔진) | |
| 실시간 | `realtime/`(전략 실행기, 리스크통합 실행기) | |
| DB | `database/`(엔진/세션), 모델은 도메인별 분산 | Alembic: `database/alembic/versions/`(64개, 실사용) |
| Frontend | `frontend/src/app/(admin)/admin/**`(33페이지), `(user)/user/**`(16페이지) | Next.js 16 App Router |

### 2.2 발견사항

| # | 항목 | 상태 | 근거 | 문제점 | 우선순위 |
|---|---|---|---|---|---|
| 1 | `brokers/`(복수, 시세) vs `broker/kiwoom,upbit`(단수, 주문어댑터) | ✅ 정상 분리 | `broker/__init__.py:3`, `api/v1/kiwoom.py`,`upbit.py` 등에서 단방향 import 확인, 순환의존 없음 | 네이밍 유사로 오인 소지 | P3 |
| 2 | `risk/` vs `risk_engine/` | ✅ 정상 분리 | `realtime/risk_integrated_order_executor.py`는 `risk_engine`만 사용, `risk/engine.py`는 `order/execution_service.py`,`position/exit_monitor.py` 등 포지션사이징에 사용 | 문서화 부족 | P2 |
| 3 | `broker/paper_adapter.py`(`PaperBrokerOrderAdapter`) vs `broker/paper/adapter.py`(`PaperBrokerAdapter`) | ♻ 중복 | 전자는 `broker/runtime.py`(P0-3 경로), 후자는 `factory.py`/`outbox_*.py`(정식 리스크경유 경로)에서 각각 실사용 | 동일 개념 이원화, 유지보수 리스크 | P1 |
| 4 | 루트 `alembic/versions/`(5개) | 🔌 고아 | `alembic.ini`의 `script_location=%(here)s/database/alembic` 확인 — 루트 디렉터리는 어떤 명령으로도 로드 안됨 | 실행되지 않는 마이그레이션 잔재 | P2 |
| 5 | `.env.example` | ⚠ 로컬 상태 주의 | `git show HEAD:.env.example` 존재 확인, `git status`는 `D .env.example`(워킹트리에서만 삭제, 미커밋) — **저장소 결함이 아니라 로컬 편집 중 상태**(`.env.example--` 관련 추정) | 커밋 전 복구 권장 | P3(정보성) |
| 6 | 순환의존/OpenClaw 잔재 | ✅ 없음 | 상호 Grep 결과 없음, `-i openclaw` 검색 결과 문서(.md)만 검출, 소스 잔재 없음 | 없음 | - |
| 7 | 미등록 라우터 2건 | ✅ 의도된 조치 | `api/v1/step32_router.py`(deprecated tombstone, 무인증 우회 제거), `indicator_router.py`(STEP56 등록해제, 삭제예정 미삭제) | (b)는 정리만 남음 | P3 |

---

## 3. 사용자 기능 분석

| 기능 | 상태 | Frontend | Backend | DB | 외부API | 테스트 | 문제점 | 우선순위 |
|---|---|---|---|---|---|---|---|---|
| 대시보드 | 🟡 | `user/dashboard/page.tsx` | `admin_dashboard_summary.py::get_admin_dashboard_summary` | PaperAccount/Position | - | 🧪 | KPI/보유종목은 실DB. "AI추천" 카드가 호출하는 `GET /candidates/top`은 `candidates.py` 라우터 전체 `require_admin`이라 일반회원 항상 403 | P1 |
| 계좌 CRUD | 🟡 | `user/account/page.tsx` | `user_accounts.py`(전 라우트 `assert_account_access`) | PaperAccount, UserBrokerAccount | - | 🧪 | PAPER/KIWOOM/UPBIT 3종 CRUD 정상. "암호화폐 Paper" 전용 계좌타입 없음(exchange_code로만 구분). Kiwoom/Upbit "동기화"는 `last_synced_at` 메타만 갱신, 실브로커 API 미호출 | P2 |
| 전략연결·자동매매 | ❌ | `user/auto-trading`,`strategies/page.tsx` | `realtime_strategy.py`,`realtime_execution.py`,`strategy_deployment.py` 쓰기 전부 `require_admin` | StrategyDeployment | - | ❌ | 자동매매 ON/OFF, 전략생성/중지 등 쓰기 액션 전부 관리자 전용 API 호출 → 일반회원 403. 실행경로도 `REALTIME_PAPER_ACCOUNT_ID` 단일 전역계좌(계정별 격리 아님) | **P0** |
| 후보 조회 | ❌ | 전용 화면 없음 | `candidates.py` 전체 `require_admin` | CandidateBatchResponse | - | ❌ | 회원용 후보조회 화면/권한 자체가 없음 | P1 |
| 주문/체결 조회 | 🎭/❌ | `user/trading`,`trades/page.tsx` | `orders.py`(IDOR 안전) / `paper_orders.py::list_paper_orders`,`cancel/fill/reject` | PaperOrder(account_id 존재) | - | ❌ | `GET /paper-orders`가 비관리자에 **하드코딩된 빈 배열** 반환(주석의 "컬럼 없음" 설명은 사실과 다름). `cancel/fill/reject`는 소유권 검증 **전무** — IDOR로 타인 Paper주문 조작 가능 | **P0(Critical)** |
| 잔고/손익 조회 | ✅ | `user/portfolio/page.tsx` | `user_portfolio.py`(`assert_paper_account_access`) | PortfolioSnapshot | - | 🧪 | 실계산·IDOR 안전. Paper 전용(브로커 실계좌 통합 없음) | - |
| 리스크 설정 | ❌ | 없음(상태 조회만) | 사용자용 리스크 파라미터 CRUD API 부재 | - | - | ❌ | 손절/익절 등을 회원이 직접 설정하는 화면/API 전무 | P2 |
| 백테스트 | ❌ | `user/backtests/page.tsx` | `backtests.py`,`backtest_runs.py` 전체 `require_admin` | BacktestRun | - | 🧪(엔진만) | 엔진 자체는 실동작(mock 아님)이나 실행·조회 모두 관리자 전용 | **P0** |
| 리포트/알림 | ✅ | `user/notifications/page.tsx` | `user_notifications.py`(user_id 스코프) | UserNotification | 텔레그램 | 🟡 | 알림센터·텔레그램 인프라 모두 실동작 | - |

**IDOR 별도 확인**: `user_accounts`,`admin_dashboard_summary`,`orders`,`executions`,`user_portfolio`,`user_notifications`,`paper_orders(생성)`는 소유권 검증 정상. **`paper_orders.py`의 cancel/fill/reject만 검증 누락(P0 확정, 3장 참조)**.

---

## 4. 관리자 기능 분석

| 기능 | 상태 | Frontend | Backend | 문제점 | 우선순위 |
|---|---|---|---|---|---|
| 대시보드 | ✅ | `admin/dashboard` | `admin_dashboard_summary.py` | 정상 | - |
| 회원관리 | ✅ | `admin/members` | `users.py`(CRUD+활성화/비활성화/PW초기화/강제로그아웃) | 정상 | - |
| 전체 계좌관리 | ✅(Paper 한정) | `admin/accounts` | `paper_accounts.py`(admin 전체조회 분기) | "전체 계좌관리"라는 이름과 달리 Paper 계좌만 대상, 실계좌는 별도(kiwoom/upbit) 화면 | P3 |
| 시장데이터 관리 | 🎭 | `admin/data`,`admin/market` | 없음 — 둘 다 `redirect(monitoring)` | 재수집 트리거 UI 자체가 존재하지 않음(스텁) | P2 |
| 전략관리 | ✅ | `admin/strategies` | `strategy_deployment.py`,`strategy_runtime.py::reload` | 등록→배포→런타임 reload 실제 연결. LIVE 배포는 서버가 거부 | - |
| 후보/LLM 관리 | 🟡 | `admin/ai`,`admin/ollama` | `ai_analysis.py`,`candidates.py` | **조회 전용** — 재실행/모델 재로드 등 제어 버튼 없음 | P3 |
| 주문/체결 모니터링 | ✅ | `admin/orders`,`trades`,`trading`,`positions`(→portfolio redirect) | `order_execution.py`,`orders.py`,`executions.py` | 정상 mutation 확인 | - |
| 리스크/킬스위치 | ✅ (가장 견고) | `admin/risk` | `kill_switch.py`→`kill_switch_guard.py`→`trading_guards.py`→`OrderExecutionService` | 버튼→DB→실제 주문차단까지 end-to-end 검증됨 | - |
| 스케줄러/배치 | ✅ | `admin/scheduler`,`batch` | `scheduler_admin.py::run_scheduled_job_now`→실 APScheduler | Run Now 버튼 실동작 | - |
| 장애복구 | ❌ | `admin/operations`(`UnimplementedApiPanel`) | 백업dump/restore, 로그tail API 없음 | 전용 화면 없음(단, 부재를 정직하게 명시) | P1 |
| 감사로그 | ✅ | `admin/logs` | `audit.py::/audit/events` | 정상 | - |
| 시스템설정/상태 | ✅ | `env-settings`,`system-settings`,`monitoring` | `settings.py`,`monitoring.py` | 정상 DB CRUD | - |
| 텔레그램 관리 | 🟡 | `admin/telegram` | `notifications.py::/notification/test` | 테스트발송 실동작하나 "운영명령" 표는 정적 카탈로그, `telegram_ops.py`와 화면 미연결 | P2 |
| 키움/업비트 전용화면 | ✅(단 P1 있음) | `admin/kiwoom`,`upbit` | 실API mutation 연결 | (상세는 5·6장) — kiwoom 계좌패널이 Paper데이터 표시(P1) | P1 |
| DB 관리 | ✅(보안양호) | `admin/db` | `ops_db.py` | **전부 읽기전용**, SQL콘솔·웹restore 없음 — 위험한 직접조작 기능 없음 | - |
| API/문서 | ✅ | `admin/api`,`docs` | `docs_cms.py` | 파일기반 CMS, 읽기전용 | - |

---

## 5. 키움 자동매매 분석

| 항목 | 상태 | 근거 | 문제점 | 우선순위 |
|---|---|---|---|---|
| REST인증/토큰관리 | ✅ | `brokers/kiwoom/auth.py`,`broker/kiwoom/token_client.py`(캐시+갱신여유 300s) | 토큰 메모리 보관(평문DB저장 없음, 안전). 인증 구현이 `brokers/`·`broker/` 두 곳 존재 | P2 |
| 실계좌/모의계좌 분리 | ✅ | `broker/kiwoom/config.py:56-60`(mock/real URL 분기), `settings.py:350-354`(동시활성화시 기동차단) | URL 상수가 2곳(`settings.py`,`config.py`)에 중복정의 | P3 |
| 계좌/잔고/주문가능금액 | ✅ | `broker/kiwoom/account_client.py`(ka00001/kt00001/kt00018 실호출) | 없음 | - |
| 매수/매도/취소/정정 | ✅/⚠ | `broker/kiwoom/adapter.py:78-198`(실HTTP, live게이트 적용) | 별도 경로 `api/v1/kiwoom_pending_orders.py`의 modify/cancel이 **live게이트 완전 우회**(직접 검증 완료, 3장 참조) | **P1** |
| 미체결/체결동기화 | ✅ | `pending_service.py`(ka10075 스냅샷 재구성), WebSocket 실시간 반영 | 상시 폴링 주기 없음(서버시작/수동트리거 한정), WS 재연결 실패시 갭 가능 | P2 |
| 중복주문 방지 | ✅ | DB `uq_trading_order_client_order_id`, `broker/idempotency.py`(cancel/replace) | idempotency가 **프로세스 메모리**뿐 — 재시작시 소실 | P2 |
| 장애복구 | ✅ | `broker/recovery_service.py:69-193`(계좌→미체결→WS→실행기→스케줄러 순차 복구) | 자동매매 실행기는 기본값 재개 안됨(`kiwoom_recovery_start_trading=False`, 의도된 안전장치 가능성) | P3 |
| 실거래 활성화 안전장치 | ✅(경로 한정) | 4중 게이트(`GLOBAL_LIVE_ORDER_ENABLED`,`LiveTradingTransitionGuard`,`KIWOOM_LIVE_ORDER_ENABLED`,1회용 승인토큰) | **이 게이트는 outbox 경로에서만 작동**. `kiwoom_pending_orders.py`는 우회(P1) | **P1** |
| 운영/개발 환경 차단 | 🟡 | `api/v1/kiwoom.py:52-57`(운영에서 테스트API 차단 ✅) | 반대방향(개발에서 실거래 차단) — env 하드 체크 없이 플래그로만 제어 | P2 |
| Frontend 연결 | 🔌(부분) | `admin/kiwoom/page.tsx` — 토큰테스트/계좌동기화 실동작 | **"계좌" 패널이 실제로는 하드코딩된 Paper 어댑터 데이터를 표시**(`broker_orders.py::get_account_snapshot`→`PaperBrokerOrderAdapter`) — 운영자가 실계좌로 오인 위험 | **P1** |

---

## 6. 업비트 자동매매 분석

**핵심 결론: 어댑터·시세수집 계층은 코드 품질이 높으나(JWT/nonce/query_hash 정확, rate-limit·재시도 구현), 실사용자 매매 화면·자동매매 스케줄러와 단절되어 있다 — "구현됐지만 연결 안됨" 판정 다수.**

| 항목 | 상태 | 근거 | 문제점 | 우선순위 |
|---|---|---|---|---|
| 키관리/마스킹 | ✅ | env-only 저장, `mask_secret` | DB 평문저장 없음, 안전 | - |
| 연결테스트 | ✅ | `upbit_account.py`→`test_connection()` | mock 기본값(`UPBIT_USE_MOCK=true`) | P3 |
| KRW/코인 잔고조회 | ✅ | `private_client.py:129-140`(`GET /v1/accounts`) | 없음 | - |
| 마켓/캔들/거래량 수집 | 🟡 | `brokers/upbit/client.py` 실호출 | **자동 스케줄 없음** — `scheduler/automatic.py`에 미등록, 관리자 수동 트리거만 | P1 |
| 기술지표 | 🟡 | 주식과 동일 지표엔진 공유 | 지표배치도 자동 미실행(수동전용) | P2 |
| 후보코인 생성 | 🔌 | `screener/*`는 exchange_code 범용지원 | 스케줄러 `scheduler_exchange_code` 기본값 KRX 고정 — 자동실행 경로 전무 | P1 |
| 시장가/지정가 매수매도 | 🔌 | 어댑터 실재(`order_client.py::create_order`→`POST /v1/orders`, JWT 정확) | **`user/trading/page.tsx`가 `broker_code` 미전송 → 백엔드 기본값 `"KIWOOM"` 확정, UPBIT 선택해도 도달 불가**(직접 재검증 완료: `order_execution.py:38`, `outbox_adapter_resolver.py:50`) | **P0** |
| 주문조회/미체결/취소/동기화 | 🔌 | `order_reconcile_service.py` 실동작 | 위와 동일 이유로 UPBIT 주문 자체가 생성되지 않아 대상 없음 | P1 |
| 최소주문금액(5000원) | ✅ | `broker/upbit/rules.py::validate_upbit_notional` | 없음 | - |
| Rate Limit | 🟡 | 시세: SlidingWindow+tenacity | **주문 클라이언트는 rate limiter 미장착** | P2 |
| nonce/JWT/query_hash | ✅ | `auth.py`(SHA512, uuid4, HS256) | 정확 | - |
| 재시도 정책 | 🟡 | 시세만 지수백오프 5회 | 주문/계좌 클라이언트는 재시도 없음(1회 실패 즉시 예외) | P2 |
| 24시간 자동매매 | ❌ | `automatic.py` 4개 cron 전부 mon-fri 고정시각 | `user/auto-trading/page.tsx` `DEFAULT_EXCHANGE="KRX"` 하드코딩 — **코인 자동매매가 UI 레벨에서 아예 존재하지 않음** | **P0** |
| 코인 전용 리스크 | ❌ | `risk/`,`risk_engine/` 전체 grep 결과 없음 | 코인 고변동성 대응 파라미터 부재, 주식과 동일 정책 적용 | P2 |
| 장애복구 | 🟡 | 킬스위치 exchange-scope는 재사용 가능(reason 문자열 파싱) | 업비트 전용 재연결/복구 로직은 REST 폴링으로 대체, WS 재연결 로직 없음 | P2 |
| 암호화폐 Paper | 🔌 | `PaperBrokerAdapter.submit_order` | 가격/거래소 무관하게 항상 즉시체결(시세반영 없음) — 전체 Paper 공통결함이나 코인 변동성상 영향 큼 | P1 |

---

## 7. Paper Trading 분석

| 항목 | 상태 | 근거 | 문제점 | 우선순위 |
|---|---|---|---|---|
| 체결가=실시세 반영 | ⚠ | `paper_orders.py:147-161`,`paper_executions.py` — `fill_price`를 호출자가 직접 지정 | 실시세 검증 없음. 실시세 기반 시뮬레이터(`DailyCloseFillSimulator`)는 admin전용·자동트리거 없음 → 사실상 "임의가 즉시체결" | **P1** |
| 주식/코인 엔진 공유 | ✅ | `exchange_code` 필드 하나로 분기, 동일 모델/엔진 | 코인 특화 로직(소수점, 24시간) 없음 | 정보성 |
| 슬리피지/수수료 | 🟡 | 슬리피지는 admin 전용 시뮬레이터에만 존재, 수수료 컬럼 자체 없음 | 일반경로 손익이 실거래 대비 구조적으로 유리하게 계산됨 | P2 |
| 부분체결 | ✅ | `paper_engine.py:75-136`(PARTIALLY_FILLED, 가중평균) | 정상 | - |
| 잔고/포지션 갱신 원자성 | ❌ | `PaperOrderRepository.save()`가 무조건 즉시 commit(재검증 완료: `repository.py:15`) → 이후 `account_service.apply_fill()` 실패시 롤백돼도 주문은 이미 FILLED로 커밋 | **주문완료·계좌미갱신 불일치 발생 가능. 주문생성 시점 잔고검증도 없음** | **P0** |
| 리스크 엔진 통과 | 🟡 | 수동생성(`POST /paper-orders`)은 `require_order_safety` 통과 확인 | **`RealtimePaperOrderExecutor`(전략 자동매매 경로)는 risk_engine/kill_switch import 전무(재검증 완료)** — 자동매매 Paper 주문이 리스크 게이트 우회 | **P1** |
| 암호화폐 Paper 계좌 UI | ❌ | 계좌유형 PAPER/KIWOOM/UPBIT 3종, exchange_code로만 시장구분 | "암호화폐 Paper 계좌"라는 별도 개념/화면 없음 | 정보성 |
| 테스트 | 🧪(얕음) | `test_paper_execution_service.py` 등 | Fake 재구현체 사용, 오케스트레이션 코드(원자성 버그) 자체를 검증하지 못함 | P2 |

---

## 8. 시장 데이터·기술지표 분석

| 항목 | 상태 | 근거 | 문제점 | 우선순위 |
|---|---|---|---|---|
| 주식/업비트 수집 | ✅ | `collectors/kiwoom`,`collectors/upbit` 실API호출 | 없음 | - |
| 이어받기(resume) | ✅ | `get_latest().trade_date+1`부터 요청, 최신이면 스킵 | 없음 | - |
| 중복방지 | ✅ | PK(instrument,trade_date), `ON CONFLICT DO UPDATE` upsert | 없음 | - |
| 누락 재수집 | 🟡 | `quality_service.py`가 갭 **탐지**(WARNING) | 자동 백필 로직/잡 전무 — 운영자 수동 재실행 필요 | P2 |
| 시간대 처리 | 🟡 | 캔들 파싱(KST/UTC)은 정확 | 배치트리거·품질리포트 다수가 `date.today()`(서버 로컬tz) 사용 — 자정~09시 KST 구간 경계 오차 가능 | P2 |
| 기술지표(MA/RSI/MACD/BB/ATR/52주고저) | ✅ | `indicators/engine.py` — Wilder RSI14/ATR14, MACD(12/26/9), Bollinger 등 공식 정확 | "거래량증가율(%)" 필드 자체는 없음(MA20만 저장) | P3 |
| 지표 저장방식 | ✅ | 실시간계산 API + `indicator_daily` 캐시테이블 이중구조(의도적) | 없음 | - |
| 주식/업비트 공통구조 | ✅ | `screener`,`ai/context_builder`,`indicators/service` 모두 동일 `IndicatorEngine` 사용 | 완전 공유, 중복 없음 | - |

---

## 9. 후보·전략·뉴스·공시·LLM 분석

| 항목 | 상태 | 근거 | 문제점 | 우선순위 |
|---|---|---|---|---|
| Screener/Candidate | ✅ | `screener/scoring.py`(9지표 100점), `batch_service.py`(limit=10) | 관리종목/거래정지 판정이 종목명 문자열매칭 의존(취약) | P2 |
| 뉴스 수집(네이버) | ✅ | `news/naver_client.py` 실API호출 | 중복제거는 배치 내 해시 매칭만(DB기존과 교차중복은 upsert 위임) | P3 |
| DART 공시 | ✅ | `disclosure/dart_client.py` 실Open API 호출 | 없음 | - |
| 암호화폐 전용 뉴스 | ❌ | 전체 grep 결과 코인전용 소스 없음 | 부재 확인 | P2 |
| Ollama 연동 | ✅ | `ai/ollama_client.py`(`/api/generate`,`/api/chat` 폴백) | 없음 | - |
| LLM 프롬프트/파싱 | ✅ | JSON Schema 강제(`format="json"`)+pydantic 검증 | 파싱실패시 각 서비스가 fallback 처리 | - |
| 후보점수 반영 | ✅ | `orchestration_service.py`(규칙상위10→AI 최종5) | AI 실패시 `_rule_fallback`이 최소점수 미달 후보도 완화선정 가능(사람확인 없이 저장) | P2 |
| **LLM→주문 직접실행** | ✅(위험구조 없음) | `realtime/order_executor.py` AI import 전무, AI리뷰는 결과 반환만 함. LIVE모드 자체를 `ValueError`로 차단 | **없음 — 구조적으로 안전하게 분리됨을 확인** | - |
| 전략 런타임/Reload | ✅ | `runtime_manager.py` — Reload시 전략인스턴스만 교체, 포지션은 러너레벨 유지(안전) | 없음 | - |
| 전략 시장구분 | ✅ | `runtime_loader.py::get_active(market_code,...)` — KRX/UPBIT DB레벨 분리 | 없음 | - |
| 백테스트-실전략 일치 | ❌ | `backtest/strategy.py` vs `realtime/strategy.py` **완전 별도 재구현** | 실전에만 있는 변동률필터(`_passes_change_rate`)가 백테스트엔 없음 — 백테스트 성과가 실전 신뢰성 담보 못함 | **P1** |

---

## 10. 리스크·주문·체결 분석

| 항목 | 상태 | 근거 | 문제점 | 우선순위 |
|---|---|---|---|---|
| RiskIntegratedRealtimeOrderExecutor | ✅(PAPER전용) | 킬스위치→포지션한도→일일손실→세이프티가드→`OrderExecutionService` 순 실관통 | LIVE 전략자동매매 경로는 아직 미구현(`ValueError`로 차단, 안전) | - |
| 계좌별 최대투자금액(절대금액) | ❌ | `position_limit_models.py`에 필드 정의만, 평가로직에서 참조 안됨(죽은필드) | 비율기반(`0.70` 하드코딩)만 실동작 | P2 |
| 종목/코인별 최대투자금액 | ✅ | `position_limit_rule.py` DB설정 가능 | 없음 | - |
| 최대보유수/일일최대손실 | ✅ | `MaximumOpenPositionsRule`,`DailyLossRule`+`DailyLossMonitor`(1분주기, 자동킬스위치) | 한도값이 `risk_engine/runtime.py` 전역상수 하드코딩(계좌별 불가) | P3 |
| 최소주문금액 | 🟡 | 금액지정 주문에만 적용 | 수량 직접지정시 사이징 로직 스킵되어 검증 누락 | P2 |
| 중복주문/빈도제한 | 🟡 | 전략신호 경로만 쿨다운 적용 | 일반 주문API는 idempotency_key(클라이언트 제공)만, 자동탐지 없음 | P2 |
| 급등락 제한 | ❌ | `risk_engine`,`risk` 전체 grep 결과 변동성기반 주문차단 규칙 없음 | 서킷브레이커류 리스크 규칙 부재 | **P1** |
| 손절/익절/트레일링 | ✅(Paper한정) | `exit_monitor.py`+`exit_monitor_scheduler.py`(5초주기), 실제 매도주문 생성 확인 | **Kiwoom/Upbit 실계좌 포지션은 이 자동청산 대상이 아님**(PaperPosition 테이블만 조회) — 실거래 계좌는 자동 손절 메커니즘 없음 | **P1** |
| 시장별 킬스위치 | 🟡 | `kill_switch_service.py` — reason 텍스트 파싱으로 exchange scope 흉내 | 주 주문경로 2곳(`execution_service.py`,`risk_integrated_order_executor.py`)이 `exchange_code`를 아예 미전달 → "UPBIT만 정지"해도 KRX까지 전부 차단(과차단, fail-safe 방향이나 오작동) | P2 |
| 매수차단·매도만허용 | ✅ | `EmergencyStopRule`+`require_order_allowed` 전 호출부 일관 적용 | 없음 | - |
| **리스크엔진 우회 경로** | ❌ | `POST /api/v1/broker/orders`(`broker_orders.py`)→`BrokerOrderService.place_order`→`PaperBrokerOrderAdapter` — **킬스위치/포지션한도/일일손실 전혀 미경유**(재검증 완료: `service.py` 전체에 risk import 없음) | 관리자 인증만으로 도달 가능. 현재 `live_mode=False`+인메모리 Paper 어댑터라 즉시 금전피해는 없으나, "실거래 전환 검증용" 구조 자체가 완성되어 있어 실거래 어댑터 연결 시 즉시 위험 | **P0** |
| Broker Adapter 인터페이스 | 🟡 | `BrokerAdapter`(동기, Kiwoom/Upbit/Paper 3종 구현, 리스크경유 경로) vs `BrokerOrderAdapter`(비동기, `PaperBrokerOrderAdapter` 1종, 리스크우회 경로) | 인터페이스 이원화 자체가 P0 우회경로의 근본원인 | P1 |

---

## 11. 잔고·손익 분석

| 항목 | 상태 | 근거 | 문제점 | 우선순위 |
|---|---|---|---|---|
| 주문 상태머신 | 🟡 | 실거래(`trading_order`)는 정식 `OrderStateMachine` 사용 | Paper(`paper_order`)는 자체 ad-hoc 검증(`_assert_status`)으로 이원화 | P2 |
| 내부ID/외부ID | ✅ | `client_order_id`(unique)+`broker_order_id` 모두 존재 | 없음 | - |
| 평균체결가/미체결수량 | ✅ | `paper_engine.py:100-127` 가중평균, 초과체결 차단 | 없음 | - |
| 보유수량/평균매입가 | 🟡 | `account_service.py` 정확한 가중평균 | `position/calculator.py`(동일로직 재구현)가 어디서도 호출 안되는 죽은코드 | P3 |
| 가용잔고 검증 | ❌ | 체결시점 검사(`apply_fill` BUY시 확인)는 있으나 **주문생성 시점 검증 전무** | 잔고초과 주문이 ACCEPTED까지 생성 가능. 10장의 원자성 결함과 결합시 "체결완료·현금미차감" 실사고 경로 확인 | **P0** |
| 평가/실현/일일/누적손익 | ✅(Paper한정) | `account_service.py`,`portfolio_snapshot_service.py` 공식 검증 정상 | Kiwoom/Upbit 실계좌용 동일 계산서비스는 없음 | P2 |
| 통합 뷰(키움/업비트/Paper) | ❌ | `user_accounts.py`는 계좌를 타입별 나열만, 합산없음. `PortfolioSnapshotService`는 PaperAccount만 참조 | 브로커별 완전 분리, 통합 대시보드 부재 | **P1** |

---

## 12. 장애복구·스케줄러·운영 분석

| 항목 | 상태 | 근거 | 문제점 | 우선순위 |
|---|---|---|---|---|
| 서버시작 복구 흐름 | 🟡 | `lifecycle.py:142-192` — 설정검증/DB연결은 실패시 기동차단, **브로커복구는 `_run_optional`로 실패해도 조용히 통과** | 복구실패가 텔레그램 등으로 통지되지 않음, 로그만 | P1 |
| 미체결 복구(외부-DB대조) | 🟡 | `pending_service.py::synchronize()` — 브로커 응답으로 통째로 delete후 재삽입 | 개별 불일치 검출/경고 없음. **업비트용 동등 로직 없음**(키움 전용) | P1 |
| 중복 재주문 방지 | ✅ | outbox idempotency(`idempotency_key`+`request_hash`) | 복구서비스는 조회전용이라 재주문 시나리오 자체가 설계상 없음 | - |
| Kill Switch 복구 | ✅ | 매 주문검증시 DB 직접조회(메모리캐시 없음) | 재시작 타이밍갭 없음 | - |
| 전략런타임 복구 | 🟡 | 단일 활성 PAPER 전략 1개만 자동로드 | 복수 배포전략은 자동복원 안됨 | P2 |
| 장전/장중/장후 작업 | ✅ | `automatic.py` 4개 cron(후보선정→AI분석→포지션계획→스냅샷), `position_planning`은 `allowed_actions=["WATCH","REVIEW"]`뿐(자동실주문 없음) | 없음 | - |
| 작업중복실행 방지 | 🟡 | 전 job `max_instances=1`,`coalesce=True` | 프로세스간(DB advisory lock 등) 락은 없음 — 스케줄러 프로세스 중복기동 방지장치 부재 | P2 |
| 실패작업 재시도/알림 | 🟡 | 파이프라인 `max_attempts=3`+지수백오프, DB에 실패기록 | **텔레그램 등 실패 알림 발행 코드 없음** — 배치실패가 운영자에게 능동통지 안됨 | P2 |
| NSSM/시작스크립트 | ✅ | `ops/install_nssm_service.ps1`(재시작정책, 로그로테이션) | 없음 | - |
| DB백업/복원 | 🟡 | `ops/backup_db.ps1` 실 pg_dump 스크립트 존재 | **자동 주기실행 등록(Task Scheduler 등) 없음** — 수동실행 의존 | **P1** |
| Health Check | ✅ | `/health`가 DB latency 실측 | 운영환경은 DB만 점검, 브로커API 상태 미포함 | P3 |
| 운영로그 | ✅ | structlog JSON, 민감정보 마스킹, NSSM 로테이션(10MB) | 없음 | - |

---

## 13. DB 분석

| 항목 | 상태 | 근거 | 문제점 | 우선순위 |
|---|---|---|---|---|
| 스키마 규모 | ✅ | 65개 마이그레이션, `create_table` 81회 — 인증/RBAC·계좌·주문체결·포지션·리스크·후보전략·뉴스공시·시세지표·운영 도메인 커버 | 없음 | - |
| PK/FK/Unique | 🟡 | `paper_position` unique(계좌,거래소,종목), `execution` unique(브로커,체결ID, 중복체결방지) 등 양호 | **`trading_order.account_id`(실거래 주문) FK 제약 누락** — 동일테이블 타 컬럼은 FK 있는데 이것만 없음 | **P1** |
| Numeric 정밀도 | ✅ | 전체 `Float(` 0건, 전부 `Numeric(20,2)`/`Numeric(28,8)` 등 | 문제없음(금융시스템 기본요건 충족) | - |
| Soft Delete/Audit | 🟡 | created_at/updated_at 전테이블 일관 | `deleted_at`은 `PaperAccount`만 존재, `UserBrokerAccount`는 `is_active`만 사용 — 패턴 불일치 | P3 |
| 사용자 소유권 컬럼 | ✅ | `PaperAccount.user_id`,`UserBrokerAccount.user_id`(FK), 주문/포지션은 `account_id` 경유 | 일관성 있음 | - |
| 시간대 | ✅ | 전체 마이그레이션 `DateTime(timezone=True)`만 사용, naive 0건 | 없음 | - |
| 코드-DB 불일치 | ✅ | 확인범위(PaperAccount 등) 내 완전 일치 | 전수조사는 아님 | - |
| 불필요/중복 | 🟡 | 시세미시구조 테이블(candle_minute 등)은 전부 실사용 확인. `position/calculator.py`(DB매핑 없는 순수로직)는 죽은코드 | 코드중복(테이블 orphan은 없음) | P3 |

---

## 14. Frontend 분석

| 항목 | 상태 | 근거 | 문제점 | 우선순위 |
|---|---|---|---|---|
| TypeScript | ✅ | `tsc --noEmit` exit 0 | 없음 | - |
| Lint | ⚠ | `npm run lint` — 2 errors, 7 warnings | `profile/page.tsx:84`,`trades/page.tsx:71`의 `react-hooks/set-state-in-effect` 에러(렌더캐스케이드 유발) | P2 |
| 프로덕션 빌드 | ✅ | `npm run build` exit 0, 59라우트 정적생성 성공 | `middleware.ts` 컨벤션 deprecated 경고(Next16) | P3 |
| Mock 데이터 잔존 | ✅ | 전체 grep 결과 없음 | 없음 | - |
| 빈 버튼/CRUD 누락 | 🟡 | watchlist/members는 완전CRUD | 뉴스/공시/포트폴리오 관리화면은 조회+동기화만(구조상 의도 가능) | P3 |
| 로딩/에러/빈상태 | 🟡 | watchlist는 로딩/빈상태 분리 렌더 | admin 대시보드는 `isError` 처리 0건 — API실패시 에러메시지 없이 빈값 렌더 가능 | P2 |
| 중복클릭 방지 | ✅ | 주문제출폼 `isPending` 기반 disable 확인 | 없음 | - |
| 권한별 메뉴 | ✅ | `menu.tsx::filterMenuByPermissions/filterUserMenuByRoles` 실제 필터링 | 클라이언트 렌더 단계만 필터링, 서버미들웨어는 쿠키존재만 확인(교차이슈) | P1 |
| Deprecated 라우트 | 🟡 | `routes.ts`의 `@deprecated routes` export가 실제 3곳(404페이지, interceptors, 회원가입폼)에서 여전히 사용중 | 마이그레이션 미완료 | P3 |
| API URL-Backend 일치 | ✅ | 4개 샘플(`/user/watchlist`,`/orders`,`/paper-orders`,`/system/dashboard`) 전부 prefix 일치 | 없음 | - |
| 미사용 컴포넌트 | 🟡 | `ComingSoon.tsx` — 외부 소비처 0건(데드코드 추정) | 정리 필요 | P3 |
| **매매화면 broker_code 누락** | ❌ | `user/trading/page.tsx` — exchange_code만 전송, broker_code 필드 자체 없음 | **업비트 선택해도 항상 키움으로 라우팅(P0, 6장 참조)** | **P0** |

---

## 15. 보안 분석

| # | 이슈 | 등급 | 근거 | 우선순위 |
|---|---|---|---|---|
| 1 | Paper 주문 fill/cancel/reject 소유권 검증 누락(IDOR) | **High** | `api/v1/paper_orders.py:147-222`, 직접 재검증 완료 | **P0** |
| 2 | `/api/v1/broker/orders` 리스크엔진 완전 우회 | **High**(구조적, 현재 실피해 없음) | `broker/service.py` 전체 risk import 없음, 직접 재검증 완료 | **P0** |
| 3 | `kiwoom_pending_orders.py` modify/cancel이 실거래 4중 안전장치 우회 | **High** | 관리자 인증만 요구, 직접 재검증 완료 | P1 |
| 4 | Frontend `middleware.ts` — JWT 서명/만료 미검증(쿠키 존재만 확인) | Medium | `middleware.ts:19-37`, 백엔드가 최종방어선이라 실피해 제한적 | P2 |
| 5 | 텔레그램/키·시크릿 저장 | ✅ 안전 | Upbit 키 env-only, Kiwoom 토큰 메모리보관, JWT시크릿 하드코딩 없음(운영은 미설정시 기동차단) | - |
| 6 | 관리자 API 보호 | ✅ 대체로 안전 | 샘플링한 관리자 라우터 대부분 `require_admin`/`require_permission` 정상 적용 | - |
| 7 | Refresh Token 재사용 탐지 | ✅ 안전 | jti+해시+user_id 삼중검증, timing-safe 비교 | - |
| 8 | 비활성/잠금 사용자 차단 | ✅ 안전 | 로그인시 + 매 요청시(`get_current_user`) 이중 재검증 | - |
| 9 | DB 관리자 화면 | ✅ 안전 | 전부 읽기전용, SQL콘솔/웹restore 없음 | - |

---

## 16. 테스트 분석

- **규모**: 169개 파일, 516개 테스트 수집(`pytest.ini` 기본필터 `not external and not live`). 단, `external`/`live` 마커를 실제로 사용하는 테스트는 **0건** — 마커체계가 장식적이며, 사실상 모든 테스트가 mock 어댑터 기반(실 API 계약변경 감지 불가).
- **키움/업비트 Mock 테스트**: `test_kiwoom_client.py`,`test_upbit_order_adapter.py` 등은 `httpx.MockTransport`로 실제 클라이언트 로직(헤더/페이징/검증 예외)을 검증하는 **깊이 있는 테스트**로 확인됨(응답형태만 확인하는 얕은 테스트 아님).
- **확정 P0/P1 6건 전부 "관련 라우터/통합지점을 호출하는 테스트가 아예 없어서" 검출되지 못한 것으로 일관 확인**:

| P0/P1 이슈 | 테스트 존재? | 근거 |
|---|---|---|
| paper_orders IDOR | ❌ | 관련 grep 결과 무결과. 유사패턴(`account_ownership`+403)은 `test_step65_user_accounts.py`에는 있으나 거래도메인엔 미적용 |
| broker_orders 리스크우회 | ❌ | `test_broker_order_service.py`는 승인토큰 플로우만 검증, 리스크경유 여부 어서션 없음 |
| Frontend broker_code 누락 | ❌ | `openOrders.test.ts`는 필터헬퍼만 테스트. `e2e/smoke.spec.ts`는 로그인렌더 1건뿐, "추후확장" 주석 |
| kiwoom_pending_orders 안전장치우회 | ❌ | 유일 관련테스트는 DTO매퍼만 검증, 라우터 호출 테스트 없음 |
| Paper 체결 원자성 | ❌ | `test_paper_execution_service.py`는 Fake 세션(rollback 미검증)으로 해피패스만 확인 |
| 백테스트-실전략 divergence | ❌ | 두 엔진을 교차검증하는 테스트 없음 |

- **IDOR/권한 테스트**: 계좌 도메인(`test_step65_user_accounts.py` 등)에는 IDOR 테스트 관행이 확립되어 있으나 **거래(주문) 도메인에는 적용되지 않음** — 팀 역량 문제가 아니라 신규/개조 라우터에 대한 적용 누락으로 판단.
- **Kill Switch 테스트**: ✅ 풍부(`test_kill_switch_service.py` 등), 단 가드가 실제로 호출되는지(배선 지점)는 검증 안됨.
- **Frontend**: Vitest 26개 파일은 순수 헬퍼함수 단위테스트 위주. Playwright E2E는 스모크 1건뿐 — **실질적 E2E 커버리지 없음(🎭)**.
- **Lint(Backend)**: ruff/mypy 설정 없음. pyflakes 임시실행 결과 46건(대부분 미사용 import). `upbit_account.py`에 비인쇄 유니코드 문자 혼입 발견(파싱 이슈 원인, 별도 확인 필요).

---

## 17. 미구현 기능 목록 (❌)

1. 사용자 리스크 파라미터(손절/익절 등) 설정 화면·API
2. 업비트 24시간 자동매매(스케줄러·프론트 모두 KRX 하드코딩)
3. 암호화폐 전용 뉴스 수집 소스
4. 급등락 제한(변동성 서킷브레이커) 리스크 규칙
5. 계좌별 최대투자금액(절대금액) — 필드만 정의, 로직 미사용
6. 관리자 장애복구 UI(백업 dump/restore, 로그 tail)
7. 자동 주기 DB 백업 스케줄 등록
8. 브로커 통합 잔고·손익 뷰(키움/업비트/Paper 합산)
9. 거래량증가율(%) 지표 필드
10. Paper 체결 수수료/슬리피지 모델(일반 경로)
11. 결측 데이터 자동 백필(탐지만 존재)
12. 사용자용 후보종목/코인 조회 화면(admin 전용만 존재)

## 18. 연결되지 않은 기능 목록 (🔌)

1. 업비트 주문 어댑터 전체(시장가/지정가/취소/동기화) — 코드는 완성도 높으나 사용자 매매화면과 단절(broker_code 누락)
2. 업비트 후보코인 생성 로직 — 스케줄러 KRX 고정으로 자동실행 경로 없음
3. `/api/v1/broker/orders` — 실거래 어댑터·리스크엔진과 미연결(현재 Paper 인메모리 어댑터)
4. `admin/kiwoom` 계좌 패널 — 실제 키움 데이터가 아닌 Paper 어댑터 데이터 표시
5. 사용자 자동매매/전략/후보/백테스트 화면 — 백엔드가 admin 전용이라 사실상 미연결(회원 기준)

## 19. 중복·미사용 코드 목록 (♻)

1. `broker/paper_adapter.py`(`PaperBrokerOrderAdapter`) vs `broker/paper/adapter.py`(`PaperBrokerAdapter`) — 이원화, P0 우회경로의 근본원인
2. 루트 `alembic/versions/`(5개, 고아 — `database/alembic`이 정본)
3. `position/calculator.py`,`position/models.py::Position` — 어디서도 호출되지 않는 죽은 코드
4. `screener/service.py::filter_candidates`(레거시 STEP34 호환) — 호출처 없음
5. `frontend/src/components/common/ComingSoon.tsx` — 소비처 없음
6. 주문 상태머신 이원화(실거래 `OrderStateMachine` vs Paper `_assert_status` ad-hoc)
7. `brokers/`(시세) vs `broker/`(주문) — 이름 유사(중복 아님, 문서화 필요)

---

## 20. 우선순위 개선 계획

### P0 — 즉시 차단 항목

| # | 작업명 | 문제 | 영향 | 수정대상 | DB Migration | 테스트 필요 | 선행작업 | 완료조건 |
|---|---|---|---|---|---|---|---|---|
| P0-1 | Paper 주문 소유권 검증 추가 | `paper_orders.py` fill/cancel/reject에 `assert_paper_account_access`류 검증 없음(IDOR) | 타 사용자 Paper 주문 무단 조작 | `api/v1/paper_orders.py:147-222` | 불필요 | 타 사용자 order_id로 조작 시도 → 403 테스트 | 없음 | 3개 엔드포인트 모두 `order_cancel_replace.py`의 `_assert_order_owner` 패턴 적용, 회귀테스트 통과 |
| P0-2 | 매매화면 broker_code 전송 | Frontend가 broker_code 미전송 → 항상 KIWOOM 라우팅 | 업비트 실거래/모의거래 전면 불가 | `frontend/.../user/trading/page.tsx`, `api/v1/order_execution.py:38`(기본값 제거 또는 exchange_code 기반 자동매핑) | 불필요 | UPBIT 선택 후 주문 제출 시 실제 UpbitBrokerAdapter 호출 검증 E2E | 없음 | exchange_code=UPBIT 선택 시 broker_code=UPBIT로 정확히 전달되어 outbox_adapter_resolver 도달 확인 |
| P0-3 | 리스크엔진 우회 경로 제거/재배선 | `/api/v1/broker/orders`가 킬스위치·리스크한도 미경유 | 실거래 전환 시 무제한 리스크 우회 주문 가능 | `api/v1/broker_orders.py`, `broker/service.py`, `broker/runtime.py`, `broker/paper_adapter.py`, `broker/base.py` | 불필요 | 킬스위치 활성 상태에서 이 경로 호출 시 차단되는지 검증 | P0-1 이후 우선 | 이 라우트를 제거하거나 `OrderExecutionService` 경유로 재배선, 킬스위치/한도 검증 통과 확인 |
| P0-4 | Paper 체결 원자성/잔고검증 확보 | 주문 FILLED 커밋과 계좌갱신 커밋 분리, 생성시점 잔고검증 없음 | 잔고초과 체결·데이터 불일치 | `trading/repository.py:15`, `trading/execution_service.py:97-127`, `trading/service.py::create`(생성시 잔고검증 추가) | 불필요(로직변경) | 계좌갱신 실패 유도 시 주문도 함께 롤백되는지 통합테스트(실제 DB세션) | 없음 | 주문체결과 계좌갱신을 단일 트랜잭션으로 묶고, 생성 시점 가용잔고 검증 추가, 실패 시나리오 테스트 통과 |
| P0-5 | 사용자 자동매매/후보/백테스트 접근권한 재설계 | `realtime_strategy.py` 등이 라우터 전체 require_admin이라 일반회원 403 | 서비스 핵심가치(사용자 자동매매)가 회원계정으로 작동 안함 | `api/v1/{realtime_strategy,realtime_execution,candidates,backtests,backtest_runs}.py`, `strategy_deployment.py` | 필요 가능성(사용자별 실행 슬롯 분리시) | 일반회원 계정으로 자동매매 ON/OFF, 후보조회, 백테스트 실행 E2E | 계정별 실행격리 설계(`REALTIME_PAPER_ACCOUNT_ID` 전역 문제 해결) 선행 | 일반회원 권한으로 각 기능 200 응답 및 실제 동작 확인 |
| P0-6 | 업비트 자동매매 스케줄 활성화 | 스케줄러/자동매매화면이 KRX 하드코딩 | 코인 24시간 자동매매 전면 부재 | `scheduler/automatic.py`, `scheduler/handlers.py`, `frontend/.../user/auto-trading/page.tsx` | 불필요 | 업비트 캔들/지표/후보 배치가 자동 실행되는지, 야간에도 도는지 확인 | P0-2 선행 권장 | UPBIT 전용(또는 24시간) cron 등록, 자동매매 화면에서 거래소 선택 가능 |

### P1 — 핵심 기능 복구

| # | 작업명 | 요약 | 수정대상 | 우선순위 근거 |
|---|---|---|---|---|
| P1-1 | 키움 pending-orders 안전장치 적용 | `kiwoom_pending_orders.py` modify/cancel에 4중 게이트 적용 | `api/v1/kiwoom_pending_orders.py` | 실거래 안전장치 우회 |
| P1-2 | admin/kiwoom 계좌패널 데이터 소스 수정 | Paper 어댑터 대신 실제 Kiwoom 계좌조회 연결 | `api/v1/broker_orders.py::get_account_snapshot` | 운영자 오인 위험 |
| P1-3 | RealtimePaperOrderExecutor 리스크게이트 적용 | 전략 자동매매 Paper 주문도 킬스위치/리스크 경유 | `realtime/order_executor.py` | 리스크 우회 일관성 |
| P1-4 | 백테스트-실전략 로직 통합 | 공통 전략 로직 모듈化, 변동률필터 등 동기화 | `backtest/strategy.py`, `realtime/strategy.py` | 백테스트 신뢰성 |
| P1-5 | 급등락 제한 리스크 규칙 추가 | 서킷브레이커류 규칙 신설 | `risk_engine/rules.py` | 리스크 커버리지 공백 |
| P1-6 | 실계좌 포지션 자동청산 확장 | exit_monitor가 Kiwoom/Upbit 포지션도 감시하도록 확장 | `position/exit_monitor_loader.py` | 실거래 계좌 손절 메커니즘 부재 |
| P1-7 | 브로커 통합 잔고·손익 뷰 | 사용자 대시보드에 3개 브로커 합산 뷰 추가 | `api/v1/user_portfolio.py`, `user_accounts.py`, Frontend 대시보드 | 사용자 경험/리스크 가시성 |
| P1-8 | trading_order.account_id FK 추가 | 참조무결성 보강 | DB migration | 데이터 무결성 |
| P1-9 | 자동 DB 백업 스케줄 등록 | Task Scheduler/NSSM에 backup_db.ps1 주기등록 | `ops/` | 운영 복구력 |
| P1-10 | paper/broker 어댑터 이원화 정리 | 둘 중 하나로 통합 | `broker/paper_adapter.py`, `broker/paper/adapter.py` | 유지보수 리스크·P0-3 근본원인 |
| P1-11 | 브로커복구 실패 알림 추가 | 서버시작 복구 실패시 텔레그램 통지 | `api/lifecycle.py` | 운영 가시성 |

### P2 — 통합 기능 완성
데이터 백필 자동화, `date.today()` KST 일관 적용, 업비트 주문클라이언트 rate-limit/재시도 추가, 코인 전용 리스크 파라미터, 텔레그램 운영명령 화면 연결, 파이프라인 실패 알림, admin/data·market 화면 실체화, lint 에러 2건(set-state-in-effect) 수정, 시장별 킬스위치 exchange_code 전파 수정.

### P3 — 품질 개선
루트 alembic 고아 디렉터리 삭제, `.env.example` 로컬 상태 정리, 죽은 코드 제거(`position/calculator.py`, `screener/service.py::filter_candidates`, `ComingSoon.tsx`), deprecated `routes` export 마이그레이션, 네이밍 문서화(`broker`/`brokers`, `risk`/`risk_engine`), 거래량증가율 지표 필드 추가, soft-delete 컬럼 적용기준 통일.

---

## 21. 완성도 점수

### 사용자 기능

| 항목 | 점수 | 근거 |
|---|---|---|
| 로그인·권한 | 85 | JWT/RBAC/재사용탐지 견고. Paper주문 IDOR 1건이 감점요인 |
| 계좌관리 | 65 | CRUD는 실동작하나 브로커 동기화가 메타데이터 갱신 수준, 코인전용 계좌개념 없음 |
| 시장데이터 | 50 | 백엔드 파이프라인은 견고하나 사용자에게 노출되는 후보/지표 접근이 admin 전용으로 막혀있음 |
| 전략 | 15 | 화면은 있으나 쓰기 액션 전부 403(admin 전용), 전역 단일계좌 구조 |
| 후보선정 | 10 | 사용자용 후보조회 자체가 없음 |
| 주문·체결 | 40 | 생성은 되나 조회(paper_orders 빈배열)·조작(IDOR)에 심각한 결함, 업비트 라우팅 단절 |
| 잔고·손익 | 55 | Paper 손익은 정확하나 브로커 통합뷰 부재 |
| 리스크 | 10 | 사용자 설정 기능 전무 |
| 리포트·알림 | 80 | 알림센터·텔레그램 실동작 |
| **평균** | **~46** | |

### 관리자 기능

| 항목 | 점수 | 근거 |
|---|---|---|
| 회원관리 | 90 | 완전한 CRUD+상태관리 |
| 계좌관리 | 70 | Paper 전체조회는 되나 실계좌 통합관리는 아님 |
| 데이터운영 | 40 | data/market 화면이 스텁(redirect)로만 존재 |
| 전략관리 | 80 | 배포·reload 실동작 |
| 후보/LLM관리 | 50 | 조회 전용, 제어기능 없음 |
| 주문모니터링 | 85 | 정상 |
| 리스크·킬스위치 | 90 | 가장 견고, end-to-end 검증됨 |
| 장애복구 | 30 | 전용 UI 없음(부재 명시는 양호) |
| 스케줄러 | 85 | 실 job 트리거 확인 |
| 로그·감사·알림 | 75 | 감사로그 정상, 텔레그램 일부 미연결 |
| **평균** | **~70** | |

### 시장별 자동매매

| 시장 | 점수 | 근거 |
|---|---|---|
| 키움 주식 자동매매 | 68 | 어댑터/인증/주문/복구 전반 견고하나 안전장치 우회 라우트(P1), admin 화면 데이터오인(P1) 존재 |
| 업비트 자동매매 | 28 | 어댑터 코드품질은 높으나 사용자 경로·자동스케줄과 완전 단절(P0 다수), 코인전용 리스크 없음 |
| 주식 Paper Trading | 42 | 부분체결·가중평균 등 기본기는 되나 원자성 결함(P0), 실시세 미반영, 리스크우회 |
| 암호화폐 Paper Trading | 35 | 엔진은 주식과 공유되어 동작하나, 전용 UI 부재 + 주식Paper와 동일한 원자성/리스크 결함 상속 |

### 종합

| 구분 | 점수 |
|---|---|
| **사용자 기능 전체 완성도** | **46 / 100** |
| **관리자 기능 전체 완성도** | **70 / 100** |
| **키움 자동매매 완성도** | **68 / 100** |
| **업비트 자동매매 완성도** | **28 / 100** |
| **Paper Trading 완성도** | **39 / 100**(주식42, 코인35 평균) |
| **전체 프로젝트 완성도** | **약 50 / 100** |

**종합 근거**: 백엔드 핵심 도메인 로직(인증, 킬스위치, DB무결성, 지표계산, 브로커 어댑터 개별 코드)의 품질은 60~90점대로 준수하다. 그러나 이 부품들을 사용자에게 실제로 연결하는 "마지막 배선"(Frontend↔API 권한, broker_code 전달, 스케줄러 등록, 리스크게이트 배선)에서 반복적으로 누락이 발생해 실사용 가능한 완성도는 부품 품질보다 크게 낮다. 특히 "사용자가 실제로 쓸 수 있는 자동매매"라는 프로젝트의 핵심 목표 기준으로는 업비트(28점)와 사용자 전략기능(15점)이 사실상 미완성 상태다.

---

*본 보고서는 코드 읽기·검색(Read/Grep)과 직접 재검증(2차 확인)을 통해 작성되었으며, 코드 수정은 수행하지 않았습니다.*
