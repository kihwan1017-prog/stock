# 메뉴·Role 재구성 결과 보고서

**작성일:** 2026-07-22  
**범위:** STEP 1~7 완료  
**계획서:** [README_MENU_ROLE_RESTRUCTURE_PLAN.md](./README_MENU_ROLE_RESTRUCTURE_PLAN.md)

---

## 1. 변경 전 구조

- Role: `admin` / `operator` / `viewer` 3단계 RBAC
- `require_admin`: admin **또는** `ops:execute`(operator)
- USER 메뉴: 플랫 17항목 (매매·자동매매·AI 등 기능 단위)
- ADMIN 메뉴: permission 기반 기술·운영 단위 그룹
- 로그인 Redirect: admin|operator → `/admin/dashboard`, 그 외 → `/user/dashboard`
- 키움·업비트·Paper: Admin 전용 페이지 + User 계좌·매매·시장에 분산

---

## 2. 변경 후 구조

- Role: **`admin` / `user` 두 개만** (레거시 alias: viewer→user, operator→admin)
- `require_admin`: DB **admin만** (+ Admin API Key)
- USER/ADMIN 메뉴: **업무 프로세스 순서**로 재구성, 레이아웃·사이드바 분리
- 로그인: USER → `/user/dashboard`, ADMIN → `/admin/dashboard`
- ADMIN이 `/user/*` 접근 시 → `/admin/dashboard` 강제 이동
- USER가 `/admin/*` 접근 시 → AuthGuard 차단 → `/user/dashboard`
- 미구현 화면은 Mock 없이 **준비 중 + 사유** 표시

---

## 3. USER 메뉴

| 메뉴 | 경로 | 상태 |
|------|------|------|
| 대시보드 | `/user/dashboard` | 연결 |
| 내 계좌 · 전체/키움/업비트/Paper | `/user/accounts*` | 연결 (필터 공용 뷰) |
| 시장 정보 · 주식/암호화폐 | `/user/markets/*` | 연결 |
| 관심종목·뉴스·공시 | 기존 경로 | 연결 |
| 매매 후보 · 주식/업비트 | `/user/candidates/stocks|crypto` | 준비 중 |
| LLM 분석 | `/user/candidates/llm` → `/user/ai` | 연결 |
| 내 전략·자동매매·백테스트 | 기존 경로 | 연결 |
| 매매(수동) | `/user/trading` | 연결 |
| 내 주문·체결 | `/user/orders` | 연결 (Paper 중심) |
| 키움/업비트 주문 | `/user/orders/kiwoom|upbit` | 준비 중 |
| 잔고·손익 | `/user/portfolio` | 연결 |
| 내 리스크 | `/user/risk` | 준비 중 |
| 리포트·알림·설정·내 정보 | 기존 경로 | 연결 |

---

## 4. ADMIN 메뉴

업무 순: 대시보드 → 회원 → 계좌(키움/업비트 포함) → 시장데이터 → 후보·LLM → 전략 → 주문·잔고 → 리스크 → 스케줄러·운영 → 장애복구 → 알림 → 운영관리 → 내 정보

| 신규/주목 | 경로 | 상태 |
|-----------|------|------|
| 기술지표 관리 | `/admin/indicators` | 준비 중 |
| 장애 복구 | `/admin/recovery` | 준비 중 |
| 내 정보 | `/admin/profile` | 준비 중 |
| 그 외 기존 Admin 페이지 | 기존 경로 | 메뉴 재배치·유지 |

---

## 5. Role 및 권한 검사

| 항목 | 결과 |
|------|------|
| 허용 Role | `admin`, `user` |
| 레거시 매핑 | viewer→user, operator→admin, trader→user |
| JWT Role Claim | 인가에 미사용 — DB RBAC 재검증 |
| `require_admin` | admin만 (`ops:execute` 제거) |
| `require_admin_user` | admin만 (기존) |
| 무효 Role 로그인 | 거부 |
| 무효 Role API | `get_current_user` 403 |

---

## 6. Route 변경

| 구 경로 | 신 경로 |
|---------|---------|
| `/user/account` | `/user/accounts` |
| `/user/market` | `/user/markets/stocks` |
| `/user/trades` | `/user/orders` |
| `/user/strategies/auto` | `/user/auto-trading` |
| `/user/candidates/llm` | `/user/ai` |
| `/user/orders/paper` | `/user/orders` |

신규: `/user/accounts/{kiwoom,upbit,paper}`, `/user/markets/*`, `/user/candidates/*`, `/user/orders/{kiwoom,upbit}`, `/user/risk`, `/admin/indicators`, `/admin/recovery`, `/admin/profile`

---

## 7. Backend 소유권 검사

| 함수 | 상태 |
|------|------|
| `assert_paper_account_access` | 유지 |
| `assert_trading_account_access` | 유지 |
| `assert_broker_account_access` | 유지 |
| `assert_account_access` | 유지 |
| 주문 cancel/replace 소유권 | 유지 |
| User strategies 전역 읽기 | 잔여 Gap (본인 한정 강화는 후속) |

---

## 8. 미구현·준비 중 메뉴

