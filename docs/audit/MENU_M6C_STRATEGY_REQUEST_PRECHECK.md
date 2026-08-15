# MENU M6-C0 — Strategy Request READ Presentation Precheck

**Mode:** READ-ONLY PRECHECK ONLY · **production mutation = 0**  
**Date:** 2026-08-15  
**Baseline:** M6-B `87d0229` · M6-A STATUS_COLOR shared · M6-0 `SHARED_PRESENTATION_DIFFERENT_ACTION`  
**Verdict:** `STRATEGY_REQUEST_READ_SHARE_RECOMMENDED`

> shared component/columns/hook 생성 · approve/reject/create/cancel 공용화 · route/API/permission · commit/push **금지**.

---

## 0. Baseline

| Item | Status |
|------|--------|
| HEAD | `87d0229` refactor(ui): share read-only order columns |
| M6-0 hint | Strategy Request = SHARED_PRESENTATION_DIFFERENT_ACTION |
| M6-A | `STRATEGY_REQUEST_STATUS_COLOR` already shared (both pages import) |
| M6-B | Order COMMON_READ — **untouched** this STEP |
| This STEP | re-verify list/detail/history/actions with live source |

---

## 1. Routes (actual)

| Role | Route | Page |
|------|-------|------|
| Admin | `/admin/strategy-requests` | `frontend/src/app/(admin)/admin/strategy-requests/page.tsx` |
| User | `/user/strategy-requests` | `frontend/src/app/(user)/user/strategy-requests/page.tsx` |

Menu: Admin (no new `menu:*` — admin layout role) · User `minAccess: user`.  
Backend: Admin router `Depends(require_admin)` · User owner/`OWNERSHIP_DENIED`.

**Route merge:** **금지** (유지).

---

## 2. Business roles (code)

| | Admin | User |
|--|-------|------|
| Primary | 전체 요청 심사 (status filter 기본 `PENDING_REVIEW`) | 본인 요청 생성 + 목록 |
| List | all users · filter by status | own list (`listStrategyRequests`) |
| Detail | Drawer · Descriptions · reviewer fields | Drawer · lighter text |
| Mutations | **approve** · **reject** (+ `review_note`) | **create** · **cancel** |
| History | GET history table in Drawer | **없음** (FE history API 미호출) |
| Extra | link → Candidate Lifecycle | Candidate lifecycle eligibility gate before create |

---

## 3. Page metrics (source measure)

| Metric | Admin | User |
|--------|------:|-----:|
| LOC | **272** | **308** |
| Extracted feature components | **0** (page-local) | **0** |
| `useState` | **3** | **4** |
| `useEffect` | **0** | **0** |
| `useQuery` (GET surfaces) | **3** | **3** |
| `useMutation` | **2** | **2** |
| Significant UI handlers (approx) | **6** | **8** |
| API client calls used | **5** | **5** |
| GET | **3** | **3** |
| Mutation | **2** | **2** |
| `<Table>` | **2** (list + history) | **1** (list) |
| `<Drawer>` | **1** | **1** |
| `<Modal>` | **0** | **0** |
| Major sections | **4** (alert/filter/list/drawer) | **4** (alert/create card/list/drawer) |

---

## 4. API matrix

### Admin (`adminApi`)

| Op | Endpoint |
|----|----------|
| list | `GET /admin/strategy-requests` |
| detail | `GET /admin/strategy-requests/{id}` |
| history | `GET /admin/strategy-requests/{id}/history` |
| approve | `POST .../approve` |
| reject | `POST .../reject` |

### User (`userApi`)

| Op | Endpoint |
|----|----------|
| lifecycle (create gate) | `GET /user/ai-candidates/{id}/lifecycle` |
| create | `POST /user/strategy-requests` |
| list | `GET /user/strategy-requests` |
| detail | `GET /user/strategy-requests/{id}` |
| cancel | `POST .../cancel` |

**Overlap class:** `DIFFERENT_ENDPOINT_SAME_SCHEMA` for list/detail  
(same service `_to_dict` shape; admin vs user path + scope).  
History: Admin-only FE. Mutations: **no overlap** (KEEP_SEPARATE).

---

## 5. Row / detail type

Backend `_to_dict` fields (shared service):  
`strategy_request_id`, `candidate_id`, `user_id`, `reviewer_user_id`, `status`,  
`candidate_lifecycle_status_snapshot`, `candidate_status_at_review`,  
`candidate_fingerprint_at_review`, `request_note`, `review_note`, `version`,  
`requested_at`, `reviewed_at`, `cancelled_at`, `created_at`, `updated_at`.

| Side | FE typing |
|------|-----------|
| User | `StrategyRequestItem` (typed) |
| Admin | `JsonValue` → `asRecord` / `cell` |

**Verdict:** `STRUCTURALLY_COMPATIBLE` (same backend dict; Admin untyped Record).  
Do **not** merge Admin/User API client types into one mega-type for containers.

---

## 6. List column matrix

### Admin list (6 READ · 0 action columns)

| # | title | dataIndex | Class |
|---|-------|-----------|-------|
| 1 | ID | `strategy_request_id` | COMMON_READ |
| 2 | Candidate | `candidate_id` | COMMON_READ |
| 3 | User | `user_id` | ADMIN_ONLY_READ |
| 4 | 상태 | `status` | COMMON_READ |
| 5 | 요청 시점 Candidate 상태 | `candidate_lifecycle_status_snapshot` | ADMIN_ONLY_READ |
| 6 | 요청일시 | `requested_at` | COMMON_READ |

