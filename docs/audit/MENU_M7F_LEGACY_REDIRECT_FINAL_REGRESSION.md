# MENU M7-F — Legacy / Redirect Final Regression Audit

**Mode:** FINAL AUDIT ONLY · **production mutation = 0**  
**Date:** 2026-08-15  
**Baseline HEAD:** `d1d0634` (M7-A) · M7-B docs uncommitted (docs-only WT)  
**Verdict:** `LEGACY_REDIRECT_CLEANUP_COMPLETE_WITH_LIMITATIONS`  
**M7_CLOSE:** **YES**

> route/page/redirect/menu/permission/API **변경·삭제 금지**.  
> commit/push 금지 (본 STEP). M7-B/F docs는 이후 selective commit.

---

## Contract totals (re-verified)

| Metric | Expected | Actual |
|--------|---------:|-------:|
| total redirect | 12 | **12** |
| KEEP_REDIRECT | 3 | **3** |
| DEPRECATE_REDIRECT | 9 | **9** |
| REMOVE_CANDIDATE | 0 | **0** |
| REVIEW_REQUIRED | 0 | **0** |
| redirect target verified | 12 | **12** |
| redirect chain | 0 | **0** |
| canonical missing | 0 | **0** |
| legacy menu exposure | 0 | **0** |
| active internal legacy nav | 0 | **0** |

---

## Redirect map (source)

### KEEP_REDIRECT

| Source | Target | Page | Canonical page |
|--------|--------|:----:|:--------------:|
| `/admin` | `/admin/dashboard` | yes | yes (no redirect) |
| `/user` | `/user/dashboard` | yes | yes |
| `/user/candidates/llm` | `/user/ai` | yes | yes |

### DEPRECATE_REDIRECT

| Source | Target |
|--------|--------|
| `/admin/data` | `/admin/monitoring` |
| `/admin/market` | `/admin/monitoring` |
| `/admin/positions` | `/admin/portfolio` |
| `/admin/settings` | `/admin/env-settings` |
| `/user/account` | `/user/accounts` |
| `/user/market` | `/user/markets/stocks` |
| `/user/trades` | `/user/orders` |
| `/user/strategies/auto` | `/user/auto-trading` |
| `/user/orders/paper` | `/user/orders` |

Shared targets (`data`+`market`→monitoring, `trades`+`orders/paper`→orders) = **allowed** compatibility.

---

## M7-A regression

| Check | Result |
|-------|--------|
| Menu `LLM 분석` | `userRoutes.ai` → `/user/ai` |
| Menu `/user/candidates/llm` | **0** |
| `/user/ai` page | exists · not redirect |
| `/user/candidates/llm` page | exists · `redirect(userRoutes.ai)` |
| page delete | **0** |

`menu.test.ts` M7-A case **PASS** (suite 11/11).

---

## M7-B regression

| Check | Result |
|-------|--------|
| 9 DEPRECATE pages still present | **yes** |
| REMOVE_CANDIDATE | **0** |
| removal gate | **FAIL** (`UNKNOWN_EXTERNAL_COMPATIBILITY`) |
| Doc SoT | `MENU_M7B_DEPRECATED_REDIRECT_DOCUMENTATION.md` |

**Policy:** telemetry/외부 사용 근거 전까지 **삭제 작업 재개 금지**.

---

## Cross-track regression (read-only)

| Track | Result |
|-------|--------|
| M3-B strategy menus + pages | exposed · pages exist · KEEP_CANONICAL |
| M4 Operations regroup | menu intact · LIVE control → `/admin/accounts` |
| M5 Upbit Hub | 5 tabs (overview/technical/news/ab/ops) intact |
| M6 shared utils/orders/strategyRequests | intact · user→admin `dataHelpers` imports **0** |
| permission / AuthGuard | delta **0** (layouts unchanged since M7-A) |
| backend/API (M7-attributable) | **0** (residual backend WIP ≠ M7) |
| TradingOrder / Outbox / create_order / POST orders | **0** |
| LIVE/ARM/Scheduler/Runtime/Kill/Recovery (M7) | **0** |
| Scanner/Shadow/News/A-B policy (M7) | **0** |

---

## Tests / lint

| Check | Result |
|-------|--------|
| `menu.test.ts` | **11 PASS** |
| eslint `menu.tsx` / `menu.test.ts` | **PASS** |
| M7 typecheck new errors | **0** (residual WIP tsc 분리) |

---

## Limitations

1. DEPRECATE 9 + KEEP 3 redirects **의도적 유지** (삭제 ≠ cleanup 완료 조건).
2. External bookmark: `UNKNOWN_EXTERNAL_COMPATIBILITY`.
3. M7-0 / M7-B audit files may be uncommitted until selective docs commit.
4. `useMarketSessionStatus` → `adminApi` = preexisting M6 limitation (utils 아님).

---

## M7_CLOSE = YES

Legacy/Redirect cleanup track **공식 종료**.  
후속 삭제는 별도 product/telemetry gate 없이는 열지 않음.

---

## Next STEP (exactly one)

**M8-0 — FINAL ADMIN / USER MENU, ROUTE, PERMISSION REGRESSION AUDIT**
