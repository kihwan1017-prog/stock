# MENU M6-F — Shared Component Consolidation Final Regression / CLOSE

**Mode:** FINAL AUDIT ONLY · **production mutation = 0** · **shared code mutation = 0**  
**Date:** 2026-08-15  
**Baseline HEAD:** `a3612c0` (M6-C) · M6-B `87d0229` · M6-A `239550d`  
**Verdict:** `SHARED_COMPONENT_CONSOLIDATION_COMPLETE_WITH_LIMITATIONS`  
**M6_CLOSE:** **YES**

> M7 자동 시작 · production/shared 수정 · push **금지**.  
> 본 커밋: M6-D0/E0/F audit docs + Canonical CLOSE 고정.

---

## 0. Wave roll-up

| Wave | Outcome | Status |
|------|---------|--------|
| M6-0 | DESIGN_READY | docs |
| M6-A | formatters/utils · user→admin utils **0** · shim | **committed** `239550d` |
| M6-B | Order COMMON_READ **7** | **committed** `87d0229` |
| M6-C | Strategy Request COMMON_READ **4** | **committed** `a3612c0` |
| M6-D0 | Draft formatter sufficient | **SKIP** (no Draft column module) |
| M6-E0 | optional candidates **0** | **SKIP** |
| M6-F | final regression | **this audit** |

---

## 1. M6-A final

| Check | Result |
|-------|--------|
| Location | `frontend/src/shared/utils/` |
| Helpers | `asRecord`, `extractRows`, `cell`, `STRATEGY_REQUEST_STATUS_COLOR`, `STRATEGY_DRAFT_STATUS_COLOR`, `rateToPercent`, `percentToRate` (**7**) |
| user → `@/features/admin/utils/dataHelpers` | **0** (CLEAN) |
| admin shim | `features/admin/utils/dataHelpers.ts` re-export **retained** |
| shared hooks / mega components | **0 / 0** |
| circular | **0** |

### Import direction (broader)

| Edge | Class | Notes |
|------|-------|-------|
| user → admin **utils** | **CLEAN** | 0 |
| user → admin **api** (`useMarketSessionStatus`) | **INTENTIONAL** / preexisting limitation (M6-A out-of-scope API) | not introduced by B/C |
| admin → user `ProfileWorkspace` | **INTENTIONAL** | Pattern E Shell prop |
| other admin → user product | **CLEAN** | 0 |
| UNEXPECTED | **0** | |

---

## 2. M6-B Order columns final

| Check | Result |
|-------|--------|
| Module | `frontend/src/shared/orders/orderReadColumns.ts` |
| Keys (7) | `order_id`, `exchange_code`, `symbol`, `side_code`, `status_code`, `order_quantity`, `order_price` |
| Admin slots | **10** (7 shared + `broker_code` + 취소 + 상세) |
| User slots | **8** (7 + `created_at`) |
| Broker rich status | **maintained** (`replaceOrderReadColumn`) |
| capability / query / mutation / owner in shared | **0** |
| Consumers | Admin orders · User orders · BrokerOrdersView (**3**) |

---

## 3. M6-C Strategy Request columns final

| Check | Result |
|-------|--------|
| Module | `frontend/src/shared/strategyRequests/strategyRequestReadColumns.tsx` |
| Keys (4) | `strategy_request_id`, `candidate_id`, `status`, `requested_at` |
| Admin slots | **6** (+ `user_id` + lifecycle snapshot) |
| User slots | **4** |
| Approve/reject · create/cancel · History · Detail | **outside shared** |
| STATUS_COLOR | M6-A reuse |
| Consumers | Admin + User pages (**2**) |
| capability props | **0** |

---

## 4–5. M6-D / M6-E SKIP audit

| Item | Evidence |
|------|----------|
| `shared/strategyDrafts/` | **absent** |
| Draft STATUS_COLOR | both pages → shared utils |
| M6-E candidate modules | **none added** |
| Account / Portfolio / Kill / Notification / Backtest / Candidate / LIVE Val / Hub | classifications from M6-E0 **unchanged** · no new share |

---

## 6. Shared inventory totals

| Metric | Value |
|--------|------:|
| shared utils helpers | **7** |
| shared column modules | **2** |
| shared COMMON_READ keys | **11** (7+4) |
| shared hooks (M6) | **0** |
| mega shared React pages (M6) | **0** |
| capability props (M6 shared) | **0** |
| route / API / permission / AuthGuard merges | **0** |
| owner isolation changes | **0** |

