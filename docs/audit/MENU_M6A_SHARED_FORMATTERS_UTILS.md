# MENU M6-A — Shared Formatters / Utils Extraction

**Mode:** IMPLEMENTATION (utils/formatters only)  
**Verdict:** `SHARED_FORMATTERS_UTILS_READY_WITH_LIMITATIONS`  
**Date:** 2026-08-15  
**Baseline:** M6-0 `SHARED_COMPONENT_CONSOLIDATION_DESIGN_READY`

> route/permission/AuthGuard/backend/API · shared hook · shared React page component · commit/push **없음**.  
> LIVE/Kill/Recovery/Credential mutation **0**.

---

## 1. Before / After

| Metric | Before | After |
|--------|-------:|------:|
| user → `@/features/admin/utils/dataHelpers` | **13** | **0** |
| shared target | — | `frontend/src/shared/utils/` |
| helpers moved (canonical body) | 0 | **7** (`asRecord`,`extractRows`,`cell`,`STRATEGY_REQUEST_STATUS_COLOR`,`STRATEGY_DRAFT_STATUS_COLOR`,`rateToPercent`,`percentToRate`) |
| duplicate formatter maps removed | — | Request×2 · Draft×2 · Risk rate×2 → **3 pairs** |
| admin `dataHelpers.ts` | full body | **re-export shim** (compat) |
| deleted old file? | — | **No** (shim retained for remaining admin imports) |
| circular dependency | — | **No** |
| shared hook / shared component | — | **0 / 0** |

---

## 2. Shared location (convention)

Existing `frontend/src/shared/` used (components already).  
Added: `frontend/src/shared/utils/`.

| File | Exports |
|------|---------|
| `dataHelpers.ts` | `asRecord`, `extractRows`, `cell` |
| `strategyStatusColors.ts` | `STRATEGY_REQUEST_STATUS_COLOR`, `STRATEGY_DRAFT_STATUS_COLOR` |
| `riskRatePercent.ts` | `rateToPercent`, `percentToRate` |
| `index.ts` | re-exports |

Admin shim: `features/admin/utils/dataHelpers.ts` → re-export shared (no local body).

---

## 3. Domain results

| Area | Result |
|------|--------|
| Request STATUS | Shared map · Admin/User pages import · actions **untouched** |
| Draft STATUS | Shared map · Admin/User pages import · Draft hub actions **untouched** |
| Risk rate↔% | Shared helpers · Admin/User risk pages · Kill/system/LIVE logic **untouched** |
| dataHelpers | User tree → shared only |

### Import change counts

| Side | Files updated (import path / formatter) |
|------|----------------------------------------:|
| User | **13** (dataHelpers) + Request/Draft/Risk formatter pages |
| Admin | strategy-requests · strategy-drafts · risk (+ shim rewrite) |
| Remaining admin consumers | still import shim path (~60) — works via re-export |

---

## 4. Safety / regression

| Check | Result |
|-------|--------|
| route / permission / AuthGuard / backend API | **0** |
| owner isolation | unchanged (no scope in helpers) |
| TradingOrder / Outbox / create_order / POST orders | **0** |
| M5 Upbit Hub production | **untouched** (Ops/News/Ambiguous not edited in M6-A except via intact shim) |
| production trading mutation | **0** |

---

## 5. Tests

| Suite | Result |
|-------|--------|
| `sharedUtils.test.ts` | PASS |
| `m6aImportDirection.test.ts` | PASS (user→admin utils = 0) |
| eslint (M6-A primary files) | PASS |
| GuidedUpbitLiveSmokePanel eslint | **pre-existing** errors (import-only touch) — not M6-A blocker |
| tsc M6-A paths | 신규 오류 **0** (project WIP noise separate) |

---

## 6. Limitations

1. Admin bulk migrate to `@/shared/utils` not completed — shim remains.  
2. User strategy-requests keeps **local** `asRecord` returning `undefined` (signature differs from shared `null`) — left alone to avoid behavior drift.  
3. Admin-only STATUS maps (Ambiguous, settlement, jobs, calendar) **not** moved (KEEP_SEPARATE / not Admin↔User dup).  
4. `useMarketSessionStatus` still calls `adminApi` for market session (API, out of M6-A utils scope).

---

## 7. Changed files (summary)

**New:** `shared/utils/*` (+ tests)  
**Shim:** `features/admin/utils/dataHelpers.ts`  
**User imports:** 13 files under `features/user` + `app/(user)`  
**Formatters:** admin/user strategy-requests · strategy-drafts · risk pages  
**Docs:** this audit + Canonical  

---

## 8. Next STEP (exactly one)

**M6-B0 — Order READ-ONLY shared columns PRECHECK** (승인 후 · READ-ONLY).  
M6-B 구현으로 바로 가지 않음. Admin shim 삭제·56 consumer bulk migrate **금지**.
