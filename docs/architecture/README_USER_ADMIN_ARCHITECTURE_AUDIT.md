# 사용자·관리자 아키텍처 감사 보고서

> 조사일: 2026-07-22 (재조사)  
> 범위: 코드·API·DB·화면 연결만 (**코드 변경 없음**)  
> 원칙: FE → API → Service → Repository/외부 API 실제 호출 추적. 메뉴·파일명만으로 완료 판정하지 않음.

---

## 9.1 전체 평가

| 항목 | 판정 | 요약 |
|------|------|------|
| 로그인 통합 | ✅ | `/login` 단일. 사용자/관리자 별도 로그인 화면 없음 |
| 권한별 화면 분리 | ✅ / 🟡 | `(user)` / `(admin)` 레이아웃·메뉴 분리. 미들웨어는 토큰 존재만 검사 |
| 사용자 기능 완성도 | 🟡 | 계좌·알림·관심종목·AI·뉴스(유저 API)는 양호. 시세·전략·자동매매·후보 위젯은 Admin API 의존(🔌) |
| 관리자 기능 완성도 | 🟡 ~ ✅ | 회원·리스크·브로커·스케줄러·설정 다수 구현. `/admin/logs` 페이지 없음, Recovery FE 미연동 |
| 주식 통합 | 🟡 | Paper+Kiwoom 경로 존재. **회원별 키움 AppKey/Secret 없음**(서버 env 공용) |
| 업비트 통합 | 🟡 | Admin sync·어댑터 존재. User 전용 업비트 시세/잔고 UI·API 약함. 회원별 Access/Secret 없음 |
| Paper 통합 | ✅ / 🟡 | Paper 계좌·주문·포트폴리오 중심. fill/cancel 소유권 검사 있음 |
| Backend 권한 검증 | ✅ / ⚠ | `get_current_user`·`require_admin`·`require_permission`은 **DB RBAC 재검증**. `require_authenticated`·refresh는 locked 미검사 |
| Frontend Route Guard | ✅ / 🟡 | AuthGuard+roles. 메뉴 숨김만으로는 불충분 → **API 403이 실제 방어선** |

**한줄 결론:**  
「단일 로그인 + User/Admin 화면 분리」골격은 갖춰져 있으나, **일반 사용자 자동매매·시세·전략 화면이 Admin 전용 API에 기대어 연결이 깨져 있고**, **주식·업비트 회원별 실계좌 키 모델이 없어** 요구 구조의 “본인 명의 통합 자동매매”와는 아직 거리가 있다.

---

## 1. 공통 로그인 구조

| 확인 항목 | 결과 | 근거 |
|-----------|------|------|
| 로그인 화면 통합 | ✅ | `frontend/src/app/(auth)/login/page.tsx` + `LoginForm.tsx` |
| 별도 관리자 로그인 | ❌ 없음 (의도적 통합) | `routes.ts`: `adminRoutes.login` = `userRoutes.login` = `/login` |
| 권한별 분기 | ✅ | `roles.ts` `resolvePostLoginPath()` → admin/operator → admin, 그 외 → user |
| JWT만 신뢰하지 않음 | ✅ (대부분) | `auth/deps.py` `get_current_user`·`require_admin`: DB roles/permissions 재조회. 주석: "JWT claim roles 가 아니라 DB RBAC 재검증" |
| 비활성/잠금 로그인 차단 | ✅ | `auth/service.py` `login()` + `user_status.py`. API: `get_current_user` |
| 일반 사용자 `/admin` URL | 🟡 | `middleware.ts`: 토큰만 검사 → URL 진입 가능. `AuthGuard`+`requiredRoles`로 UI 차단 → `/user/dashboard` |
| 관리자 API 일반 사용자 | ✅ (대체로) | `require_admin` → 403. 단 operator+permission은 일부 API 통과 |
| 로그아웃·만료 | ✅ / 🟡 | `interceptors.ts` 401→refresh→실패 시 login. refresh 경로 locked 미검사 |

흐름 증거:

```text
LoginForm → POST /api/v1/auth/login (AuthService.login)
  → JWT access + refresh (DB hash 저장)
  → resolvePostLoginPath(roles)
  → /admin/* 또는 /user/*
요청 시 get_current_user: JWT sub → DB user + RbacRepository
```

---

## 9.2 사용자 기능 결과

