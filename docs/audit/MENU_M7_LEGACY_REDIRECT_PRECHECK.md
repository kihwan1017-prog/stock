# MENU M7-0 — Legacy / Redirect Route Cleanup Precheck

**Mode:** READ-ONLY PRECHECK ONLY · **production mutation = 0**  
**Date:** 2026-08-15  
**Baseline:** M6_CLOSE `de16a45` · M5_CLOSE=YES · branch `release/v1.1.0`  
**Verdict:** `LEGACY_REDIRECT_CLEANUP_DESIGN_READY`

> route/page 삭제 · redirect/menu/AuthGuard/permission 변경 · commit/push **금지**.  
> **REMOVE_CANDIDATE = 0** (북마크 호환) · M7 구현은 소형·문서/정규화 위주.

---

## 0. Inventory totals (HEAD `de16a45`)

| Scope | `page.tsx` count |
|-------|-----------------:|
| Admin under `app/(admin)/admin` | **60** |
| User under `app/(user)/user` | **36** |
| Redirect-only pages (`redirect(`) | **12** |
| Redirect chains (A→B→C) | **0** |

Layouts: `(admin)/layout.tsx` · `(user)/layout.tsx` — both wrap `AuthGuard` (role scopes). No per-legacy permission keys found.

---

## 1. Redirect map (actual source → target)

| Source | Target | Mechanism |
|--------|--------|-----------|
| `/admin` | `/admin/dashboard` | `redirect(adminRoutes.dashboard)` |
| `/admin/data` | `/admin/monitoring` | `redirect(adminRoutes.monitoring)` |
| `/admin/market` | `/admin/monitoring` | same |
| `/admin/positions` | `/admin/portfolio` | `redirect(adminRoutes.portfolio)` |
| `/admin/settings` | `/admin/env-settings` | `redirect(adminRoutes.envSettings)` |
| `/user` | `/user/dashboard` | `redirect(userRoutes.dashboard)` |
| `/user/account` | `/user/accounts` | `redirect(userRoutes.accounts)` |
| `/user/market` | `/user/markets/stocks` | `redirect(userRoutes.marketsStocks)` |
| `/user/trades` | `/user/orders` | `redirect(userRoutes.orders)` |
| `/user/strategies/auto` | `/user/auto-trading` | `redirect(userRoutes.autoTrading)` |
| `/user/orders/paper` | `/user/orders` | `redirect(userRoutes.orders)` |
| `/user/candidates/llm` | `/user/ai` | `redirect(userRoutes.ai)` |

**Chains:** none — every hop lands on a real content page.

### routes.ts alias quirk (important)

`adminRoutes.data|market|positions|settings` **already equal** their canonical path strings (`/admin/monitoring` etc.), so new code using those constants **never hits** the `/admin/data` page files.  
Page files remain for **literal URL bookmarks** only.

`legacyUserRoutes` (`account`/`trades`/`market`) exists separately and is marked `@deprecated`.

---

## 2. Classification tallies (all pages)

| Class | Count | Notes |
|-------|------:|-------|
| **KEEP_CANONICAL** | **83** | Menu/workflow content pages (incl. M3-B) |
| **KEEP_REDIRECT** | **3** | `/admin`, `/user`, `/user/candidates/llm` (menu still points to llm) |
| **DEPRECATE_REDIRECT** | **9** | Legacy aliases; keep for bookmarks; document sunset |
| **DETAIL_ONLY** | **1** | `/user/ai` (active page; sidebar uses llm alias) |
| **HIDDEN_ACTIVE** | **0** | — |
| **REMOVE_CANDIDATE** | **0** | Gate failed: external bookmark / low removal value |
| **REVIEW_REQUIRED** | **0** | — |

Redirect-only pages = KEEP_REDIRECT + DEPRECATE_REDIRECT = **12**.

---

## 3. Known legacy candidates (current HEAD)

### Admin

| Route | Kind | Class | Notes |
|-------|------|-------|-------|
| `/admin` | redirect | **KEEP_REDIRECT** | Entry-point |
| `/admin/data` | redirect | **DEPRECATE_REDIRECT** | Literal path only; `adminRoutes.data`→monitoring |
| `/admin/market` | redirect | **DEPRECATE_REDIRECT** | Same pattern → monitoring |
| `/admin/positions` | redirect | **DEPRECATE_REDIRECT** | → portfolio |
| `/admin/settings` | redirect | **DEPRECATE_REDIRECT** | → env-settings (conservative) |

### User

| Route | Kind | Class | Notes |
|-------|------|-------|-------|
| `/user` | redirect | **KEEP_REDIRECT** | Entry-point |
| `/user/account` | redirect | **DEPRECATE_REDIRECT** | → accounts |
| `/user/market` | redirect | **DEPRECATE_REDIRECT** | → markets/stocks |
| `/user/trades` | redirect | **DEPRECATE_REDIRECT** | → orders |
| `/user/strategies/auto` | redirect | **DEPRECATE_REDIRECT** | → auto-trading |
| `/user/orders/paper` | redirect | **DEPRECATE_REDIRECT** | → orders (paper is main orders UX) |
| `/user/candidates/llm` | redirect | **KEEP_REDIRECT** | **Menu still uses** `userRoutes.candidatesLlm` |
| `/user/ai` | **active page** | **DETAIL_ONLY** | Full AI recommendations UI; Links from dashboard/CandidatesView |

