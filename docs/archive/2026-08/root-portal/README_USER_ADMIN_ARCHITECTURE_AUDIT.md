# USER/ADMIN 통합 자동매매 아키텍처 조사 보고서

조사일: 2026-07-22
조사 범위: `src/stock_platform/**`(Backend, FastAPI), `frontend/src/**`(Next.js 16.2.10), `database/alembic/**`
조사 방식: 코드 수정 없이 Read/Grep/Glob 기반 실제 코드·라우팅·DB 마이그레이션·프론트 API 호출 추적. Mock/미구현 여부는 실제 호출 체인(Frontend → apiClient → FastAPI router → Service/Repository → DB or 외부 API)을 따라가서 판정.

---

## 9.1 전체 평가

| 항목 | 평가 | 근거 |
| --- | --- | --- |
| 로그인 통합 여부 | ✅ 완료 | `/login` 단일 화면. `frontend/src/app/(auth)/login/page.tsx`, Backend `POST /api/v1/auth/login` 단일 엔드포인트로 사용자·관리자 공통 처리 |
| 권한별 화면 분리 여부 | 🟡 부분 완료 | `(admin)/admin/*` vs `(user)/user/*` 라우트 그룹은 명확히 분리. 단, Role 자체가 2단계(ADMIN/USER)가 아니라 3단계(`admin`/`operator`/`viewer`)이며 `operator`가 관리자 콘솔 접근 권한(`canAccessAdminPortal`)을 가져 경계가 완전히 이분법적이지 않음 |
| 사용자 기능 완성도 | 🟡 60~70% | 계좌·주문(Paper)·잔고·알림·관심종목은 실 API 연동 완료. **전략관리는 Admin 전용 API를 그대로 호출**하여 일반 유저(viewer)는 사실상 사용 불가 |
| 관리자 기능 완성도 | 🟡 70~80% | 회원·계좌·리스크·킬스위치·스케줄러·전략은 구현. 감사 로그는 전용 메뉴가 아니라 다른 화면에 내장 |
| 주식 통합 수준 | ✅ 높음 | Kiwoom 시세·주문·계좌 동기화 라우터 다수(`kiwoom.py`, `kiwoom_account_sync.py`, `kiwoom_pending_orders.py` 등) 존재, 사용자 매매 화면에서 실 API 사용 |
| 업비트 통합 수준 | 🟡 중간 | Backend 라우터는 존재(`upbit.py`, `upbit_account.py`)하나, User 메뉴/라우트에 "업비트" 전용 화면이 없음 — `/user/trading`의 거래소 Select에 `UPBIT` 옵션만 추가된 수준 |
| Paper 통합 수준 | ✅ 높음 | `paper_account`/`paper_order`/`paper_position`/`paper_trade` 테이블, `user_id` 소유권 컬럼 포함, User 화면에서 생성·주문·포지션 조회까지 실동작 |
| Backend 권한 검증 수준 | ✅ 양호 | `get_current_user`/`require_admin`이 JWT claim이 아니라 **매 요청마다 DB(RBAC 테이블)를 재조회**하여 역할을 재검증(`auth/deps.py:259-266`). 강등 즉시 반영됨 |
| Frontend Route Guard 수준 | 🟡 보조적 | `middleware.ts`는 쿠키 존재 여부만 확인하는 **soft gate**이며, 실제 role 검사는 클라이언트 컴포넌트 `AuthGuard.tsx`에서 수행(우회 가능한 계층). 최종 방어선은 Backend API 권한 검증 |

**핵심 발견 3가지**