| 기능 | 상태 | Frontend | Backend | DB / 비고 | 문제점 | 개선 필요 |
|------|------|-----------|---------|-----------|--------|-----------|
| 대시보드 자산(통합) | 🟡 | `user/dashboard` | `GET /dashboard/admin-summary` | Paper 중심 | Kiwoom/Upbit 자산 미통합. API 응답에 scheduler/jobs/ollama/errors 포함(**정보 노출**) | User 전용 slim KPI API |
| 키움/업비트 자산 위젯 | ❌ / 🔌 | 대시보드 미표시 | Broker sync는 Admin | — | 회원별 live 잔고 user API 없음 | User broker balance API |
| Paper 자산·포지션 | ✅ | dashboard, portfolio | `/paper-accounts/*`, `/user/portfolio/*` | `trading.paper_*` | 단일/선택 Paper | — |
| 오늘/누적 손익 | 🟡 | dashboard KPI | admin-summary / portfolio | Paper | Live 손익 없음 | — |
| 미체결·최근 체결 | 🟡 | dashboard, trades | `/orders`, `/executions`, `/paper-orders` | ownership + account_id | Live broker ID는 Paper ownership 모델과 불일치 가능 | Broker ownership 모델 |
| 자동매매 상태 | 🔌 | dashboard, auto-trading | `/strategy-deployments/active` 등 | 글로벌 | start/stop·realtime은 **require_admin** → 일반 user 403 | User-scoped auto-trading API |
| 경고·알림 | ✅ | `user/notifications` | `/user/notifications/*` | `notification.*` | 대시보드 위젯 없음 | — |
| 관리자 통계 비노출(UI) | 🟡 | dashboard는 KPI만 렌더 | admin-summary | — | **응답 JSON에 운영 필드 포함** | 응답 분리 |
| 계좌 목록/CRUD | ✅ / 🟡 | `user/account` | `/user/accounts/*` | `user_broker_account`, paper | Broker는 메타·마스킹만. 암호화폐 Paper 타입 UI 약함 | crypto paper 타입 |
| 계좌 IDOR | ✅ | — | `assert_account_access` / `_resolve_owned` | — | — | — |
| 키움/업비트 본인 Key 관리 | ❌ | 없음 | 서버 env 공용 | settings | 요구사항(본인 Key)과 불일치 | per-user vault |
| Secret 마스킹 | ✅ | account/profile | `mask_account_number`, hash | — | — | — |
| 시장 시세(주식/업비트) | 🔌 | trading | `/market`, `/prices`, `/realtime-quotes`, `/upbit` | Admin router | 일반 user 403 | User market read API |
| 관심종목 검색 | ✅ | watchlist | `/user/watchlist/search` | — | — | — |
| 뉴스·공시(유저) | ✅ | news, disclosures | `/user/news`, `/user/disclosures` | watchlist 기반 | Dashboard는 Admin `/news` `/dart` 호출(🔌) | Dashboard를 user API로 |
| 전략 목록·연결 | 🔌 | strategies | deploy/stop/update **require_admin** | 글로벌 배포 | User는 active **조회만** | User strategy binding |
| 공용 전략 수정 차단 | ✅ (사실상) | — | admin only | — | User는 수정 불가(403) | — |
| 백테스트 | 🔌 | backtests | `/backtests/*` require_admin | — | 일반 user 403 | User backtest 또는 숨김 |
| 자동매매 계좌별 설정 | ❌ | auto-trading UI | realtime-* admin | — | UnimplementedNotice, per-account 없음 | 설계·API |
| 후보 파이프라인 UI | 🟡 | AI 페이지 ✅ / Dashboard 🔌 | AI: `/user/ai/*`; candidates: admin | — | Dashboard `getTopCandidates` 403 | — |
| 주문 조회·취소 | ✅ / 🟡 | trading, trades | paper + `/orders/{id}/cancel` ownership | — | replace FE 없음 | replace UI |
| 잔고·손익 | 🟡 | portfolio | `/user/portfolio/*` | Paper | Live 미구현 | — |
| 일일 리포트 | ❌ | 없음 | `/daily-reports` admin | — | — | User report 또는 숨김 |
| 알림 구독 | ✅ | notifications, settings | `/user/notifications`, `/user/settings` | — | — | — |

### 사용자 메뉴 (실제 vs 권장)

| 권장 | 실제 (`userMenuItems`) |
|------|------------------------|
| 사용자 대시보드 | ✅ Dashboard |
| 내 계좌(키움/업비트/Paper 하위) | 🟡 「내 계좌」단일 페이지 |
| 시장 정보 주식/암호화폐 | ❌ 별도 메뉴 없음 (매매·관심종목에 혼재) |
| 매매 후보 | 🟡 AI 추천만 (후보 메뉴 없음) |
| 내 전략·자동매매·백테스트 | ✅ 메뉴 있음, API는 🔌 |
| 내 주문·잔고 | ✅ 거래내역·포트폴리오 |
| 리포트 | ❌ |
| 알림·내 정보 | ✅ |

---

## 9.3 관리자 기능 결과