### `/user/ai` vs `/user/candidates/llm`

**Pattern A confirmed:** menu → `/user/candidates/llm` → redirect → `/user/ai`.  
`/user/ai` is the real surface; llm is a labeled alias.

---

## 4. M3-B promoted (not legacy)

| Route | Menu | Class |
|-------|:----:|-------|
| `/admin/strategy-requests` | yes | **KEEP_CANONICAL** |
| `/admin/strategy-drafts` | yes | **KEEP_CANONICAL** |
| `/admin/portfolio-validations` | yes | **KEEP_CANONICAL** |
| `/user/strategy-requests` | yes | **KEEP_CANONICAL** |
| `/user/strategy-drafts` | yes | **KEEP_CANONICAL** |

Confirmed via `menu.tsx` + `menu.test.ts`.

---

## 5. Internal references (summary)

| Route / symbol | Production refs (approx) | Class of usage |
|----------------|--------------------------|----------------|
| Literal `/admin/data` | page file only | REDIRECT_ONLY |
| Literal `/admin/positions`,`/admin/settings` | ~0 outside pages | REDIRECT_ONLY |
| `adminRoutes.data|market|positions|settings` | **0** call sites | constants point at canonical paths |
| `userRoutes.candidatesLlm` | menu + routes | ACTIVE_INTERNAL (menu) |
| `userRoutes.ai` | llm redirect · dashboard · CandidatesView | ACTIVE |
| `userRoutes.ordersPaper` / `strategiesAuto` | routes titles mainly | REDIRECT_ONLY / DOC |
| `legacyUserRoutes.*` | deprecated export | DOC / compat |

False positives: substring `/admin/market` matches `market-calendar` API paths — not FE route usage.

**External compatibility:** all DEPRECATE_REDIRECT marked `UNKNOWN_EXTERNAL_COMPATIBILITY` — do not remove without product decision.

---

## 6. Orphan / hidden

| Finding | Result |
|---------|--------|
| Content page with no menu, no inbound, not redirect target | **0** |
| `/user/ai` | DETAIL_ONLY (inbound Links + redirect target) |
| HIDDEN_ACTIVE (intentional secret feature) | **0** |

---

## 7. Permission / AuthGuard impact

| Item | Impact |
|------|--------|
| Removing redirect pages | AuthGuard layouts unchanged; no dedicated `menu:*` for aliases |
| Pointing menu `candidatesLlm` → `userRoutes.ai` | Label/title only; **no** new permission |
| Deleting `adminRoutes.data` constant | Low risk (0 call sites) — still docs-only for now |

---

## 8. Tests

| Suite | Relevance |
|-------|-----------|
| `menu.test.ts` | M3-B paths · titles — keep green after any menu normalize |
| Dedicated redirect target tests | **sparse / none** for legacy aliases |
| M7 recommendation | Add focused tests: each redirect source → target; menu `candidatesLlm` vs `ai` |

---

## 9. REMOVE_CANDIDATE gate

Applied to all DEPRECATE_REDIRECT: **FAIL gate** on external bookmark risk and/or active alias constants.  
→ **REMOVE_CANDIDATE count = 0**.

---

## 10. Implementation waves (design only)

| Wave | Scope | Risk |
|------|-------|------|
| **M7-A** | Optional menu normalize: `candidatesLlm` → `userRoutes.ai` + keep llm redirect page | LOW |
| **M7-B** | Document DEPRECATE_REDIRECT list · sunset notes in routes.ts / audit | LOW |
| **M7-C** | True orphan remove — **N/A (0 candidates)** · SKIP unless new evidence | — |
| **M7-D** | Menu/redirect regression tests | LOW |

If product wants zero FE churn: **M7-A/C SKIP**, only M7-B docs + M7-D tests.

---

## 11. Safety / regression

| Check | Result |
|-------|--------|
| production mutation | **0** |
| M5 Hub | **untouched** |
| M6 shared utils/orders/strategyRequests | **untouched** |
| TradingOrder / Outbox / create_order / POST orders | **0** |
| LIVE/ARM/Scheduler/Runtime/Kill/Recovery | **0** |
| residual WIP | **untouched** |
| commit / push | **금지** |

---

## 12. Next STEP (exactly one)

**M7-A — Optional menu normalize `/user/candidates/llm` → `/user/ai` (keep redirect page)**  
또는 product가 churn 거절 시 **M7-B DEPRECATE documentation only**.

Default recommendation: **M7-A** (승인 후 · menu+test only · no page delete).