1. **Role 모델이 ADMIN/USER 2단계가 아니라 `admin`/`operator`/`viewer` 3단계**로 시딩되어 있음(`database/alembic/versions/e3f4a5b6c7d8_create_rbac_tables.py`). Frontend는 `operator`를 "trader" 티어로 표시하며 관리자 콘솔 접근을 허용(`roles.ts:canAccessAdminPortal`)한다.
2. **키움·업비트 실계좌 인증은 회원별이 아니라 서버 공용(단일) credential**이다. `UserBrokerAccount` 테이블은 계좌번호 해시·마스킹 값만 저장하고 App Key/Secret은 아예 저장하지 않는다. 사용자 화면에도 "키움 OpenAPI는 현재 서버 공용 인증을 사용합니다"라고 명시되어 있어 은폐된 문제는 아니지만, "회원별 실계좌 자동매매"라는 목표 아키텍처와는 구조적으로 다르다.
3. **전략관리(전략 배포/런타임/실시간 전략) API가 전부 `require_admin` 전용**인데, User 화면(`/user/strategies`)이 이 API들을 그대로 호출한다. 일반 회원(viewer 기본 역할)은 이 화면에서 대부분의 액션이 403으로 실패한다 — 사용자 소유 전략 연결 모델 자체가 없음.

---

## 9.2 사용자(USER) 기능 결과

| 기능 | 상태 | Frontend 위치 | Backend 위치 | DB | 문제점 | 개선 필요 |
| --- | --- | --- | --- | --- | --- | --- |
| 로그인/로그아웃/토큰 갱신 | ✅ 완료 | `(auth)/login`, `features/auth/hooks/useAuth.ts` | `api/v1/auth.py` (`/login`,`/refresh`,`/logout`) | `auth.user`, `auth.refresh_token` | 없음 | - |
| 대시보드(본인 자산·손익 등) | 🟡 일부 구현 | `(user)/user/dashboard/page.tsx` | `api/v1/admin_dashboard_summary.py`(`/dashboard/admin-summary`, 이름은 admin이지만 소유권 검사로 공용) | `paper_account` 등 | 엔드포인트 명칭이 `admin-summary`로 혼란 소지, 실거래(Kiwoom/Upbit) 자산 통합 표시 여부 미확인 | 명칭 정리 및 통합자산 뷰 검증 |
| 내 계좌 (Paper) | ✅ 완료 | `(user)/user/account/page.tsx` | `api/v1/user_accounts.py` | `trading.paper_account` | 없음 | - |
| 내 계좌 (Kiwoom/Upbit 연결) | 🟡 일부 구현 | 동일 페이지 내 "Broker 계좌 연결" 폼 | `api/v1/user_accounts.py` | `trading.user_broker_account` | 실제 App Key/Secret 입력·저장 UI 없음(설계상 의도적) — 회원별 실계좌 자동매매 아님, 계좌번호 매핑(별칭)만 존재 | 목표 아키텍처와 방향 합의 필요 |
| 시장 정보 - 주식(종목/시세/일봉/기술지표/뉴스/DART) | 🟡 일부 구현 | 종목검색·현재가는 `/user/trading` 내 위젯, 뉴스/공시는 `/user/news`, `/user/disclosures` 개별 페이지 | `market_data_router.py`, `prices.py`, `news.py`, `dart.py`, `indicators.py` | 다수 | "시장 정보" 상위 메뉴로 통합되어 있지 않고 개별 페이지에 분산 | 메뉴 구조 재편 시 통합 고려 |
| 시장 정보 - 업비트(KRW마켓/캔들/기술지표/뉴스) | ❌ 미구현(User 화면) | 전용 페이지 없음. `/user/trading`의 거래소 Select에 `UPBIT` 항목만 존재 | `upbit.py`(Backend는 존재) | - | User용 업비트 전용 조회 화면 없음 | 신규 화면 필요 |
| 매매 후보(주식/업비트/LLM) | 🔌 API는 있으나 User 화면 미연결 | 없음 | `candidates.py`, `ai_candidates.py`, `position_candidates.py` | `candidate_run` 등 | User 사이드바에 "매매 후보" 메뉴 자체가 없음(`/user/ai`가 유사 역할 추정, 명칭 불일치) | 메뉴/라우트 신설 |
| 내 전략(전략 연결/설정/백테스트) | ⚠ 권한 구조 문제 | `(user)/user/strategies/page.tsx` | `strategy_deployment.py`, `strategy_runtime.py`, `strategy_selector.py`, `realtime_strategy.py` — **전부 `require_admin`** | `strategy_deployment` 등 | 일반 회원(viewer)은 이 화면의 대부분 액션에서 403. 사용자 소유 전략-계좌 연결 모델(user_id 컬럼) 자체가 없음 | Critical — 사용자용 전략 연결 API/테이블 신설 필요 |
| 자동매매 설정(계좌별 리스크·손절/익절 등) | 🔌 부분적 | 화면 내 일부 노출 확인 안 됨 | `risk.py`,`risk_policies.py`는 **admin 전용**(공통 정책). 계좌별 개별 설정 API 위치 불명확 | - | 사용자가 본인 계좌 단위로 손절률 등을 설정하는 전용 API를 찾지 못함 | 후속 코드 조사 필요 |
| 내 주문·체결(Paper) | ✅ 완료 | `/user/trading` 내 미체결/체결 테이블 | `paper_orders.py`, `order_execution.py`, `executions.py` | `paper_order`, `paper_trade` | 소유권 검사(`assert_paper_account_access`, `assert_trading_account_access`) 일관 적용 | - |
| 내 주문·체결(Kiwoom Live) | ✅ 완료(경로만) | 동일 화면 LIVE 모드 | `order_execution.py`(`/order-execution/submit`) — Risk+KillSwitch 강제 | `trading_order` | 직접 `/orders` POST는 의도적으로 차단(가드 우회 방지) — 설계상 정상 | - |
| 잔고·손익(통합/주식/코인) | 🟡 일부 구현 | `/user/portfolio` | `user_portfolio.py` | `paper_position` | 소유권 검사 적용됨. Kiwoom/Upbit 실잔고까지 통합 표시되는지 미확인 | 통합 자산 뷰 검증 |
| 내 리포트(일일/손익/전략성과) | ❌ 미구현 | 전용 메뉴/라우트 없음(`userRoutes`에 reports 없음) | `daily_reports.py`는 **admin 전용** | - | 사용자 전용 리포트 API/화면 부재 | 신규 구현 필요 |
| 알림 | ✅ 완료 | `/user/notifications` | `user_notifications.py` | - | `user.user_id` 소유권 일관 적용 | - |
| 내 정보/설정 | ✅ 완료 | `/user/profile`, `/user/settings` | `auth/profile_service.py`, `user_settings.py` | - | 없음 | - |
| 관심종목 | ✅ 완료 | `/user/watchlist` | `user_watchlist.py` | - | 소유권 적용 | - |