| 기능 | 상태 | Frontend | Backend | 문제점 | 개선 필요 |
|------|------|-----------|---------|--------|-----------|
| 대시보드 전체 현황 | 🟡 | `admin/dashboard` | `GET /dashboard/admin-summary` | **require_admin 아님** (`get_current_user`+계좌 소유권). admin은 전체 조회 | Admin-only aggregate endpoint |
| 회원 CRUD·잠금·권한 | ✅ | members, roles | `/users/*` `users:*`, `/roles/*` | create/update audit 일부 누락 | audit 보강 |
| 마지막 admin 권한 제거 방지 | 🟡 | — | 코드 경로 확인 필요(명시적 last-admin guard 약함) | 실수 방지 강화 | — |
| 전체 계좌 | ✅ | accounts | paper-accounts + broker sync | Upbit reconcile FE→BE 경로 불일치 가능 | API 정합 |
| Secret 원문 비노출 | ✅ | settings password, kiwoom/upbit status | mask_secret | — | — |
| 시장 데이터 운영 | 🟡 | kiwoom, upbit, scheduler | `/upbit/*` **require_admin**, `/sync/*`, jobs | Kiwoom 일봉 sync 전용 FE 약함 | — |
| 전략 배포·성과 | ✅ | strategies | strategy-deployments 등 require_admin | — | — |
| 후보·LLM | 🟡 | ai | candidates, ai-analysis admin | 실행은 스케줄러 의존 | — |
| 리스크·킬스위치 | ✅ | risk | kill-switch activate **require_admin**+audit | GET은 authenticated | — |
| 주문 모니터링 | ✅ | orders, trades | trading:read + admin 전체 | — | — |
| 장애 복구 | 🔌 | **FE 없음** | `/broker/recovery/*` require_admin | — | Admin Recovery UI |
| 스케줄러·작업 | 🟡 | operations, scheduler, batch | jobs, scheduler-admin | backup dump UI 제한 | — |
| 알림·텔레그램 | 🟡 | notifications, telegram | notification + telegram ops | 채널 CRUD·ops FE 약함 | — |
| 감사 로그 | 🔌 | 메뉴 `/admin/logs` **페이지 없음** | `GET /audit/events` require_admin | operations에서 5건 preview | logs 페이지 구현 |
| 시스템 설정 | ✅ | system-settings, env-settings | `/settings*` settings:* + audit | — | — |

### 관리자 메뉴 (실제 vs 권장)

| 권장 | 실제 |
|------|------|
| 회원·계좌·시장·전략·후보·주문·리스크·스케줄러·복구·리포트·알림·감사·설정·상태 | 대부분 메뉴 존재 |
| 장애 복구 | ❌ 메뉴/페이지 없음 (API만) |
| 감사 로그 | 🔌 메뉴만, page 없음 |
| 킬스위치 | ✅ Risk 관리에 포함 |

---

## 9.4 권한 보안 결과

| API 또는 화면 | 필요 권한 | 실제 검증 | 소유권 | 취약점 | 심각도 |
|---------------|-----------|-----------|--------|--------|--------|
| `POST /api/v1/auth/login` | public | status/lock 검사 | — | — | — |
| `GET /api/v1/auth/me` | JWT | `get_current_user` DB | — | — | — |
| `require_admin` 라우터군 (`/upbit/*`, `/sync/*`, pipelines, …) | admin/ops/key | DB RBAC 또는 API Key | — | operator+`ops:execute` 광범위 | Medium |
| `GET /dashboard/admin-summary` | 인증 | ownership (paper) | ✅ | **운영 필드 응답 노출** | High |
| `/user/accounts/*` | JWT | `assert_account_access` | ✅ | — | — |
| `/paper-orders/{id}/cancel|fills` | trading:write | `assert_paper_account_access` | ✅ | — | — |
| `/orders/{id}/cancel|replace` | trading:write | `assert_trading_account_access` | ✅ (Paper 중심) | Broker live ID 불완전 | Medium |
| `/candidates/*`, `/market/*`, `/prices/*` | admin | require_admin | — | User FE가 호출→403 (기능 🔌) | Low (보안상 OK) |
| Kill Switch activate | admin | require_admin + audit | — | — | — |
| Kill Switch GET | authenticated | require_authenticated | — | locked 미검사 | Low |
| `POST /auth/refresh` | refresh JWT | is_active만 | — | **locked 미차단** | Medium |
| `/admin/*` middleware | token | 역할 미검사 | — | URL soft gate | Low |
| AuthGuard admin | admin\|operator | FE roles 캐시 | — | stale role 가능(API는 DB) | Medium |
| `/admin/logs` | menu | — | — | 페이지 없음 | Low |
| Health/version | public | 없음 | — | 정보 노출 제한적 | Low |

