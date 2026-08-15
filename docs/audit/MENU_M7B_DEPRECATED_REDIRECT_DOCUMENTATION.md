# MENU M7-B — Deprecated Redirect Documentation

**Mode:** DOCUMENTATION / READ-ONLY · **production mutation = 0**  
**Date:** 2026-08-15  
**Baseline:** M7-A commit `d1d0634` · branch `release/v1.1.0`  
**Verdict:** `LEGACY_REDIRECT_DEPRECATION_DOCUMENTED`

> **DEPRECATE_REDIRECT ≠ DELETE_ROUTE.**  
> External bookmark/deep-link 사용은 코드로 증명 불가 → `UNKNOWN_EXTERNAL_COMPATIBILITY` → REMOVE gate **FAIL**.  
> route/page/redirect/menu/API/permission **변경·삭제 금지**.

---

## 0. Inventory (source re-verified at HEAD `d1d0634`)

| Metric | Count |
|--------|------:|
| total redirect pages | **12** |
| KEEP_REDIRECT | **3** |
| DEPRECATE_REDIRECT | **9** |
| redirect target verified | **12** |
| redirect chains | **0** |
| canonical page missing | **0** |
| legacy menu exposure | **0** |
| INTERNAL_REFERENCE_REMAINING (Link/router.push to legacy path) | **0** |
| REVIEW_REQUIRED | **0** |
| REMOVE_CANDIDATE | **0** |
| MENU_NORMALIZATION_REQUIRED | **0** |

---

## 1. KEEP_REDIRECT (not deprecated)

| Legacy | Target | Why keep |
|--------|--------|----------|
| `/admin` | `/admin/dashboard` | Entry-point compatibility |
| `/user` | `/user/dashboard` | Entry-point compatibility |
| `/user/candidates/llm` | `/user/ai` | Bookmark + M7-A menu already → `/user/ai`; redirect page **retained** |

M7-A regression: menu leaf `LLM 분석` → `userRoutes.ai` (`/user/ai`). llm redirect page **unchanged**.

---

## 2. DEPRECATE_REDIRECT matrix (9)

| legacy_route | canonical_route | classification | legacy_page | canonical_page | redirect_target_verified | redirect_chain | menu_exposure | permission_impact | removal_status | removal_blocker |
|--------------|-----------------|:--------------:|:-----------:|:--------------:|:------------------------:|:--------------:|:-------------:|:-----------------:|:--------------:|-----------------|
| `/admin/data` | `/admin/monitoring` | DEPRECATE_REDIRECT | yes | yes | yes (`adminRoutes.monitoring`) | none | 0 | none | RETAIN_FOR_COMPATIBILITY | UNKNOWN_EXTERNAL_COMPATIBILITY |
| `/admin/market` | `/admin/monitoring` | DEPRECATE_REDIRECT | yes | yes | yes | none | 0 | none | RETAIN_FOR_COMPATIBILITY | UNKNOWN_EXTERNAL_COMPATIBILITY |
| `/admin/positions` | `/admin/portfolio` | DEPRECATE_REDIRECT | yes | yes | yes (`adminRoutes.portfolio`) | none | 0 | none | RETAIN_FOR_COMPATIBILITY | UNKNOWN_EXTERNAL_COMPATIBILITY |
| `/admin/settings` | `/admin/env-settings` | DEPRECATE_REDIRECT | yes | yes | yes (`adminRoutes.envSettings`) | none | 0 | none | RETAIN_FOR_COMPATIBILITY | UNKNOWN_EXTERNAL_COMPATIBILITY |
| `/user/account` | `/user/accounts` | DEPRECATE_REDIRECT | yes | yes | yes (`userRoutes.accounts`) | none | 0 | none | RETAIN_FOR_COMPATIBILITY | UNKNOWN_EXTERNAL_COMPATIBILITY |
| `/user/market` | `/user/markets/stocks` | DEPRECATE_REDIRECT | yes | yes | yes (`userRoutes.marketsStocks`) | none | 0 | none | RETAIN_FOR_COMPATIBILITY | UNKNOWN_EXTERNAL_COMPATIBILITY |
| `/user/trades` | `/user/orders` | DEPRECATE_REDIRECT | yes | yes | yes (`userRoutes.orders`) | none | 0 | none | RETAIN_FOR_COMPATIBILITY | UNKNOWN_EXTERNAL_COMPATIBILITY |
| `/user/strategies/auto` | `/user/auto-trading` | DEPRECATE_REDIRECT | yes | yes | yes (`userRoutes.autoTrading`) | none | 0 | none | RETAIN_FOR_COMPATIBILITY | UNKNOWN_EXTERNAL_COMPATIBILITY |
| `/user/orders/paper` | `/user/orders` | DEPRECATE_REDIRECT | yes | yes | yes (`userRoutes.orders`) | none | 0 | none | RETAIN_FOR_COMPATIBILITY | UNKNOWN_EXTERNAL_COMPATIBILITY |