## 9.3 관리자(ADMIN) 기능 결과

| 기능 | 상태 | Frontend 위치 | Backend 위치 | DB | 문제점 | 개선 필요 |
| --- | --- | --- | --- | --- | --- | --- |
| 관리자 대시보드 | ✅ 완료 | `/admin/dashboard` | `admin_dashboard_summary.py`,`system_dashboard.py` | - | 없음 | - |
| 회원관리(목록/등록/활성/잠금/권한) | ✅ 완료 | `/admin/members`, `/admin/roles` | `users.py`(`require_permission("users:*")`), `roles.py` | `auth.user`,`auth.user_role` | 자기 자신 마지막 관리자 권한 제거 방지 로직 확인(`user_admin_service.py:201,207,250`) | - |
| 전체 계좌관리 | ✅ 완료 | `/admin/accounts` | `user_accounts.py`(admin은 `assert_*`에서 우회 허용), 전용 admin 계좌 API | `paper_account`,`user_broker_account` | 없음 | - |
| 시장 데이터 관리(주식/업비트 수집) | 🟡 일부 구현 | `/admin/monitoring`, `/admin/kiwoom`, `/admin/upbit`, `/admin/data`(모니터링으로 리다이렉트) | `market_data_router.py`,`sync.py`,`kiwoom_account_sync.py` | - | "데이터 관리" 메뉴가 사실상 모니터링 화면에 흡수됨(`routes.ts` 주석: "실체 페이지 없음") | 목표 메뉴와 1:1 대응 필요 시 재편 |
| 전략관리 | ✅ 완료(Admin 기준) | `/admin/strategies` | `strategy_deployment.py`,`strategy_runtime.py`,`strategy_selector.py`,`strategy_performance*.py` — 전부 admin 전용 | `strategy_deployment` 등 | User 쪽에서 재사용되며 발생하는 403 문제(9.2 참조)의 근본 원인이 이 라우터 자체가 완전 admin-only이기 때문 | - |
| 후보·LLM 관리 | ✅ 완료 | `/admin/ai` | `ai_candidates.py`,`ai_analysis.py`,`ai_orchestration.py` | - | 없음 | - |
| 주문·체결 모니터링(전체) | ✅ 완료 | `/admin/orders`,`/admin/trades` | `broker_orders.py`(`require_admin` 라우터 전체), `order_states.py`,`order_outbox.py` | - | 없음 | - |
| 잔고·손익 모니터링(사용자별) | 🟡 일부 구현 | `/admin/portfolio`,`/admin/positions`(레거시 리다이렉트) | `portfolio_backtests.py` 등 | - | "사용자별 자산" 전용 admin API 명시적으로 확인 못함 | 후속 확인 |
| 리스크관리(공통 정책·킬스위치) | ✅ 완료 | `/admin/risk` | `risk.py`,`risk_policies.py`,`kill_switch.py` — 전부 router-level `require_admin` | `kill_switch_history` 등 | 킬스위치는 시스템 전역 스코프(계좌별 아님) — 목표 스펙(계좌별 리스크 포함)과 일부 차이 | - |
| 스케줄러·작업관리 | ✅ 완료 | `/admin/scheduler`,`/admin/batch`,`/admin/operations` | `scheduler_admin.py`,`jobs.py` | - | 없음 | - |
| 장애 복구 | ✅ 완료 | `/admin/operations`(통합 추정) | `broker_recovery.py` | - | 전용 메뉴 대신 운영센터에 통합 | - |
| 리포트 | ✅ 완료(Admin 전용) | 별도 메뉴 미확인(`routes.ts`에 reports 경로 없음) | `daily_reports.py` | - | Frontend 전용 화면 라우트가 안 보임 — API만 존재할 가능성 | 확인 필요 |
| 알림관리(텔레그램) | ✅ 완료 | `/admin/notifications`,`/admin/telegram` | `notifications.py`,`telegram_ops.py` | - | 없음 | - |
| 운영관리(시스템/DB/로그/감사) | 🟡 일부 구현 | `/admin/system-settings`,`/admin/env-settings`,`/admin/logs`,`/admin/db`,`/admin/api`,`/admin/ollama` | `settings.py`,`ops_db.py`,`monitoring.py`,`audit.py`(`require_admin`) | `audit_event` | **감사 로그 전용 메뉴/라우트가 없음** — `audit.py` API는 존재하나 `routes.ts`/`menu.tsx`에 독립 메뉴 항목 없음(다른 화면에 내장 추정) | 감사 로그 전용 화면 신설 검토 |

