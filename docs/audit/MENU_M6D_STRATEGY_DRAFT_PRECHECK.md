# MENU M6-D0 — Strategy Draft READ Presentation Precheck

**Mode:** READ-ONLY PRECHECK ONLY · **production mutation = 0**  
**Date:** 2026-08-15  
**Baseline:** M6-C `a3612c0` · M6-A `STRATEGY_DRAFT_STATUS_COLOR` shared · M6-0 §5.4 SHARE_FORMATTER (list only)  
**Verdict:** `STRATEGY_DRAFT_FORMATTER_ALREADY_SHARED_SUFFICIENT`

> M6-D column/component 구현 · mutation 공용화 · route/API/permission · commit/push **금지**.  
> **M6-D = SKIP** → next **M6-E0**.

---

## 0. Baseline

| Item | Status |
|------|--------|
| HEAD | `a3612c0` refactor(ui): share strategy request read columns |
| M6-0 | Strategy Draft → **SHARE_FORMATTER only** · Admin hub dwarfs User · never share containers |
| M6-A | `STRATEGY_DRAFT_STATUS_COLOR` in `shared/utils/strategyStatusColors.ts` |
| M6-B / M6-C | `shared/orders` · `shared/strategyRequests` — **untouched** this STEP |

---

## 1. Routes (actual)

| Role | Route | Page |
|------|-------|------|
| Admin | `/admin/strategy-drafts` | `frontend/src/app/(admin)/admin/strategy-drafts/page.tsx` |
| User | `/user/strategy-drafts` | `frontend/src/app/(user)/user/strategy-drafts/page.tsx` |

Route merge **금지**.

---

## 2. Roles (code)

| | Admin | User |
|--|-------|------|
| Role | STEP12 **Draft hub** — list + edit + generation + approval + history + comparison + backtest panels | **Owner-scoped READ-ONLY** list + Drawer detail |
| Scope | Admin / all requests | Own drafts via `GET /user/strategy-drafts` |
| Mutations | Many (create/revision/update/archive/approve/reject/generate/…) | **0** |
| History / actor | Yes (tables with `actor`) | **None** |

---

## 3. Page metrics

| Metric | Admin | User |
|--------|------:|-----:|
| LOC | **5202** | **142** |
| Extracted draft feature components | 0 (page-local mega) | 0 |
| `useState` | **~66** | **1** (`selectedId`) |
| `useEffect` | **0** | **0** |
| `useQuery` | **54** | **2** |
| `useMutation` | **30** | **0** |
| Significant handlers (approx) | **high** (`onClick` ~38+) | **1** (row → drawer) |
| API surface | large Admin draft/generation/approval family | list + detail only |
| GET (page queries) | **54** | **2** |
| Mutation | **30** | **0** |
| `<Table>` | **26** | **1** |
| `<Drawer>` / `<Modal>` | 5 / 5 | 1 / 0 |
| `<Descriptions>` occurrences | **144** | **8** (one detail block) |
| Primary list READ columns | **6** | **5** |
| Action on list | row opens hub edit/detail | row opens RO drawer |

---

## 4. Primary draft **list** column matrix

### Admin primary list (6)

| # | title | dataIndex | Class |
|---|-------|-----------|-------|
| 1 | ID | `draft_id` | ADMIN_ONLY |
| 2 | Version | `label` | EXACT_COMMON |
| 3 | Request | `strategy_request_id` | EXACT_COMMON |
| 4 | 상태 | `status` | EXACT_COMMON |
| 5 | 제목 | `title` | EXACT_COMMON |
| 6 | 생성일시 | `created_at` | EXACT_COMMON |

### User list (5)

| # | title | dataIndex | Class |
|---|-------|-----------|-------|
| 1 | Version | `label` | EXACT_COMMON |
| 2 | Request | `strategy_request_id` | EXACT_COMMON |
| 3 | 상태 | `status` | EXACT_COMMON |
| 4 | 제목 | `title` | EXACT_COMMON |
| 5 | 생성일시 | `created_at` | EXACT_COMMON |

| Metric | Value |
|--------|------:|
| exact common | **5** |
| semantic common | **5** (same Tag status pattern) |
| Admin READ | **6** |
| User READ | **5** |
| **common_read_ratio** | **5 / min(6,5) = 1.0** |
| Admin-only list | `draft_id` |
| User-only list | **none** |