Source pages (read-only verify):

- `admin/data|market|positions|settings/page.tsx`
- `user/account|market|trades|strategies/auto|orders/paper/page.tsx`

Canonical content pages exist and do **not** call `redirect(` (no A→B→C).

---

## 3. Constants vs pages vs menu vs breadcrumb

| Layer | Behavior |
|-------|----------|
| **A. Redirect page** | Literal URL `/admin/data` etc. still has `page.tsx` with `redirect(...)` |
| **B. Route constant** | `adminRoutes.data\|market\|positions\|settings` already equal **canonical** path strings (never hit redirect pages when using constants) |
| **C. Menu href** | Sidebar uses canonical only (`monitoring`, `portfolio`, `envSettings`, `accounts`, `marketsStocks`, `orders`, `autoTrading`, `ai`) — **legacy exposure = 0** |
| **D. Breadcrumb** | Titles remain for `userRoutes.strategiesAuto`, `ordersPaper`, `candidatesLlm`, and `legacyUserRoutes` keys — **not deleted** |

`legacyUserRoutes` export: defined in `routes.ts` only; **no production import** found.

---

## 4. Internal references (frontend `src`)

| Kind | Result |
|------|--------|
| redirect implementation | 9 DEPRECATE + 3 KEEP (expected) |
| menu | **0** legacy leaf |
| Link / router.push to literal legacy path | **0** |
| route constant keys pointing at legacy path strings | `strategiesAuto`, `ordersPaper`, `legacyUserRoutes.*`, `candidatesLlm` (KEEP) — titles / aliases only |
| tests | `menu.test.ts` asserts llm redirect retained (KEEP); no DEPRECATE deletion tests |

→ **INTERNAL_REFERENCE_REMAINING (navigation) = 0**

---

## 5. Permission / AuthGuard

| Check | Result |
|-------|--------|
| Admin layout | `AuthGuard` `requiredRoles=["admin"]` — path-agnostic |
| User layout | role filter + `requiredRolesForUserPath` — no legacy-only bypass found |
| permission mutation | **0** |
| AuthGuard mutation | **0** |
| REVIEW_REQUIRED | **0** |

Redirect cannot escalate role: same `(admin)` / `(user)` layout gate applies to legacy and canonical under the same segment.

---

## 6. REMOVE gate

| Criterion | Status |
|-----------|--------|
| menu reference = 0 | PASS |
| internal Link navigation = 0 | PASS |
| canonical exists | PASS |
| redirect chain = 0 | PASS |
| external compatibility known | **FAIL** (`UNKNOWN_EXTERNAL_COMPATIBILITY`) |
| telemetry / usage evidence | **absent** |

→ **REMOVE_CANDIDATE = 0** · all nine stay `RETAIN_FOR_COMPATIBILITY`.

---

## 7. Regression (read-only)

| Area | Status |
|------|--------|
| M3-B strategy menus | untouched |
| M4 ops regroup / LIVE control `/admin/accounts` | untouched |
| M5 Upbit Hub | untouched |
| M6 shared utils/orders/strategyRequests | untouched |
| M7-A LLM → `/user/ai` + llm redirect | untouched |
| TradingOrder / Outbox / create_order / POST orders | **0** |
| LIVE/ARM/Scheduler/Runtime/Kill/Recovery | **0** |
| residual WIP | **untouched** |

---

## 8. Production mutation

**0** — docs only.

---

## 9. Next STEP (exactly one)

**M7-F — LEGACY / REDIRECT FINAL REGRESSION AUDIT**

- M7-C SKIP (orphan = 0)
- Until M7-F: route/page/redirect **삭제·변경 금지**