## 9.4 권한 보안 결과

| API 또는 화면 | 필요 권한 | 실제 권한 검증 | 소유권 검증 | 취약점 | 심각도 |
| --- | --- | --- | --- | --- | --- |
| `GET/POST /api/v1/user/accounts/*` | 로그인 사용자 본인 | `require_permission("trading:read/write")` + `assert_account_access` | ✅ 있음 (`account_ownership.py`) | 없음 | - |
| `POST /api/v1/paper-orders`, `/{id}/fill` 등 | 계좌 소유자 | `require_permission` + `assert_paper_account_access` | ✅ 있음 | 없음 | - |
| `POST /api/v1/order-execution/submit`, `executions.py` | 계좌 소유자 | `require_permission` + `assert_trading_account_access` | ✅ 있음 | 없음 | - |
| `POST /api/v1/orders` (직접 생성) | - | 항상 400 반환(의도적 차단) | 해당없음 | 없음(오히려 안전장치) | - |
| `/api/v1/broker/**`(Kiwoom/Upbit 실주문·계좌 동기화) | ADMIN | 라우터 전체 `dependencies=[Depends(require_admin)]` | 해당없음(공용 계좌) | 없음 | - |
| `/api/v1/strategy-deployments`, `/strategy-runtime/*`, `/realtime-strategy/*`, `/strategy-selector/*` | ADMIN | 라우터 전체 `require_admin` | 해당없음 | **User 화면(`/user/strategies`)이 이 API를 직접 호출** → 일반 회원은 기능 사용 불가(403). 보안 취약점은 아니지만 **기능 결함이자 UX상 권한 설계 오류** | Medium |
| `/api/v1/risk/**`, `/api/v1/risk/kill-switch/activate|deactivate` | ADMIN(변경), 로그인 사용자(조회) | `require_admin`(변경) / `require_authenticated`(조회) | 해당없음(전역 스코프) | 없음 | - |
| `/api/v1/roles`, `/api/v1/roles/users/{id}` | `roles:read`/`roles:write` (사실상 admin만 보유) | `require_permission` | 해당없음 | 없음 — 단, `operator` 역할이 `users:read`를 보유해 회원 목록 조회 가능(관리자 콘솔 진입 가능한 중간 티어) | Low |
| `/api/v1/audit/events` | ADMIN | `require_admin` | 해당없음 | 없음 | - |
| `X-Admin-API-Key` 헤더(`require_admin`,`require_authenticated`) | 서버 env 값과 일치 | `secrets.compare_digest` 상수시간 비교 | 해당없음 | 설계된 백도어(스크립트용) — env 미설정 시 비활성화되므로 자체로는 취약점 아니나, **운영 환경에서 이 키가 유출되면 전체 admin 권한 우회** 가능. 로그·문서에 노출 여부는 미확인 | Medium(운영 관리 필요) |
| 로그인 실패 시 사용자 존재 여부 노출 | - | 동일한 일반 오류 메시지 사용(`"사용자명 또는 비밀번호가..."`)  | - | 없음 — enumeration 방지 잘 되어 있음 | - |
| Refresh Token 재사용 탐지 | - | 재사용 시 해당 유저 전체 세션 revoke(`REFRESH_REUSE`) | - | 없음(오히려 우수 사례) | - |

