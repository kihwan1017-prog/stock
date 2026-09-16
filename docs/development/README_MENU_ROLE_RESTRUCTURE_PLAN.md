# 메뉴·Role 재구성 계획 (STEP 1 조사)

**작성일:** 2026-07-22  
**범위:** Frontend 메뉴·Route Guard + Backend Role·소유권 (코드 수정 없음)  
**목표 Role:** `ADMIN` / `USER` 두 개만 (세분 Role 신설 금지)  
**후속:** STEP 2~7은 본 계획 승인 후 단계별 진행

---

## 1. 조사 요약 (한 줄)

현재 시스템은 **`admin` / `operator` / `viewer` 3단계 RBAC**이며, 제품 목표의 `ADMIN`/`USER`와 이름이 다르다. Frontend 메뉴는 업무 프로세스(계좌→시장→후보→전략→주문→잔고→리스크→리포트)가 아니라 **기능·기술 단위**로 흩어져 있고, 키움·업비트·Paper는 화면이 분산되어 있다.

| 목표 개념 | 현재 코드/DB 값 | 비고 |
|-----------|-----------------|------|
| ADMIN | `admin` | 소문자 시드. `require_admin_user`는 admin만 |
| USER | `viewer` (+ alias `user`→viewer) | 회원가입 기본 역할 |
| (제거 대상) | `operator` | Admin 포털·`require_admin`(ops:execute) 통과 |
| (미사용) | SUPER_ADMIN, MANAGER, TRADER(시드), VIEWER(대문자), GUEST | Python Enum 없음. FE에 `trader` 별칭만 |

---

## 2. 현재 vs 목표 대비표