> Ratio alone does **not** justify M6-D: Admin page is a 5k-LOC hub; User is a thin RO list. Touching Admin for −5 duplicated column defs has poor risk/reward vs M6-A formatter already shared.

---

## 5. Field / presentation inventory (beyond list)

| Concern | Admin | User | Class |
|---------|-------|------|-------|
| `draft_id` | list + hub | Drawer title only | SEMANTIC / ADMIN list-only |
| `strategy_request_id` | list | list | EXACT_COMMON |
| `status` Tag | list + many panels | list + drawer | EXACT_COMMON color map |
| `label` / version | list | list | EXACT_COMMON |
| `title` / rules / timeframe | edit + detail hub | RO Descriptions | SEMANTIC_COMMON content · **layout DIFFERENT** |
| `created_at` | `cell` | bare | SEMANTIC_COMMON |
| provider/model | generation tables | typed on item, **not in User list/detail UI** | ADMIN_ONLY UI |
| History + `actor` | yes | no | ADMIN_ONLY · **do not share** |
| Approval / generate / archive | yes | no | ADMIN_ACTION · KEEP_SEPARATE |

**Detail overlap:** `SIMILAR_STRUCTURE` fields · `DIFFERENT_WORKFLOW` / layout (hub vs RO Descriptions).  
**DETAIL_SHARING:** KEEP_SEPARATE / DEFER.  
**HISTORY_SHARING:** KEEP_SEPARATE (actor risk).

---

## 6. M6-A re-check

| Check | Result |
|-------|--------|
| `STRATEGY_DRAFT_STATUS_COLOR` | **Both** pages import `@/shared/utils/strategyStatusColors` |
| Local duplicate STATUS map | **None** found on these pages |
| `cell` / `asRecord` / `extractRows` | Admin uses shared helpers; User does not need them for list |
| user → `@/features/admin` | **0** (drafts pages) |
| admin → `@/features/user` | **0** |
| Admin dataHelpers shim | retained (unchanged this STEP) |

---

## 7. Schema compatibility

| Side | Typing |
|------|--------|
| User | `StrategyDraftItem` (typed) |
| Admin | `JsonValue` / `asRecord` |

Backend family compatible for list fields → `STRUCTURALLY_COMPATIBLE` for the 5 common keys.  
Do **not** unify Admin hub types with User RO type.

API: `DIFFERENT_ENDPOINT_SAME_DOMAIN` — `GET /admin/strategy-drafts` vs `GET /user/strategy-drafts`.

---

## 8. Capability / share options

Full shared Draft component would need hub awareness (generation, approval, edit) → **capability mega-props** → **OPTION E REJECT**.

| Option | Eval |
|--------|------|
| A KEEP_AS_IS | Acceptable (no further DRY) |
| **B FORMATTER_ALREADY_SHARED_SUFFICIENT** | **Recommended** — M6-A done; matches M6-0 |
| C SHARE_COMMON_READ_COLUMNS | Technically possible (5 keys) but **low value** vs Admin hub risk |
| D SMALL PRESENTATIONAL HELPER | Optional Tag helper only — marginal; not worth a STEP |
| E FULL COMPONENT | **REJECT** |

**Recommended:** **OPTION B**  
**M6-D implement?** **NO (SKIP)**

---

## 9. KEEP_SEPARATE

- Entire Admin Draft hub container  
- Approve/reject/create/revision/archive/generate  
- History/audit/`actor`  
- Comparison / attempts / backtest panels  
- User RO Drawer layout  
- Query/filter hooks · routes · permissions · backend  

---

## 10. Safety / regression

| Check | Result |
|-------|--------|
| production mutation this STEP | **0** |
| route / API / permission / AuthGuard / backend | **0** |
| owner isolation | unchanged |
| TradingOrder / Outbox / create_order / POST orders | **0** |
| M5 Hub | **untouched** |
| M6-B `shared/orders` | **untouched** |
| M6-C `shared/strategyRequests` | **untouched** |
| residual WIP | **untouched** |
| commit / push | **금지** |

---

## 11. Next STEP (exactly one)

**M6-E0 — Optional shared presentation final PRECHECK** (승인 후 · READ-ONLY).  
Do **not** start M6-D implementation.