---

## 7. Over-abstraction

| Module | Consumers ≥2 | route/API/perm/mutation | Verdict |
|--------|:------------:|-------------------------|---------|
| `shared/utils/*` | yes | no | **KEEP** |
| `shared/orders` | 3 | no | **KEEP** |
| `shared/strategyRequests` | 2 | no | **KEEP** |

Row types `OrderReadRow` / `StrategyRequestReadRow` = presentation min-shape only (no Admin/User schema merge).

---

## 8. Route / permission / backend

M6 commits introduce **no** new routes, permission keys, AuthGuard, or backend endpoints.  
Shared layers are FE presentation only.

---

## 9. M5 / M4 regression

| Check | Result |
|-------|--------|
| M5 Hub tabs | 개요 / Technical / 뉴스 파이프라인 / A/B 실험 / 운영·정합 — **present** |
| M6-B/C file touch on Hub | **none** |
| M6-A | import/formatter only on some pages (risk/live-validation/portfolio helpers) — **no Hub tab IA change** |
| LIVE CONTROL canonical | `AdminUpbitLiveUbaPanel` on `/admin/accounts` |
| Risk | Kill CONTROL · LIVE/ARM **READ** + link to accounts — **no control duplication reintroduced** |

---

## 10. Trading / policy

| Check | Result |
|-------|--------|
| TradingOrder / Outbox / create_order / POST orders | **0** (audit) |
| LIVE/ARM/Scheduler/Runtime/Kill/Recovery mutation by M6 | **0** |
| Scanner / Shadow / Cohort / News N2–N5 / A/B policy | **0** |

---

## 11. Quality gates (this STEP)

| Gate | Result |
|------|--------|
| vitest M6 suite (4 files) | **31 PASS** |
| eslint M6 shared + wired pages | **PASS** |
| tsc M6 paths | 신규 **0** |
| tsc WIP (separate) | live-validation null · NewsCollector `analysis_id`/`signal_id` → **FAIL_PREEXISTING_WIP** |

---

## 12. Residual WIP (not M6-F fixes)

**Pre-M6 / parallel WT** (examples): NewsCollector rowKey · Ambiguous · risk/portfolio presentation · MarketExplorer · RuntimePreflight · live-validation · backend/ops/.run/tmp · recovery · accounts helpers · …

**M6 residual docs:** included in this selective docs commit (M6-D0/E0/F + Canonical).

Committed M6 production paths (`shared/utils|orders|strategyRequests` + wired pages) are **clean** vs HEAD.

---

## 13. Mission statement

Shared **value-bearing** presentation only:  
utils/formatters (A) · Order RO columns (B) · Strategy Request RO columns (C).  
Skipped Draft columns (D) and optional marginal shares (E).  
Workflow / permission / mutation / owner scope stayed in containers.

---

## 14. CLOSE

**M6_CLOSE = YES**  
Further Admin/User shared refactor requires a **new concrete need** (new STEP), not continuation of M6 waves.

---

## 15. Next STEP (exactly one)

**M7-0 — Legacy / redirect route cleanup PRECHECK** (READ-ONLY · no delete implementation).

---

## Linked

- [MENU_M6_SHARED_COMPONENT_PRECHECK.md](MENU_M6_SHARED_COMPONENT_PRECHECK.md)  
- [MENU_M6A_SHARED_FORMATTERS_UTILS.md](MENU_M6A_SHARED_FORMATTERS_UTILS.md)  
- [MENU_M6B_ORDER_READ_COLUMNS_SHARED.md](MENU_M6B_ORDER_READ_COLUMNS_SHARED.md)  
- [MENU_M6C_STRATEGY_REQUEST_READ_COLUMNS_SHARED.md](MENU_M6C_STRATEGY_REQUEST_READ_COLUMNS_SHARED.md)  
- [MENU_M6D_STRATEGY_DRAFT_PRECHECK.md](MENU_M6D_STRATEGY_DRAFT_PRECHECK.md)  
- [MENU_M6E_SHARED_PRESENTATION_FINAL_PRECHECK.md](MENU_M6E_SHARED_PRESENTATION_FINAL_PRECHECK.md)