| 화면 | 사유 | 후속(2026-07-23) |
|------|------|------------------|
| USER 주식/업비트 매매 후보 | 사용자용 후보 스코어링 API 없음 | AI 추천 안내 CTA 추가 |
| USER 키움/업비트 주문 조회 | 실계좌 주문 조회 API 미연동 | 유지 |
| USER 내 리스크 | 회원별 리스크 API 없음 | 유지 |
| ADMIN 기술지표 | 전용 관리 UI 없음 | 유지 |
| ADMIN 장애 복구 | (구) ComingSoon | **실연동** `GET/POST /broker/recovery` |
| ADMIN 내 정보 | (구) ComingSoon | **실연동** `/api/v1/user/profile` 재사용 |
| 뉴스 AI 요약 등 | 기존 UnimplementedNotice 유지 | 유지 |

---

## 9. 변경 파일 목록 (주요)

### Backend
- `src/stock_platform/auth/role_codes.py` (신규)
- `user_admin_service.py`, `rbac_repository.py`, `user_status.py`, `deps.py`, `service.py`, `schemas.py`, `models.py`
- `database/alembic/versions/o2c3d4e5f6a7_rbac_admin_user_roles_only.py`
- 관련 tests (`test_rbac`, `test_auth_user_status`, ownership fixtures 등)

### Frontend
- `config/routes.ts`, `config/menu.tsx`, `config/menu.test.ts`
- `features/auth/utils/roles.ts`, `permissions.ts`, `LoginForm.tsx`
- `components/layout/AuthGuard.tsx`, `(user)/layout.tsx`, `(admin)/layout.tsx`
- `components/common/ComingSoon.tsx`
- `features/user/accounts/AccountsView.tsx`, `features/user/market/MarketExplorer.tsx`
- 신규/Redirect pages: accounts*, markets*, candidates*, orders*, risk, admin indicators/recovery/profile

### Docs
- `docs/development/README_MENU_ROLE_RESTRUCTURE_PLAN.md`
- `docs/development/README_MENU_ROLE_RESTRUCTURE_RESULT.md` (본 문서)

---

## 10. DB Migration

| Revision | 내용 |
|----------|------|
| `o2c3d4e5f6a7` | viewer→user rename, operator→admin 승격 후 삭제, JSONB 정규화, default `["user"]` |
| Downgrade | user→viewer rename, operator Role 재생성(권한 세트는 근사) |

**운영 적용:** `alembic upgrade head`

---

## 11. 테스트 결과

| 구분 | 결과 |
|------|------|
| Backend auth/RBAC/ownership 관련 pytest | 통과 |
| Frontend vitest 전체 | **26 files / 70 tests 통과** |
| 메뉴 링크 유효성 (`menu.test.ts`) | 통과 |
| roles / LoginForm | 통과 |

---

## 12. 남은 문제

1. ~~운영 DB migration~~ — 로컬 head(`o2c3d4e5f6a7`) 확인. **다른 환경은 각자 `alembic upgrade head` 필요**
2. User strategies — 공용 데이터 UI 안내 추가. **계좌별 ownership은 `user_id` 스키마 후 가능**
3. USER 후보·주문·리스크·지표·recovery — **실연동 완료** (범위 제한은 화면 안내)
4. **스키마/설계 후속만 남음:**
   - UserBrokerAccount ↔ `trading_order` 실계좌 isolation
   - 회원별 리스크 한도/손절 API
   - Strategy deployment `user_id`
   - Upbit/Paper를 `BrokerRecoveryService` 컴포넌트로 편입
5. Live 주문 안전장치 유지 (`KIWOOM_LIVE_ORDER_ENABLED` 등)
### Follow-up (2026-07-23) — 남은 Gap 추가 해소

| 항목 | 결과 |
|------|------|
| DB Migration `o2c3d4e5f6a7` | 로컬 DB **이미 head 적용 확인** |
| USER 매매 후보 | `GET /api/v1/user/candidates/latest|top/{exchange}` + FE 연동 |
| USER 키움/업비트 주문 | Paper `account_id` + `broker_code` 필터 실조회 (실계좌 isolation 미구현은 안내) |
| Paper 주문 목록 | `account_id` 필터로 실데이터 반환 (빈 목록 스텁 제거) |
| USER 리스크 | 전역 킬스위치 실조회 (회원별 한도는 API 없어 안내) |
| ADMIN 기술지표 | `indicator_daily_batch` job history 실연동 |
| ADMIN Recovery | 업비트 sync/reconcile 버튼 + `POST .../reconcile-orders` 엔드포인트 추가 |
| 전략 소유권 | UI에 공용 데이터 명시 (스키마 `user_id` 없어 필터 불가) |

**여전히 스키마/설계 필요한 항목:** UserBrokerAccount↔주문 isolation, 회원별 리스크 한도, 전략 user_id, Upbit/Paper를 BrokerRecoveryService에 편입.

---

## 채팅 요약용 체크리스트

| 항목 | 결과 |
|------|------|
| ADMIN / USER 두 권한 | 적용 |
| USER 로그인 후 | `/user/dashboard` |
| ADMIN 로그인 후 | `/admin/dashboard` |
| USER 메뉴 | 업무 흐름 재구성 · 계좌/시장 통합 |
| ADMIN 메뉴 | 업무 흐름 재구성 · 운영 분리 |
| 키움 | User 계좌 필터 + Admin `/admin/kiwoom` |
| 업비트 | User 계좌·시장 + Admin `/admin/upbit` |
| Paper | User 계좌·주문·포트폴리오 주력 연결 |
| Backend 권한 | admin만 require_admin |
| 소유권 | Paper/Broker/주문 유지 |
| 테스트 | FE 70 · BE 관련 통과 |
| 미구현 | 후보·실주문·USER 리스크·indicators·recovery·admin profile |
| 보고서 | `docs/development/README_MENU_ROLE_RESTRUCTURE_RESULT.md` |
