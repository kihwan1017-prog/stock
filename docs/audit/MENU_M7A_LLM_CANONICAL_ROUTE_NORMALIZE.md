# MENU M7-A — Normalize User LLM Menu to Canonical `/user/ai`

**Date:** 2026-08-15  
**Baseline:** M7-0 `LEGACY_REDIRECT_CLEANUP_DESIGN_READY` · M6_CLOSE `de16a45`  
**Verdict:** `LLM_MENU_CANONICAL_ROUTE_READY_FOR_COMMIT`  
**Commit:** **금지** (완료보고 후 selective)

---

## Before / After

| | Before | After |
|--|--------|-------|
| Sidebar leaf | `/user/candidates/llm` | **`/user/ai`** |
| Label | `LLM 분석` | `LLM 분석` (유지) |
| Menu key | `candidates-llm` | `candidates-llm` (유지) |
| Legacy URL | redirect → `/user/ai` | **동일 redirect 유지** |

```text
BEFORE: Menu → /user/candidates/llm → redirect → /user/ai
AFTER:  Menu → /user/ai
Legacy: /user/candidates/llm → redirect → /user/ai  (page 유지)
```

---

## Contracts retained

| Item | Status |
|------|--------|
| `frontend/.../candidates/llm/page.tsx` | **미수정** · `redirect(userRoutes.ai)` |
| `userRoutes.candidatesLlm` | 유지 (`/user/candidates/llm`) |
| `userRoutes.ai` | 유지 (`/user/ai`) |
| breadcrumb titles for both paths | 유지 (삭제 없음) |
| page 삭제 | **0** |
| route 삭제 | **0** |
| permission / AuthGuard | **delta 0** |
| API / backend | **0** |

---

## Menu integrity

| Check | Result |
|-------|--------|
| duplicate User href | **0** |
| broken leaf page | **0** |
| `/user/ai` page | exists |
| `/user/candidates/llm` page | exists |
| menu leaf `/user/ai` | **1회** |
| menu leaf `/user/candidates/llm` | **0** |

---

## Tests

| Suite | Result |
|-------|--------|
| `menu.test.ts` (incl. M7-A case) | **11 PASS** |
| eslint `menu.tsx` / `menu.test.ts` | **PASS** |
| tsc (menu-related new errors) | **0** |

---

## Out of scope (M7-B+)

Admin/User other DEPRECATE redirects (`/admin/data`, `/user/account`, …) — untouched.

---

## Regression / safety

| Check | Result |
|-------|--------|
| M3-B strategy menu | 유지 (test assert) |
| M4 ops regroup | 미수정 |
| M5 Upbit Hub | 미수정 |
| M6 shared | 미수정 |
| TradingOrder / Outbox / orders API | **0** |
| residual WIP | **미수정** |

---

## Changed files

- `frontend/src/config/menu.tsx`
- `frontend/src/config/menu.test.ts`
- `docs/audit/MENU_M7A_LLM_CANONICAL_ROUTE_NORMALIZE.md` (+ Canonical 갱신)

---

## Next STEP (exactly one)

**M7-B — Document DEPRECATE_REDIRECT sunset list** (page/redirect 삭제 금지)