| 구분 | 현재 구조 | 목표 구조 | 수정 대상 | 주의사항 |
|------|-----------|-----------|-----------|----------|
| Role 모델 | DB 시드 `admin`/`operator`/`viewer`. `ALLOWED_ROLES` 3개. alias `user`→`viewer` | `ADMIN`/`USER`만 (코드값은 기존 소문자 유지 권장: `admin`/`user` 또는 `admin`/`viewer`→`user` 매핑) | `user_admin_service.py`, RBAC 시드 마이그레이션, `roles.ts`, `roles.test.ts`, `test_rbac.py`, `test_user_admin.py` | operator 사용자 마이그레이션 정책 필요(→admin 승격 vs user 강등). Permission(`menu:*`,`ops:execute`)은 Role 축소 후에도 당분간 유지 가능 |
| 로그인 | 통합 `/login` 이미 존재 | 통합 로그인 유지 | `LoginForm.tsx`, `useAuth.ts` | 변경 최소 |
| 로그인 후 Redirect | `resolve_default_route`: admin\|operator→`/admin/dashboard`, else→`/user/dashboard`. FE `resolvePostLoginPath`도 동일 | USER→`/user/dashboard`, ADMIN→`/admin/dashboard` | `user_status.py`, `roles.ts` | operator 제거 후 분기 단순화. password/onboarding 우선순위 유지 |
| JWT vs DB | `get_current_user`가 DB RBAC 재로드. JWT roles는 편의용 | 동일 원칙 유지·강화 | `deps.py` | JWT Role Claim만으로 `require_admin` 통과하는 코드는 이미 없음 |
| `require_admin` | admin **또는** `ops:execute`(operator) 또는 Admin API Key | 민감 운영은 **admin만** (`require_admin_user`와 정렬) | `deps.py`, 다수 라우터 dependencies, `test_auth_deps_step52.py` | operator가 쓰는 ops API 일괄 차단됨 → 기존 operator 계정 영향 |
| 소유권 | `assert_paper_account_access`, `assert_trading_account_access`, `assert_broker_account_access`, `assert_account_access` | 동일 + 주문·전략·리포트 소유권 보강 | `account_ownership.py`, `order_cancel_replace.py`, user strategies API | 전략은 `/user/strategies`가 **전역 읽기** 위주 — 계좌별 연결 ownership 부족 |
| FE Role 상수 | `ROLE_ADMIN`/`OPERATOR`/`VIEWER`, ProductRole viewer\|trader\|admin | admin / user 두 티어 | `roles.ts`, `permissions.ts`, AuthGuard, layouts | `canAccessAdminPortal`에서 operator 제거 |
| Admin Layout 가드 | `requiredRoles={["admin","operator"]}` | `["admin"]`만 | `(admin)/layout.tsx` | |
| User Layout 가드 | `requiredRolesForUserPath` → 항상 undefined (경로 게이트 비활성). **admin도 /user 접근 가능** | 정책 확정: ADMIN→`/admin/dashboard` 강제 여부 | `(user)/layout.tsx`, `roles.ts`, AuthGuard | 스펙: “정책에 따라 admin→admin dashboard”. **권장: ADMIN의 /user 직접 접근은 차단·리다이렉트** |
| Middleware | 쿠키/Bearer 유무만 검사. Role 미검사 | Soft gate 유지 + 클라이언트 Role 가드 강화 | `middleware.ts` | Next **16.2.10**, `proxy.ts` 없음 — middleware 유지 |
| USER 메뉴 | 플랫 17항목: dashboard, account, trading, auto-trading, strategies, backtests, portfolio, watchlist, trades, ai, market, news, disclosures, notifications, reports, settings, profile | 업무 흐름 트리: 대시보드→내 계좌(키움/업비트/Paper)→시장→후보→전략→주문→잔고→리스크→리포트→알림→내 정보 | `menu.tsx`, `routes.ts`, 신규/이동 page.tsx | 존재하지 않는 하위 링크 금지. 미구현은 `준비 중` |
| ADMIN 메뉴 | permission 기반 그룹: 개요/사용자/거래/전략·AI/콘텐츠/리스크·운영/브로커/시스템 | 회원→전체계좌→시장데이터→지표→후보·LLM→전략→주문→잔고→리스크→스케줄러→복구→리포트→알림→운영→내 정보 | `menu.tsx`, `routes.ts`, admin pages | 키움/업비트 전용 메뉴를 “계좌·주문·시장데이터” 하위로 통합 |
| USER Route | `/user/account`, `/user/trading`, `/user/market` 등 | `/user/accounts/*`, `/user/markets/*`, `/user/candidates/*`, `/user/orders`, `/user/risk` 등 | App Router pages + redirects | 기존 URL → 신규 Redirect 권장 |
| ADMIN Route | `/admin/members`, `/admin/kiwoom`, `/admin/upbit` 등 | `/admin/users`, `/admin/market-data`, `/admin/recovery` 등 (점진) | routes + redirects | 일괄 rename보다 alias/redirect 우선 |
| 계좌 유형 | `AccountType`: PAPER / KIWOOM / UPBIT. Live는 env 게이트 | Role과 분리. Market/Broker/AccountType 분류 | enum 재사용, FE 필터 props | `KIWOOM_LIVE` 등 새 Enum 중복 생성 금지. Live 주문 env 유지 |
| 대시보드 | User: Paper/admin-summary 중심. Admin: 시스템 요약 | 스펙 위젯 세트 | dashboard pages | API 없으면 Mock 금지 → 준비 중 |
| 테스트 | FE `roles.test.ts`(operator 포털). BE `test_rbac`, ownership IDOR | ADMIN/USER·Redirect·IDOR·JWT 변조 | 다수 테스트 갱신 | Skip으로 통과 금지 |

---

## 3. Role·로그인·Redirect 상세

### 3.1 Backend Role

| 항목 | 위치 | 내용 |
|------|------|------|
| 허용 집합 | `src/stock_platform/auth/user_admin_service.py` | `ALLOWED_ROLES = {"admin","operator","viewer"}` |
| Alias | 동일 | `"user"` → `"viewer"` |
| 시드 | `database/alembic/versions/e3f4a5b6c7d8_create_rbac_tables.py` | 3역할 + permission |
| viewer 거래권 | `n1b2c3d4e5f6_grant_trading_write_to_viewer.py` | `trading:write` 부여 |
| 상태 컬럼 | `l8a9b0c1d2e3_...` | lock/onboarding — Role 변경 없음 |
| default_route | `auth/user_status.py` | admin\|operator → `/admin/dashboard` |