### User list (4 READ · 0 action columns)

| # | title | dataIndex | Class |
|---|-------|-----------|-------|
| 1 | ID | `strategy_request_id` | COMMON_READ |
| 2 | Candidate | `candidate_id` | COMMON_READ |
| 3 | 상태 | `status` | COMMON_READ |
| 4 | 요청일시 | `requested_at` | COMMON_READ |

| Metric | Value |
|--------|------:|
| common_read keys | **4** |
| Admin read | **6** |
| User read | **4** |
| **common_read_ratio** | **4 / min(6,4) = 1.0** |
| Admin-only | `user_id`, `candidate_lifecycle_status_snapshot` |
| User-only list | **none** |
| Table action columns | **0** (actions live in Drawer) |

Status Tag: both use `STRATEGY_REQUEST_STATUS_COLOR` + identical Tag pattern.

---

## 7. Status presentation

| Item | Status |
|------|--------|
| `STRATEGY_REQUEST_STATUS_COLOR` | **Already shared** (M6-A) · both pages |
| Tag render | near-duplicate (inline) · pure presentation |
| Extra status helpers | **none** (no separate label map / terminal helper on these pages) |
| User local `asRecord` | still page-local duplicate (Admin uses shared `asRecord`) — optional cleanup only |

---

## 8. Detail / Request summary

| Field / UI | Admin | User | Class |
|------------|:-----:|:----:|-------|
| status Tag | Y | Y | COMMON |
| candidate Tag | Y | Y | COMMON |
| `user_id` | Y | (typed, not emphasized) | ADMIN_VISIBILITY |
| `reviewer_user_id` | Y | not shown | ADMIN_ONLY_UI |
| lifecycle snapshot | Descriptions | secondary text | SIMILAR |
| `request_note` / `review_note` | Y | Y | COMMON |
| `requested_at` / `reviewed_at` | Y | Y | COMMON |
| `cancelled_at` | not in Descriptions | Y | USER_ONLY_UI |
| Approve/Reject panel | Y | — | ADMIN_ACTION |
| Cancel panel | — | Y | USER_ACTION |

**Summary overlap:** `SIMILAR_STRUCTURE` (not TRUE_DUPLICATE layout — Descriptions vs Typography).  
**Workflow:** `DIFFERENT_WORKFLOW` for actions.

---

## 9. History UI

| | Admin | User |
|--|-------|------|
| FE history | Table: action / previous_status / new_status / **actor** / created_at | **Absent** |
| Actor visibility | shown (`actor`) | N/A — must not leak via shared history without filter |

**HISTORY_SHARING:** `KEEP_SEPARATE` / low value until User history exists.  
If ever shared: **exclude or gate `actor`** for User.

---

## 10–12. Mutations · isolation · capability risk

| Action | Owner | Share? |
|--------|-------|--------|
| APPROVE / REJECT | Admin Drawer | **KEEP_SEPARATE** |
| CREATE / CANCEL | User | **KEEP_SEPARATE** |

Owner/permission must stay in containers + backend.  
Full `<RequestView isAdmin canApprove …>` → **high capability-prop risk** → **OPTION E 비추천**.

Preferred: **Separate Containers → Shared Read Presentation only**.

---

## 13–16. Sharing judgments

| Surface | Verdict | Notes |
|---------|---------|-------|
| **LIST_SHARING** | **SHARE_TABLE_COLUMNS** | 4 COMMON_READ · ratio **1.0** · Admin appends 2 columns |
| **DETAIL_SHARING** | **OPTIONAL / LOW–MED** | similar fields; layout differs; hide reviewer for User |
| **HISTORY_SHARING** | **KEEP_SEPARATE** | User FE history missing · actor sensitivity |

### Options

| Option | Eval |
|--------|------|
| A KEEP_SEPARATE | Safe but leaves 4 identical list defs |
| B FORMATTERS / STATUS ONLY | **Already largely done** (STATUS_COLOR); Tag helper optional micro-gain |
| **C COMMON READ TABLE COLUMNS** | **Recommended** (M6-B pattern) |
| D SHARED SUMMARY / HISTORY | Summary optional later; History **no** |
| E FULL COMPONENT + capability props | **Reject** (approve/cancel diverge) |

**Recommended option:** **OPTION C** (+ retain M6-A formatters; no E).

---

## 17. Proposed M6-C scope (design only — do not implement now)

**M6-C (LOW):** Strategy Request COMMON_READ list columns (4 keys) + keep Admin-only append; status Tag continues to use shared color map.  
**Out of scope forever for this pair:** approve / reject / create / cancel / query hooks / route merge.  
**M6-C2 (optional later):** RO RequestSummary presentational **without** reviewer/actor leakage — only if duplication pain rises. History only if User history ships.

---

## 18–21. Safety / regression

| Check | Result |
|-------|--------|
| route / permission / AuthGuard / backend API | **0** (this STEP) |
| owner isolation | unchanged · presentation-only share candidate |
| TradingOrder / Outbox / create_order / POST orders | **0** |
| M5 Hub | **untouched** |
| M6-A user→admin utils | **0** maintained |
| M6-B orderReadColumns | **untouched** |
| residual WIP | **untouched** |
| production mutation | **0** |
| commit / push | **금지** |

---

## 22. Next STEP (exactly one)

**M6-C — Implement Strategy Request COMMON_READ list columns (RO only)** (승인 후).  
Approve/Reject/Create/Cancel · History · shared hook · route/API **금지**.