## 9.5 완성도 점수

### 사용자(USER)

| 항목 | 점수 |
| --- | --- |
| 로그인·권한 | 90 |
| 계좌관리 | 80 |
| 시장 데이터 | 55 (업비트 전용 화면 부재) |
| 전략 | 20 (사용자 소유 모델 자체 부재) |
| 후보 선정 | 15 (User 화면 미연결) |
| 주문·체결 | 85 |
| 잔고·손익 | 65 |
| 리스크 | 40 (계좌별 개인 리스크 설정 API 미확인) |
| 리포트·알림 | 45 (알림은 완료, 리포트는 미구현) |
| **사용자 기능 전체 완성도** | **≈55/100** |

### 관리자(ADMIN)

| 항목 | 점수 |
| --- | --- |
| 회원관리 | 90 |
| 계좌관리 | 80 |
| 데이터 운영 | 65 |
| 전략관리 | 85 |
| 후보·LLM 관리 | 80 |
| 주문 모니터링 | 85 |
| 리스크·킬스위치 | 90 |
| 장애 복구 | 65 (전용 메뉴 없이 통합) |
| 스케줄러 | 80 |
| 로그·감사·알림 | 60 (감사 로그 전용 메뉴 부재) |
| **관리자 기능 전체 완성도** | **≈78/100** |