### 3.2 인증 Dependency

| 함수 | 파일 | 판정 |
|------|------|------|
| `get_current_user` | `auth/deps.py` | JWT `sub` → DB 사용자 → inactive/deleted/locked 거부 → **RBAC 테이블에서 roles/permissions 재로드** |
| `require_admin_user` | 동일 | `"admin" in roles`만 |
| `require_admin` | 동일 | admin **또는** `ops:execute` **또는** Admin API Key |
| `require_permission` | 동일 | permission 코드 (admin 우회) |

### 3.3 Frontend 로그인 분기

1. `POST /auth/login` → 토큰·user(roles, defaultRoute, passwordChangeRequired, onboardingCompleted)
2. `useAuth.loginWithCredentials` → `resolvePostLoginPath`
3. 우선순위: 비밀번호 변경 → 온보딩 → `next` 권한 검증 → `defaultRoute` → Admin/User 대시보드

통합 로그인(`/login`)은 이미 충족. **변경 포인트는 Role 집합과 Redirect 조건에서 operator 제거.**

### 3.4 차단 상태 (이미 존재)

- 비활성(`is_active=False`), 탈퇴(`deleted_at`), 잠금(`locked_until`) → 로그인/`get_current_user` 거부
- USER가 `/admin` 직접 입력 → AuthGuard → `/user/dashboard` 또는 `/forbidden`
- USER가 Admin API 호출 → Backend `require_admin`/`users:*` → 403 (단, 현재는 operator도 일부 통과)

---

## 4. Layout·메뉴·페이지 목록

### 4.1 Layout

| 영역 | 경로 | 가드 |
|------|------|------|
| Auth | `frontend/src/app/(auth)/` | 없음(공개) |
| User | `frontend/src/app/(user)/layout.tsx` | AuthGuard (역할 경로 게이트 사실상 비활성) |
| Admin | `frontend/src/app/(admin)/layout.tsx` | AuthGuard `admin\|operator` + menu permission |

### 4.2 현재 USER 메뉴 (`userMenuItems`)

| Label | Path | API 연결 수준 |
|-------|------|----------------|
| Dashboard | `/user/dashboard` | 실연동 (Paper/summary) |
| 내 계좌 | `/user/account` | 실연동 (Paper·Broker) |
| 매매 | `/user/trading` | 실연동 (SSE 일부 TODO) |
| 자동매매 | `/user/auto-trading` | 부분 (스케줄·킬스위치 UnimplementedNotice) |
| 전략 | `/user/strategies` | 부분 (배포 삭제 등 stub) |
| 백테스트 | `/user/backtests` | 실연동 |
| 포트폴리오 | `/user/portfolio` | 실연동 (Paper 중심) |
| 관심종목 | `/user/watchlist` | 실연동 |
| 거래내역 | `/user/trades` | 실연동 |
| AI 추천 | `/user/ai` | 실연동 |
| 시장정보 | `/user/market` | 실연동 (주식·업비트) |
| 뉴스 | `/user/news` | 부분 (AI 요약 준비 중) |
| 공시 | `/user/disclosures` | 실연동 |
| 알림 | `/user/notifications` | 실연동 |
| 내 리포트 | `/user/reports` | 부분 |
| 설정 | `/user/settings` | 실연동 |
| 내 정보 | `/user/profile` | 실연동 |

**없음 (목표 대비):** 계좌 하위 트리(키움 실/모의, 업비트, Paper 주식/코인), 매매 후보 전용, 내 리스크 전용, 주문·체결을 브로커별로 나눈 메뉴, 기술지표 전용.

### 4.3 현재 ADMIN 메뉴 (요약)

