# MENU M6-B — Order COMMON_READ Columns Shared

**Mode:** IMPLEMENTATION (READ columns only)  
**Verdict:** `ORDER_READ_COLUMNS_SHARED_READY_WITH_LIMITATIONS`  
**Date:** 2026-08-15  
**Baseline:** M6-B0 `ORDER_READ_COLUMNS_SHARE_RECOMMENDED` · M6-A `239550d`

> mutation/query/filter/API/route/permission · capability mega-factory · commit/push **없음**.  
> LIVE/Kill/Recovery/Credential · TradingOrder/Outbox · create_order/POST orders **0**.

---

## 1. Before / After metrics

| Metric | Before | After |
|--------|-------:|------:|
| Admin `/admin/orders` column slots | **10** | **10** |
| User paper `/user/orders` columns | **8** | **8** |
| BrokerOrdersView columns | **8** | **8** |
| shared COMMON_READ keys | 0 | **7** |
| Admin-only READ | 1 (`broker_code`) | **1** (unchanged) |
| User-only READ | 1 (`created_at`) | **1** (unchanged) |
| Admin action columns | 2 (취소·상세) | **2** (unchanged) |
| capability mega-props | — | **0** |
| shared row type | — | **1** (`OrderReadRow`) |
| shared helpers | — | **3** (`create` / `build` / `replace`) |
| duplicated COMMON_READ defs (Admin+User paper+Broker ×7) | **21** inline | **7** shared (+ User status override) |
| duplicated READ definitions 감소 | — | **≈14** |

Column **order** preserved: Admin `order_id → broker → exchange…`; User `order_id → symbol → exchange…`.

---

## 2. Shared location

Convention: existing `frontend/src/shared/` (M6-A `shared/utils`).  
Added domain folder: `frontend/src/shared/orders/`.

| File | Role |
|------|------|
| `orderReadColumns.ts` | keys · titles · build/replace helpers · `OrderReadRow` |
| `orderReadColumns.test.ts` | focused wire + import-direction |

No new top-level folder inventing outside `shared/`.

---

## 3. Shared column list (M6-B0 SoT)

```text
order_id
exchange_code
symbol
side_code
status_code
order_quantity
order_price
```

Admin assembly: `ADMIN_ORDER_READ_PREFIX` + `broker_code` + `ADMIN_ORDER_READ_SUFFIX` + actions.  
User assembly: `USER_ORDER_READ_COLUMN_ORDER` + `created_at` (+ Broker status override).

---

## 4. Status renderer strategy

**Option A** — shared raw `status_code` column; User `BrokerOrdersView` uses `replaceOrderReadColumn` for rich KO/lookup.  
User paper keeps shared raw status (pre-existing). Rich renderer **not** removed.

---

## 5. Consumers

| Surface | Uses shared? | Append / override |
|---------|--------------|-------------------|
| Admin `/admin/orders` | **Yes** | `broker_code` · 취소 · 상세 |
| User `/user/orders` | **Yes** | `created_at` |
| `BrokerOrdersView` | **Yes** | rich `status_code` · `created_at` |

---

## 6. Safety / isolation

| Check | Result |
|-------|--------|
| shared columns mutation handlers | **0** |
| shared permission / owner / API | **0** |
| user → `@/features/admin` (orders paths) | **0** |
| admin → `@/features/user` (orders page) | **0** |
| GET `/orders` / clients / filters | **unchanged** |
| Admin cancel/resolve/retire/detail | **unchanged** |
| owner scope | container-only (unchanged) |
| M5 Upbit Hub production | **untouched** |
| M6-A admin dataHelpers shim | **retained** |
| TradingOrder / Outbox / create_order / POST orders | **0** |

---

## 7. Tests / quality

| Suite | Result |
|-------|--------|
| `src/shared/orders/orderReadColumns.test.ts` | **10 PASS** |
| eslint (M6-B files) | **PASS** |
| tsc M6-B paths | 신규 오류 **0** (WIP: NewsCollector / live-validation 등 별도) |

---

## 8. Limitations

1. Nullish READ cells now display `"-"` via M6-A `cell` (minor display delta vs bare empty).  
2. Titles localized via `ADMIN_ORDER_READ_TITLES` / `USER_ORDER_READ_TITLES` maps — not a single bilingual column object.  
3. Admin paper sub-table / executions / Outbox JSON panels **out of scope**.  
4. `formatOrderDateTime` not added (`created_at` remains User-local).  
5. Commit is this selective STEP (push 없음). BrokerOrdersView Link markup kept at HEAD (no drive-by).

---

## 9. Next STEP (exactly one)

**M6-C0 — Strategy Request READ presentation PRECHECK** (승인 후 · READ-ONLY).  
Order query/filter/hook/mutation 공용화 · M6-C 구현 **금지**.

---

## Changed files (M6-B)

- `frontend/src/shared/orders/orderReadColumns.ts` (**new**)
- `frontend/src/shared/orders/orderReadColumns.test.ts` (**new**)
- `frontend/src/app/(admin)/admin/orders/page.tsx`
- `frontend/src/app/(user)/user/orders/page.tsx`
- `frontend/src/features/user/orders/BrokerOrdersView.tsx`
- `docs/audit/MENU_M6B_ORDER_READ_COLUMNS_SHARED.md` (**new**)
- Canonical: CURRENT_WORK · STEP_MASTER · ROADMAP · IMPLEMENTATION_STATUS · audit/README