### 종합

| 항목 | 점수 |
| --- | --- |
| 주식 자동매매 완성도 | 75 |
| 업비트 자동매매 완성도 | 45 (Backend는 준비, User 화면·전용 메뉴 부재) |
| Paper 자동매매 완성도 | 85 |
| **전체 프로젝트 완성도** | **≈65/100** |

---

## 부록 A. 발견된 기타 이슈

- **레거시/중복 패키지**: `src/stock_platform/brokers/`(복수형)와 `src/stock_platform/broker/`(단수형)가 공존. 실 API 라우팅에서는 `broker/`만 사용되고 `brokers/`는 `tests/test_broker_consolidation_step06.py` 등 일부 테스트에서만 참조되는 사실상 죽은 코드로 보임. 완전 삭제 여부는 별도 확인·합의 필요(임의 삭제 금지 원칙에 따름).
- **역할 계층 모호성**: `operator` 역할이 `canAccessAdminPortal()`에서 admin 콘솔 접근을 허용하고 `users:read`, `audit:read`, `ops:execute` 등 민감 권한을 보유. "USER/ADMIN 이분법"을 전제로 한 목표 아키텍처와 정합성 검토가 필요.
- **Frontend Middleware는 최종 방어선이 아님**: `middleware.ts`는 쿠키 부재 시 HTML 네비게이션만 소프트 리다이렉트하며, API 프리페치는 통과시킨다. 실제 권한 경계는 Backend `require_admin`/`require_permission`/소유권 검사에 있으므로 안전하지만, 문서화된 대로 "Frontend Guard만으로 보안 완료로 판단하지 말 것" 원칙에 부합하는 실제 사례임을 확인.

## 부록 B. 조사 신뢰도 메모

시간·리소스 제약상 다음 항목은 표면적 확인에 그쳤으며, 실제 개선 작업 전 추가 조사가 필요합니다.

- 계좌별(개인화) 리스크 설정(손절률, 트레일링 스톱 등)을 사용자가 직접 설정하는 전용 API의 존재 여부 — `risk.py`/`risk_policies.py`가 admin 전용임은 확인했으나, 계좌별 개인 설정이 다른 모듈(`position_limits.py`, `user_settings.py`)에 있을 가능성이 있어 완전히 배제하지 못함.
- Kiwoom/Upbit 실잔고가 사용자 대시보드/포트폴리오 화면에 실제로 통합 표시되는지 여부(브라우저 기동 테스트는 미수행).
- 감사 로그가 어느 admin 화면에 실제로 임베드되어 있는지(코드상 `audit` 문자열이 `admin/api`, `admin/logs`, `admin/monitoring`, `admin/operations` 4개 페이지에서 발견되었으나 렌더링 내용까지는 미확인).

---

## 다음 단계 제안 (수정 대상 후보 — 코드 변경은 미실시)

이번 조사는 STEP 1(조사)에 해당하며 코드를 변경하지 않았습니다. 후속 작업 우선순위는 다음과 같이 제안합니다.

1. **Critical**: `/user/strategies` 화면과 전략 API 간의 권한 모델 불일치 해소 — 사용자 소유 "전략 연결" 개념(테이블/서비스/API) 신설 또는 화면 접근 정책 재정의.
2. **High**: 업비트 전용 사용자 화면(시세·캔들·기술지표) 신설.
3. **High**: 사용자 전용 "내 리포트" API/화면 신설.
4. **Medium**: Role 체계(admin/operator/viewer)를 목표 아키텍처(ADMIN/USER)와 어떻게 매핑할지 의사결정 — `operator`를 유지할지, ADMIN에 흡수할지, USER 내 하위 등급(계좌/설정 기반)으로 전환할지.
5. **Medium**: 감사 로그 전용 관리자 화면 신설 여부 결정.
6. **Low**: `brokers/`(복수형) 레거시 패키지 정리 여부 결정.
