# MENU M6-B0 — Order READ-ONLY Shared Columns Precheck

**Mode:** READ-ONLY PRECHECK ONLY · **production mutation = 0**  
**Date:** 2026-08-15  
**Baseline:** M6-A `239550d`  
**Verdict:** `ORDER_READ_COLUMNS_SHARE_RECOMMENDED`

> shared columns 구현 · hook · route/API/permission · order mutation · commit/push **금지**.

---

## 0. Baseline

| Item | Status |
|------|--------|
| M6-A user→admin utils | **0** (shim retained) |
| M6-0 Order hint | SHARE_TABLE_COLUMNS (RO) · mutations KEEP_SEPARATE |
| This STEP | re-verify with live column/API inventory |

---

## 1. Routes (actual)

| Role | Route | Page |
|------|-------|------|
| Admin orders | `/admin/orders` | `app/(admin)/admin/orders/page.tsx` |
| Admin trades | `/admin/trades` | `app/(admin)/admin/trades/page.tsx` (executions · paper) |
| User paper orders | `/user/orders` | `app/(user)/user/orders/page.tsx` |
| User Kiwoom | `/user/orders/kiwoom` | → `BrokerOrdersView` (`brokerCode=KIWOOM`) |
| User Upbit | `/user/orders/upbit` | → `BrokerOrdersView` (`brokerCode=UPBIT`) |
| User paper alias | `/user/orders/paper` | redirect (legacy) |
| User trades legacy | `/user/trades` | legacy redirect → orders |

**Primary pair for M6-B:** `/admin/orders` ↔ `/user/orders` (+ broker views as same column family).

---

## 2. Component inventory

### Admin `/admin/orders`

| Surface | Detail |
|---------|--------|
| Shell | `AdminPageShell` |
| Primary table | `AdminDataTable` title `GET /orders` |
| Column def | **inline** in page |
| Query | `adminApi.listOrders` → `GET /orders` (filters: account/symbol/exchange/broker/limit/offset) |
| Extra READ | Outbox JSON · Paper orders table · Kill Switch status |
| Mutations | submit · cancelTrading · retire · resolveNotSubmitted · createPaper · cancelPaper |
| Detail | Drawer `getOrder` |

### User `/user/orders`

| Surface | Detail |
|---------|--------|
| Shell | `PageContainer` |
| Primary table | Ant `Table<TradeOrder>` 「주문 내역」 |
| Column def | **inline** |
| Query | `userApi.listOrders` → `GET /orders` (**account_id required**, owner) |
| Extra READ | executions table · `AccountStrategyPerformancePanel` |
| Mutations on order table | **none** |

### User broker views

`BrokerOrdersView`: same 8 dataIndexes as paper; **status** has rich label/lookup UX (USER-specific).

---

## 3. Scope

| | Admin | User |
|--|-------|------|
| Scope | ALL_USERS / ACCOUNT selectable · broker/exchange filters | USER_OWNER · own paper `account_id` / broker UBA |
| Outbox / Ambiguous ops | Admin page (+ Ambiguous on Upbit Ops, not this table) | status **labels** only in BrokerOrdersView |
| Actions | cancel · resolve · retire · detail · paper create | none on list |

---

## 4. Column matrix — primary order list

### Admin `GET /orders` (10 column slots)

| # | title | dataIndex | Class |
|---|-------|-----------|-------|
| 1 | order_id | order_id | COMMON_READ |
| 2 | broker | broker_code | ADMIN_ONLY_READ |
| 3 | exchange | exchange_code | COMMON_READ |
| 4 | symbol | symbol | COMMON_READ |
| 5 | side | side_code | COMMON_READ |
| 6 | status | status_code | COMMON_READ |
| 7 | qty | order_quantity | COMMON_READ |
| 8 | price | order_price | COMMON_READ |
| 9 | 취소 | (action) | ADMIN_MUTATION |
| 10 | 상세 | (action) | ADMIN_MUTATION |

### User paper `/user/orders` (8 columns)

| # | title | dataIndex | Class |
|---|-------|-----------|-------|
| 1 | ID | order_id | COMMON_READ |
| 2 | 종목 | symbol | COMMON_READ |
| 3 | 시장 | exchange_code | COMMON_READ |
| 4 | 구분 | side_code | COMMON_READ |
| 5 | 상태 | status_code | COMMON_READ |
| 6 | 수량 | order_quantity | COMMON_READ |
| 7 | 가격 | order_price | COMMON_READ |
| 8 | 시각 | created_at | USER_ONLY_READ (+ dayjs render) |

### Counts

| Metric | Value |
|--------|------:|
| Admin total columns | **10** |
| Admin READ columns | **8** |
| User READ columns | **8** |
| Exact common (same dataIndex) | **7** |
| Semantic common | **7** (same fields; titles EN vs KO) |
| Admin-only READ | **1** (`broker_code`) |
| User-only READ | **1** (`created_at`) |
| Mutation/action columns | **2** (Admin only) |
| **common_read_ratio** | **7 / 8 = 0.875** |

