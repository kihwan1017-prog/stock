# MENU LOW-RISK Cleanup — STEP M3-A

**Mode:** APPLY (sidebar only) · **Verdict:** `MENU_LOW_RISK_CLEANUP_READY_WITH_LIMITATIONS`  
**Date:** 2026-08-14  
**Input:** [MENU_INVENTORY_ADMIN_USER.md](./MENU_INVENTORY_ADMIN_USER.md) · [MENU_IA_CONSOLIDATION_DESIGN.md](./MENU_IA_CONSOLIDATION_DESIGN.md)

> Production 변경은 `frontend/src/config/menu.tsx` (+ focused `menu.test.ts`)만.  
> route / page / API / AuthGuard / permission 키 **변경 없음**. 커밋하지 않음.

---

## 1. 판정

`MENU_LOW_RISK_CLEANUP_READY_WITH_LIMITATIONS`

제한:

- User `candidates/llm` 직결(`path`를 `/user/ai`로 변경)은 route/path 변경에 해당 → **미적용** (M3-B 이후 별도)
- 전체 `tsc --noEmit`은 기존 frontend WIP 3건으로 FAIL (M3-A 파일 무관)
- Admin 10→9 / User 12→8 IA 통합은 **하지 않음** (설계상 M4+)

---

## 2–3. before / after counts

| Portal | Metric | M1 / before | after |
|--------|--------|-------------|-------|
| Admin | top-level | 10 | **10** |
| Admin | leaf | 53 | **52** (monitoring 중복 1건 제거) |
| User | top-level | 12 | **12** |
| User | leaf | 27 | **27** |

---

## 4. Label 변경

| key | before | after |
|-----|--------|-------|
| `dashboard` (Admin) | Dashboard | 운영 대시보드 |
| `members-group` | 회원관리 | 회원·권한 |
| `news` (Admin) | 뉴스관리 | 뉴스 관리 |
| `disclosures` (Admin) | 공시관리 | 공시 관리 |
| `strategies` (Admin) | 전략관리 | 전략 관리 |
| `trading` (User) | 매매(주문 실행) | 매매 실행 |

---

## 5. Menu order

- Admin `시장 데이터`: 업비트 시세 → 기술지표 → 뉴스 → 공시 (monitoring 항목 제거 후 시세/지표를 앞으로)
- Admin `전략·후보`: `전략 관리` · `백테스트`를 AI 클러스터 **앞**으로 이동
- User: `업비트 LIVE 검증`을 `내 전략` 다음 · `내 주문·체결` 앞으로 이동

---

## 6–7. Sidebar hide / monitoring

- **숨김:** Admin `시장 데이터` 하위 `key: monitoring` (path `/admin/monitoring`)
- **유지:** Admin `운영관리` 하위 `key: system-monitoring` (동일 path)
- monitoring 사이드바 노출: **2 → 1**
- `frontend/src/app/(admin)/admin/monitoring/page.tsx` 및 `adminRoutes.monitoring` **유지** (직접 URL 접근 가능)

---

## 8–12. Mutation audit

| 항목 | 수 |
|------|----|
| route 삭제 | **0** |
| page 삭제 | **0** |
| API 변경 | **0** |
| AuthGuard 변경 | **0** |
| permission 키 변경 | **0** (중복 leaf 제거로 `menu:monitoring` 바인딩은 1회만 남음) |

---

## 13–15. 검증

- broken menu (leaf → `page.tsx`): **0**
- duplicate sidebar path: **1 → 0**
- 직접 URL 대상 page 존재: `/admin/upbit`, `/admin/trading`, `/admin/operations`, `/admin/monitoring`, `/admin/operations-dashboard`, `/admin/strategies`, `/user/accounts`, `/user/candidates`, `/user/strategies`, `/user/orders`

---

## 16–17. Tests

- focused vitest: `menu.test.ts` + `opsMonitoringDashboard.test.ts` + `manualIntegrity.test.ts` **PASS**
- eslint `menu.tsx` / `menu.test.ts`: **PASS**
- `npm run typecheck`: **FAIL** (기존 WIP: live-validation page, UpbitNewsNoticeCollectorPanel) — M3-A 미수정

---

## 18–21. Files / Git

Production:

- `frontend/src/config/menu.tsx`
- `frontend/src/config/menu.test.ts`

Docs (본 STEP 기록): Canonical 4종 + 본 파일 + `docs/audit/README.md`

**commit:** `feat(ui): clean up low-risk admin and user navigation` (본 커밋). push 없음.

---

## 22. Next STEP (exactly one)

**M3-B** — Strategy Request / Draft / Portfolio Validation 등 HIDDEN ACTIVE 기능의 메뉴 승격.

M3-A 검토/승인 전 자동 진행 금지.