개요(dashboard, monitoring) · 사용자(members, roles) · 거래(accounts, trading, orders, trades, portfolio) · 전략·AI · 뉴스/공시 · 운영(operations, risk, scheduler, batch, notifications, telegram) · 브로커(kiwoom, upbit) · 시스템(settings, logs, db, api, ollama, docs).

**없음 (목표 대비):** 시장 데이터 수집 전용 트리, 기술지표 관리, 후보·LLM 관리 분리, 장애 복구(`/admin/recovery`), 감사 로그 전용 메뉴, ADMIN `내 정보`(`/admin/profile`).

### 4.4 키움·업비트·Paper 화면 현황

| 시장/브로커 | USER | ADMIN | 비고 |
|-------------|------|-------|------|
| 키움 | `/user/account`, `/user/trading`(broker KIWOOM) | `/admin/kiwoom` | 실주문은 env `KIWOOM_LIVE_ORDER_ENABLED` 등 게이트 — **변경 금지** |
| 업비트 | `/user/market`, profile 연결 요약 | `/admin/upbit` | 실주문 별도 활성화 없으면 차단 유지 |
| Paper | account/trading/dashboard/portfolio/trades/reports | accounts/orders/portfolio | 사용자 거래의 주력 경로 |

공통 컴포넌트에 `marketType`/`brokerType`/`accountType`을 넘기는 통합 패턴은 **부분적**이며, 메뉴 레벨에서는 브로커별 페이지가 Admin에 분리되어 있다.

---

## 5. 소유권·API Gap

| 영역 | 현재 | Gap |
|------|------|-----|
| Paper 계좌/주문 | `assert_paper_account_access` 적용 | 양호 |
| Broker 연결 | `assert_broker_account_access` | 양호 |
| 주문 cancel/replace | `_assert_order_owner` → trading account | 양호 |
| User portfolio | paper ownership | 양호 |
| User strategies | `trading:read` 위주, **전역 전략 목록** | 계좌별 전략 연결·본인 한정 부족 |
| 리포트 | 사용자 범위 API 혼재 | `assert_report_access` 명명 함수 없음 — 필요 시 기존 패턴으로 추가 |
| Admin API prefix | `/api/v1/...` flat + `require_admin` | `/api/admin` 분리 없음 — **필수 아님**, 가드 강화로 충분 |

---

## 6. URL 변경 영향

### 6.1 권장 전략

1. **1차:** 메뉴 라벨·그룹·사이드바만 업무 순서로 재배치. 기존 path 유지 + 하위 탭/쿼리로 브로커 필터.
2. **2차:** 목표 path(`/user/accounts`, `/user/orders` 등) 추가 후 **구 path → 신 path Redirect**.
3. `routes.ts`의 기존 alias 패턴(`market`→monitoring 등)을 재사용.

### 6.2 Redirect 후보 (STEP 4~6)

| 기존 | 신규(목표) | 우선순위 |
|------|------------|----------|
| `/user/account` | `/user/accounts` | 높음 |
| `/user/trades` | `/user/orders` | 중 |
| `/user/portfolio` | `/user/portfolio`(유지) 또는 잔고·손익 하위 | 중 |
| `/user/ai` + candidates | `/user/candidates/*` | 중 |
| `/admin/members` | `/admin/users` | 낮음(alias) |
| `/admin/kiwoom`,`/admin/upbit` | 계좌·시장데이터 하위로 메뉴만 이동, path 유지 가능 | 중 |

---

## 7. Migration 필요 여부

| 항목 | 필요? | 내용 |
|------|-------|------|
| Role 코드 rename (`viewer`→`user`) | **선택** | 문서/FE는 USER로 표기하고 DB는 `viewer` 유지하는 **호환 매핑**이 안전. rename 시 Alembic + dual write |
| `operator` 제거 | **권장(정책 확정 후)** | 기존 `user_role` 행을 `admin` 또는 `user/viewer`로 이전하는 data migration + downgrade |
| Permission 시드 | 당분간 유지 | 메뉴 permission 필터는 Admin 세분화에 유용. Role은 2개여도 permission은 유지 가능 |
| AccountType Enum | 불필요 | PAPER/KIWOOM/UPBIT 재사용. Live/Mock은 계좌·환경 플래그 |