Formula: `exact_common_dataIndex / min(admin_read_columns, user_read_columns)`.

**Not in either primary list:** `filled_quantity`, avg fill, order_type (exist on type/API partially — UI absent).

---

## 5. Renderer comparison

| Field | Admin | User paper | User broker |
|-------|-------|------------|-------------|
| symbol | raw | raw | raw |
| side | raw `side_code` | raw | raw |
| qty | raw | raw | raw |
| price | raw | raw | raw |
| status | raw | raw | **custom** KO labels + ambiguous/lookup subtext |
| timestamp | **absent** | `dayjs` `YYYY-MM-DD HH:mm` | same |
| fill | N/A on list | N/A | N/A |

→ Plain COMMON_READ columns are **renderer-identical** (no Badge/Tag).  
→ Status **broker UX** = KEEP_SEPARATE override.  
→ Date = SHARE_FORMATTER candidate (`formatOrderDateTime`).

---

## 6. API / row type

| | Admin | User |
|--|-------|------|
| Endpoint | `GET /orders` (`adminApi.listOrders`) | `GET /orders` (`userApi.listOrders`) |
| Client shape | `JsonValue` → `extractRows` → `Record` | `TradeOrder[]` |
| Params | account optional + broker/exchange/symbol | **account_id / UBA required** (owner) |
| Schema | **MOSTLY_SAME_SCHEMA** | typed subset + index signature |
| Row type | `OrderRow = Record<string, unknown>` | `TradeOrder` |
| Compatibility | **STRUCTURALLY_COMPATIBLE** | |

Ownership enforcement: **server + User enabled-gate** — columns must not encode scope.

Executions (secondary): Admin `/admin/trades` vs User executions card — different property names (`quantity`/`price` vs `execution_quantity`/`execution_price`) → **out of M6-B primary scope** (note only).

---

## 7. Existing shared order UI

| Search | Result |
|--------|--------|
| OrderStatusBadge / SideBadge | **없음** |
| shared order columns | **없음** |
| M6-A utils | `cell` usable for nullish display; no order-specific formatters yet |
| `isOpenOrderStatus` | user trading helper — not Admin shared |

ALREADY_SHARED order presentation: **0**.

---

## 8. Capability-prop risk

`createOrderColumns({ isAdmin, showBroker, canCancel, canResolve, ... })` → **HIGH** — **비추천**.

권장 조립:

```text
Admin: [broker_code?, ...commonRead7, ...adminActions]
User:  [...commonRead7, created_at?, statusOverride?]
```

Titles: pass `titles` map or leave localized titles outside shared defs (dataIndex+render only).

---

## 9. Options

| Option | Assessment |
|--------|------------|
| **A KEEP_SEPARATE** | Valid but wastes 0.875 overlap |
| **B SHARE_FORMATTERS_ONLY** | Date (+ optional status label map for broker) — **LOW benefit** for 7 plain columns |
| **C SHARE_COMMON_READ_COLUMNS** | **Recommended** — 7 dataIndex columns RO; append Admin/User exclusives & actions |
| **D COLUMN_FACTORY_WITH_CAPABILITIES** | Reject unless forced — prop explosion |

**recommended_option:** `C`

---

## 10. Proposed M6-B scope (design only)

| Include | Exclude |
|---------|---------|
| Shared RO column defs for 7 common fields | Action columns |
| Optional `formatOrderDateTime` | Outbox / resolve / retire / submit |
| Title map or bilingual titles | Query/filter/pagination hooks |
| Admin/User containers append exclusives | Executions table merge |
| | Ambiguous panel |
| | Broker status rich renderer (User override) |

Suggested path (convention TBD): e.g. `frontend/src/shared/orders/orderReadColumns.ts` — **not created in this STEP**.

---

## 11. Filter / query

Filters similar (status/symbol/account) but Admin has broker/exchange/offset · User has date RangePicker.  
**M6-B: out of scope** (columns only). Query/hook share → later M6-E candidate.

---

## 12. Safety / regression

| Check | Result |
|-------|--------|
| TradingOrder / Outbox / create_order / POST orders | **0** |
| LIVE/ARM/Scheduler/Runtime | **0** |
| M5 Hub / M6-A shim | **untouched** |
| production mutation | **0** |
| commit / push | **none** |
| WIP | **protected** |

---

## 13. Limitations

1. Title locale EN vs KO — shared defs need title injection.  
2. Admin list omits `created_at` — User-only today.  
3. Broker status renderer is product UX — not shareable as-is.  
4. Executions schemas diverge — do not fold into M6-B.  
5. Admin paper sub-table uses different qty field (`requested_quantity`) — secondary.

---

## 14. Next STEP (exactly one)

**M6-B — Implement COMMON_READ order columns (RO only)** (승인 후)

본 PRECHECK에서 구현 **시작하지 않음**.