---

## 5. 통합 자동매매 프로세스

### 일반 사용자 (요구 vs 실제)

```text
로그인 ✅ → 권한 확인 ✅ → 본인 계좌 선택 ✅(Paper/Broker 메타)
→ 전략·자동매매 설정 🟡/🔌 (조회만·Admin API)
→ 시장·후보 조회 🔌 (Admin API) / AI 후보 ✅
→ 리스크 검증 ✅ (주문 경로 Kill Switch/Risk)
→ 주문 실행 🟡 (Paper 중심; Live는 게이트·ownership 제한)
→ 주문·잔고·손익 ✅(Paper)
→ 손절·익절 감시 🔌 (exit monitor는 서버 lifecycle, User UI 약함)
→ 리포트·알림 🟡 (알림 ✅, 일일 리포트 ❌)
```

### 관리자

```text
로그인 ✅ → DB RBAC ✅ → 시스템 상태 🟡
→ 회원·계좌·전략 ✅ → 데이터 수집 🟡 → 후보·LLM 🟡
→ 주문 모니터링 ✅ → 리스크·KS ✅ → 복구 🔌 → 로그·알림 🟡
```

---

## 6–7. Backend / Frontend 계층

| 계층 | 분리 상태 |
|------|-----------|
| Router | ✅ `/user/*` vs admin routers (`require_admin` / `users:*`) |
| DTO/Service | ✅ 대체로 분리. dashboard summary는 공용 서비스 |
| RBAC | ✅ DB 재검증 (`deps.py`) |
| Ownership | ✅ user accounts, paper, portfolio, notifications |
| Audit | 🟡 KS·settings·일부 user ops. 회원 CRUD 일부 누락 |
| FE 레이아웃 | ✅ `(user)` / `(admin)` |
| Route Guard | ✅ AuthGuard. middleware는 token only |
| 401/403 | ✅ interceptor. 403은 logout 안 함(의도) |
| 컴포넌트 중복 | 🟡 admin/user 페이지 분리, API 클라이언트가 admin 경로를 user가 재사용(🔌 원인) |

---

## 9.5 완성도 점수 (100점)

### 사용자

| 항목 | 점수 |
|------|------|
| 로그인·권한 | 85 |
| 계좌관리 | 70 |
| 시장 데이터 | 35 |
| 전략 | 25 |
| 후보 선정 | 55 |
| 주문·체결 | 65 |
| 잔고·손익 | 60 |
| 리스크(본인) | 40 |
| 리포트·알림 | 55 |
| **사용자 전체** | **약 54** |

### 관리자

| 항목 | 점수 |
|------|------|
| 회원관리 | 85 |
| 계좌관리 | 80 |
| 데이터 운영 | 70 |
| 전략관리 | 80 |
| 후보·LLM | 65 |
| 주문 모니터링 | 80 |
| 리스크·킬스위치 | 85 |
| 장애 복구 | 35 |
| 스케줄러 | 75 |
| 로그·감사·알림 | 55 |
| **관리자 전체** | **약 71** |

### 종합

| 항목 | 점수 |
|------|------|
| 주식 자동매매 | 55 |
| 업비트 자동매매 | 50 |
| Paper 자동매매 | 75 |
| **전체 프로젝트** | **약 58** |

---

## 우선 개선 권고 (구현은 다음 단계)

1. **Critical/High:** `admin-summary` 운영 필드 User 응답에서 제거 또는 User KPI API 분리  
2. **High:** User 화면의 Admin API 호출을 User-scoped API로 교체하거나 메뉴/기능 숨김  
3. **High:** refresh/`require_authenticated`에 locked 상태 검사  
4. **Medium:** 회원별 브로커 키 vault(요구 구조와의 정합) 또는 제품 스펙을 “서버 공용 키”로 명시  
5. **Medium:** `/admin/logs` 페이지, Recovery UI, 회원 CRUD audit  
6. **Low:** middleware 역할 soft gate, FE `/auth/me` hydrate

---

## 조사에 사용한 주요 경로

- FE: `frontend/src/app/(auth|user|admin)/`, `config/routes.ts`, `config/menu.tsx`, `AuthGuard.tsx`, `middleware.ts`, `features/auth/*`, `features/user/api/userApi.ts`, `features/admin/api/adminApi.ts`
- BE: `auth/deps.py`, `auth/service.py`, `auth/user_status.py`, `api/v1/auth.py`, `user_accounts.py`, `user_*`, `paper_*`, `order_*`, `kill_switch.py`, `upbit.py`, `admin_dashboard_summary.py`, `router.py`

---

*본 문서는 조사 전용이며 코드 변경을 포함하지 않습니다.*