**충돌 포인트:** `n1b2c3d4e5f6`가 viewer에 `trading:write`를 준 상태 — USER(=viewer) 본인 매매와 정합. operator 제거 시 Admin 전용 ops만 admin에 남기면 됨.

---

## 8. 테스트 영향

| 구분 | 파일 | 영향 |
|------|------|------|
| FE | `features/auth/utils/roles.test.ts` | operator 포털·trader 티어 assert 전면 수정 |
| FE | `LoginForm.test.tsx` | Redirect path assert 보강 권장 |
| BE | `tests/test_rbac.py`, `test_user_admin.py` | ALLOWED_ROLES 2개화 |
| BE | `tests/test_auth_deps_step52.py` | `require_admin`이 operator 거부하도록 변경 시 수정 |
| BE | `tests/test_auth_user_status.py` | default_route |
| BE | `tests/test_step65_user_accounts.py` 등 | ownership — Role rename 시 fixture 역할명 |
| E2E | `frontend/e2e/smoke.spec.ts` | 메뉴 라벨·path 변경 시 갱신 |

---

## 9. STEP별 수정 대상 파일 (확정 초안)

### STEP 2 — Role 정리

- `src/stock_platform/auth/user_admin_service.py`
- `src/stock_platform/auth/user_status.py`
- `src/stock_platform/auth/deps.py` (`require_admin` ↔ `require_admin_user` 정렬)
- `src/stock_platform/auth/rbac_repository.py` (alias)
- 신규 Alembic (operator 이전·선택적 viewer→user)
- FE: `roles.ts`, `roles.test.ts`, `(admin)/layout.tsx`
- 관련 BE 테스트

### STEP 3 — 로그인 분기

- `frontend/src/features/auth/hooks/useAuth.ts`
- `frontend/src/features/auth/utils/roles.ts` (`resolvePostLoginPath`)
- `frontend/src/features/auth/components/LoginForm.tsx` (필요 시)
- Backend `resolve_default_route` (STEP 2와 연동)

### STEP 4 — Layout·메뉴

- `frontend/src/config/menu.tsx`
- `frontend/src/config/routes.ts`
- `(user)/layout.tsx`, `(admin)/layout.tsx`
- `MainLayout` / 모바일 메뉴 컴포넌트
- 신규 placeholder pages (미구현 명시)

### STEP 5 — Route Guard

- `AuthGuard.tsx`
- `middleware.ts` (Role은 클라이언트 중심, soft gate 유지)
- `/forbidden`, ADMIN→USER 정책 Redirect
- API interceptor 401/403 (`lib/api/interceptors.ts`)

### STEP 6 — 업무 프로세스 화면 연결

- User: accounts / markets / candidates / strategies / orders / portfolio / risk / reports
- Admin: users / accounts / market-data / indicators / candidates / strategies / orders / portfolio / risk / jobs / recovery / reports / notifications / system
- API: `userApi.ts`, `adminApi.ts` — **Mock 대체 금지**
- 키움·업비트·Paper Adapter 로직 **미변경**

### STEP 7 — 테스트

- 섹션 8 목록 + 신규 케이스 (잘못된 Role, JWT 변조, IDOR, 메뉴 링크 유효성)

---

## 10. 미구현·준비 중으로 남을 가능성이 큰 항목

조사 기준, **메뉴만 만들고 API가 없거나 부분적인 것**은 STEP 6에서 완료 처리하지 않고 `준비 중` + 사유 표시:

| 영역 | 사유 |
|------|------|
| USER 기술지표 전용 화면 | 시장 페이지에 부분 포함, 전용 UI/API 빈약 |
| USER 매매 후보(주식/업비트) 분리 | AI/candidates Admin 중심 |
| USER 내 리스크(한도·트레일링) | Admin risk·계정 설정에 분산 |
| ADMIN 장애 복구 전용 | operations에 일부, recovery 라우트 없음 |
| ADMIN 시장 데이터 수집 트리 | monitoring/pipelines에 분산 |
| 뉴스 AI 요약 | UI에 이미 준비 중 |
| 전략 성과 집계 리포트 | reports UnimplementedNotice |
| Backup/Restore 등 | operations Backend 미구현 문구 |

