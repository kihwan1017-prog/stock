# MENU M5-E — Ops / Reconciliation SECTION_REORGANIZE

**Mode:** IMPLEMENTATION (UI section order only)  
**Verdict:** `OPS_RECONCILIATION_SECTION_REORGANIZE_READY_WITH_LIMITATIONS`  
**Date:** 2026-08-15  
**Baseline:** M5-E0 `OPS_RECONCILIATION_SECTION_REORGANIZE` · Ops HEAD LOC 278  
**Host:** `/admin/upbit` → 운영·정합 (`UpbitHubOpsSection`)

> Production mutation **0** (reconcile/sync/rate/snapshot/connection **미실행**).  
> push **없음**. Ambiguous panel **미수정**.  
> Next gate: **M5-F** Upbit Hub Final Regression Audit.

---

## 1. Before / After

| Metric | Before (M5-E0 / HEAD) | After (M5-E WT) |
|--------|----------------------:|----------------:|
| Ops LOC | 278 | 302 |
| split | no | **no** (single file) |
| useState | 1 | 1 |
| useEffect | 0 | 0 |
| useQuery (Ops) | 3 | 3 |
| useMutation (Ops) | 4 | 4 |
| Ambiguous mutations | 7 | 7 (untouched) |
| Ambiguous GET | 4 | 4 (untouched) |
| Ambiguous mount | 1 | 1 |

### Before order

버튼줄 (연결/잔고/체결) → status → rate → snapshot → Ambiguous

### After order

1. **운영 상태** — status READ  
2. **연결·동기화** — UBA ID · connection test · balance sync  
3. **Rate 상태** — table · health · recheck  
4. **Snapshot** — positions · raw  
5. **주문·체결 정합** — 체결 동기화 (reconcile)  
6. **Ambiguous Orders** — panel mount

---

## 2. API / Mutation contract

**Unchanged** (string refs + counts):

Ops GET: `getUpbitAccountStatus` · `getUpbitAccountSnapshot` · `getUpbitRateLimits`  
Ops mutations: `testUpbitAccountConnection` · `syncUpbitAccount` · `reconcileUpbitOrders` · `recheckUpbitRateLimits`

Handler bodies / endpoints / success messages **not edited**.

---

## 3. Ambiguous protection

- File `UpbitAmbiguousOrdersPanel.tsx`: **not edited in M5-E** (pre-existing Korean WIP residual remains in WT).
- Mount: OpsSection only (`<UpbitAmbiguousOrdersPanel />` × 1).
- Mutation/GET counts inside Ambiguous: unchanged by this STEP.

---

## 4. Canonical ownership (no regression)

| Domain | Owner | Ops tab |
|--------|-------|---------|
| LIVE/ARM/Scheduler | `/admin/accounts` | link only · no CONTROL mutation |
| Risk/Kill | `/admin/risk` | no Upbit ops mutations |
| Recovery CONTROL | `/admin/recovery` | Ambiguous not mounted |
| Runtime | `/admin/trading` | untouched |
| Orders/Outbox | `/admin/orders` | Ambiguous not mounted |

---

## 5. M5 regression

| Gate | Result |
|------|--------|
| M5-A 5 tabs | PASS (hub tabs test) |
| M5-B Technical order | PASS (focused) |
| M5-C News order | section order intact; rowKey WIP makes M5-C rowKey assertion fail — **pre-existing**, not M5-E |
| M5-D KEEP_AS_IS | A/B panel untouched |
| LIVE mutation on upbit | 0 |
| Risk LIVE mutation via Ops | 0 |

---

## 6. Safety regression

| Check | Result |
|-------|--------|
| TradingOrder delta | 0 (UI only) |
| Outbox delta | 0 |
| create_order / POST /v1/orders | 0 |
| Actual reconcile/sync/rate/snapshot/connection run | **0** |
| Server restart | **금지 · 미실행** |

---

## 7. Tests / lint

| Gate | Result |
|------|--------|
| `upbitOpsReconciliationSectionOrder.test.ts` | PASS |
| `upbitHubTabs.test.ts` | PASS |
| `upbitTechnicalSectionOrder.test.ts` | PASS |
| eslint (OpsSection + new test) | PASS |
| tsc (M5-E paths) | 신규 오류 **0** |

---

## 8. Changed files (M5-E scope)

- `frontend/src/features/admin/upbit/UpbitHubOpsSection.tsx`
- `frontend/src/features/admin/upbit/upbitOpsReconciliationSectionOrder.test.ts` (new)
- `docs/audit/MENU_M5E_OPS_RECONCILIATION_SECTION_REORGANIZE.md` (this file)
- Canonical: CURRENT_WORK · STEP_MASTER · ROADMAP · IMPLEMENTATION_STATUS · audit/README

---

## 9. Limitations

1. Ambiguous panel WIP (encoding/labels) still residual — out of scope.  
2. NewsCollector rowKey WIP still residual — M5-C focused rowKey assert may fail until that WIP settles.  
3. Snapshot section still depends on Sync section’s `ubaId` state (shared; intentional, no API change).  
4. No file split (by design — SECTION_REORGANIZE only).

---

## 10. Next STEP (exactly one)

**STEP M5-F — Upbit Hub Final Regression Audit** (승인 후).  
M6 시작 금지. Ambiguous / API / backend 추가 작업 **금지**.
