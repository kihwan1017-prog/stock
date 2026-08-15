# MENU M6-C — Strategy Request COMMON_READ List Columns Shared

**Mode:** IMPLEMENTATION (list READ columns only)  
**Verdict:** `STRATEGY_REQUEST_COLUMNS_SHARED_READY_WITH_LIMITATIONS`  
**Date:** 2026-08-15  
**Baseline:** M6-C0 `STRATEGY_REQUEST_READ_SHARE_RECOMMENDED` · M6-B `87d0229`

> approve/reject/create/cancel · History · Detail · query/hook · route/API/permission · commit/push **없음**.

---

## 1. Before / After

| Metric | Before | After |
|--------|-------:|------:|
| Admin list columns | **6** | **6** |
| User list columns | **4** | **4** |
| shared COMMON_READ keys | 0 | **4** |
| Admin-only READ | 2 | **2** (`user_id`, `candidate_lifecycle_status_snapshot`) |
| User-only list READ | 0 | **0** |
| capability mega-props | — | **0** |
| shared row type | — | **1** (`StrategyRequestReadRow`) |
| shared helpers | — | **3** (`renderStatusTag` / `create` / `build`) |
| duplicated COMMON_READ defs (Admin+User ×4) | **8** | **4** shared (**−4**) |
| column order | — | **unchanged** (Admin segments around Admin-only) |

---

## 2. Shared location

`frontend/src/shared/strategyRequests/` (parallel to M6-B `shared/orders/`).

| File | Role |
|------|------|
| `strategyRequestReadColumns.tsx` | keys · titles · Tag status · build helpers |
| `strategyRequestReadColumns.test.ts` | focused wire + import-direction |

---

## 3. Shared keys (M6-C0 SoT)

```text
strategy_request_id
candidate_id
status
requested_at
```

Admin assembly: `ADMIN_SR_READ_PREFIX` + `user_id` + `ADMIN_SR_READ_AFTER_USER` + lifecycle + `ADMIN_SR_READ_SUFFIX`.  
User assembly: `USER_SR_READ_COLUMN_ORDER` (= all 4).

---

## 4. Status / requested_at strategy

| Concern | Strategy |
|---------|----------|
| status | Shared `renderStrategyRequestStatusTag` · **M6-A** `STRATEGY_REQUEST_STATUS_COLOR` (no new map) |
| requested_at | Shared `cell()` (Admin already; User bare → nullish now `"-"`) |

---

## 5. KEEP_SEPARATE (verified)

- Admin approve/reject Drawer  
- User create Card / cancel Drawer  
- Admin history table + `actor`  
- Detail Descriptions / Typography  
- All APIs / queries / owner scope  

---

## 6. Safety / regression

| Check | Result |
|-------|--------|
| route / permission / AuthGuard / backend | **0** |
| user→admin / admin→user imports (pages) | **0** |
| M5 Hub | **untouched** |
| M6-A STATUS_COLOR / shim | **reused / retained** |
| M6-B `shared/orders` | **untouched** |
| TradingOrder / Outbox / create_order / POST orders | **0** |

---

## 7. Tests / quality

| Suite | Result |
|-------|--------|
| `strategyRequestReadColumns.test.ts` | **12 PASS** |
| eslint (M6-C files) | **PASS** |
| tsc M6-C paths | 신규 **0** (WIP NewsCollector / live-validation 별도) |

---

## 8. Limitations

1. User `requested_at` nullish display now `"-"` via `cell`.  
2. Detail/History still duplicated (DEFER per M6-C0).  
3. User page still has local `asRecord` (out of list-column scope).  
4. Commit is this selective STEP (push 없음).

---

## 9. Next STEP (exactly one)

**M6-D0 — Strategy Draft READ presentation PRECHECK** (승인 후 · READ-ONLY).  
Detail/History/mutation 공용화 · M6-D 구현 **금지**.

---

## Linked

- [MENU_M6C_STRATEGY_REQUEST_PRECHECK.md](MENU_M6C_STRATEGY_REQUEST_PRECHECK.md)