---

## 11. 작업 안전 체크리스트 (전 STEP 공통)

- [ ] 자동매매·Adapter 로직 삭제/병합 금지
- [ ] `KIWOOM_LIVE_ORDER_ENABLED` / Upbit live / Global live 기본 차단 유지
- [ ] Secret·API Key 화면 노출 금지
- [ ] USER 타인 ID로 데이터 접근 차단 (FE 숨김만으로 완료 금지)
- [ ] 테스트 Skip으로 통과 금지
- [ ] Migration downgrade 경로 고려
- [ ] 새 Markdown은 `docs/` 하위 (본 문서 위치: `docs/development/`)

---

## 12. STEP 1 완료 조건 체크

- [x] 현재 Role·로그인·Layout·Menu·Route·Backend 권한·소유권·화면/API 조사
- [x] 본 계획서 작성 (`docs/development/README_MENU_ROLE_RESTRUCTURE_PLAN.md`)
- [x] 수정 대상 파일 초안 확정 (섹션 9)
- [x] Migration·충돌 정리 (섹션 7)
- [ ] **코드 수정은 하지 않음** (STEP 1 경계)
- [ ] 사용자 확인 후 STEP 2 진행

---

## 13. STEP 2 완료 기록 (2026-07-22)

정책 확정·적용:

1. DB Role 코드: **`admin` / `user`** (`viewer` → `user` rename)
2. 기존 `operator` 계정: **`admin` 승격** 후 operator Role 삭제
3. 레거시 입력 alias: `viewer`→`user`, `operator`→`admin`, `trader`→`user`
4. `require_admin`: **DB admin만** (`ops:execute` 경로 제거). Admin API Key 유지
5. ADMIN의 `/user/*` 접근 정책은 **STEP 5**에서 처리 (본 STEP 미포함)

마이그레이션: `database/alembic/versions/o2c3d4e5f6a7_rbac_admin_user_roles_only.py`

## 14. STEP 3 완료 기록 (2026-07-22)

적용 내용:

1. USER 로그인 → `/user/dashboard`, ADMIN 로그인 → `/admin/dashboard` (`roleHomePath` / `resolve_default_route`)
2. 통합 `/login` 유지 · 이미 로그인 상태에서 `/login` 접근 시 Role별 대시보드로 이동
3. Role 없음·잘못된 Role → 로그인 거부 / `get_current_user` 403 / FE `/forbidden`
4. `defaultRoute`·`next`의 `/admin`은 USER에게 허용하지 않음
5. 비활성·잠금·탈퇴는 기존 로그인/`get_current_user` 차단 유지
6. 토큰 만료 시 interceptor → `/login` (기존)

## 15. STEP 4~7 · 최종 완료 (2026-07-22)

- STEP 4: Layout·메뉴 업무 프로세스 재구성
- STEP 5: Route Guard (ADMIN↔USER 교차 차단, 무효 Role 차단)
- STEP 6: 화면 연결 + 준비 중 명시 (Mock 없음)
- STEP 7: FE/BE 테스트 통과
- 결과 보고서: [README_MENU_ROLE_RESTRUCTURE_RESULT.md](./README_MENU_ROLE_RESTRUCTURE_RESULT.md)


---

## 관련 문서

- [KNOWN_ISSUES.md](../../KNOWN_ISSUES.md) — KI-U11-03, KI-AUTH-*  
- [docs/architecture/README_USER_ADMIN_ARCHITECTURE_AUDIT.md](../architecture/README_USER_ADMIN_ARCHITECTURE_AUDIT.md)  
- 최종 결과 보고(미작성): `docs/development/README_MENU_ROLE_RESTRUCTURE_RESULT.md` (전 STEP 완료 후)
