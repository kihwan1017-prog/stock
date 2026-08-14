# MENU M3-B — Hidden Strategy Workflow Promotion

**Mode:** NAVIGATION EXPOSURE ONLY · **Verdict:** `MENU_M3B_READY_WITH_LIMITATIONS`  
**Date:** 2026-08-14  
**Baseline:** `bab25d36577f817138830fbb13e78e6af6e401c9` (M3-A)  
**Input SoT:** M1 inventory · M2 IA design (untracked 유지, 본 STEP에서 커밋하지 않음)

> menu entry 추가만. route/page/API/AuthGuard/permission 키 **신규 생성 없음**.  
> commit: `feat(ui): expose strategy workflow navigation` (본 커밋). push 없음.

---

## 1. Precheck

| Route (지시서 표기) | 실제 route | page.tsx | 상태 |
|---------------------|------------|----------|------|
| `/admin/strategy-requests` | `/admin/strategy-requests` | 존재 | ACTIVE (심사 승인/반려 API) |
| `/admin/drafts` | **`/admin/strategy-drafts`** | 존재 | ACTIVE (Draft CRUD/버전) |
| `/admin/portfolio-validations` | `/admin/portfolio-validations` | 존재 | ACTIVE (조합 검증 API) |
| `/user/strategy-requests` | `/user/strategy-requests` | 존재 | ACTIVE (owner 요청 생성) |
| `/user/drafts` | **`/user/strategy-drafts`** | 존재 | ACTIVE (owner 조회 전용) |
| User Portfolio Validation | **없음** | — | 메뉴 미추가 |

`/admin/drafts` · `/user/drafts` page는 **없음**. M1/M2 SoT 실제 경로(`strategy-drafts`)를 승격.

ComingSoon/obsolete 아님. AuthGuard: Admin `requiredRoles=["admin"]` + `enforceMenuPermission`. User: `minAccess=user`, enforceMenuPermission 없음.

---

## 2. Counts

| Portal | top-level before/after | leaf before/after |
|--------|------------------------|-------------------|
| Admin | 10 / **10** | 52 / **55** (+3) |
| User | 12 / **12** | 27 / **29** (+2) |

신규 top-level: **0**

---

## 3. Promoted entries

| Portal | label | route | parent | permission | scope |
|--------|-------|-------|--------|------------|-------|
| Admin | 전략 요청 | `/admin/strategy-requests` | 전략·후보 | (없음, Admin role) | 전역 심사 |
| Admin | 전략 초안 | `/admin/strategy-drafts` | 전략·후보 | (없음, Admin role) | 전역 Draft |
| Admin | 포트폴리오 검증 | `/admin/portfolio-validations` | 전략·후보 | (없음, Admin role) | Admin 전용 |
| User | 전략 요청 | `/user/strategy-requests` | 내 전략 | minAccess=user | owner |
| User | 전략 초안 | `/user/strategy-drafts` | 내 전략 | minAccess=user | owner 조회 |

신규 `menu:strategy_requests` 등 **생성하지 않음** (M2 후보안, 본 STEP 금지).

---

## 4. Workflow 순서 (구현 기준)

Candidate → Strategy Request → Draft → (Admin) Portfolio Validation → Backtest → Paper/Runtime

사이드바:

```text
Admin 전략·후보
  전략 관리 → 전략 요청 → 전략 초안 → 포트폴리오 검증 → 백테스트 → (기존 AI/후보)

User 내 전략
  전략 → 전략 요청 → 전략 초안 → 자동매매 → 백테스트
```

---

## 5. Mutation audit

| 항목 | 수 |
|------|----|
| route 추가/삭제/rename | **0 / 0 / 0** |
| page/component | **0** |
| API/backend | **0** |
| AuthGuard/role | **0** |
| permission 키 | **0** |
| duplicate sidebar | **0** |
| broken leaf | **0** |
| /admin/upbit · Operations · legacy redirect | **0** |

breadcrumb metadata만 `routes.ts` admin title 3건을 메뉴 label과 맞춤 (path 불변).

---

## 6. Limitations

- 지시서 `/admin/drafts`·`/user/drafts`는 실제 경로가 `*-strategy-drafts`
- 신규 menu:* 미생성 → Admin 항목은 기존 직접 URL과 같이 **admin role**로 노출
- page H1(AdminPageShell title)는 영문 유지 (page 수정 금지)
- User Portfolio Validation route 없음 → 미노출
- 전체 tsc는 기존 frontend WIP 오류로 FAIL (M3-B 무관)

---

## 7. Next

**M4 — Operations Consolidation** (승인 후). 자동 진행 금지.
