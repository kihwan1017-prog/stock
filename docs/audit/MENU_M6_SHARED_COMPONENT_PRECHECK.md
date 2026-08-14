# MENU M6-0 — Admin / User Shared Component Consolidation Precheck

**Mode:** READ-ONLY PRECHECK ONLY · **production mutation = 0**  
**Date:** 2026-08-15  
**Branch:** `release/v1.1.0` · baseline M5-F `a738d91`  
**Verdict:** `SHARED_COMPONENT_CONSOLIDATION_DESIGN_READY`

> route merge · permission/AuthGuard · backend/API · owner/admin scope 합치기 **금지**.  
> Shared View · Separate Scope · Separate Permission · Separate Mutation Ownership.  
> M6-A 구현 · commit/push · LIVE/ARM/Runtime **금지**.

---

## 0. Baseline / WIP protection

| Item | Status |
|------|--------|
| M5_CLOSE | YES |
| Upbit Hub structure | protected (no change) |
| Residual WIP | NewsCollector rowKey · Ambiguous · risk/page · RuntimePreflight · backend/ops/.run/tmp — **untouched** |

---

## 1. Principles

| Do | Do not |
|----|--------|
| Share pure presentation / formatters / RO columns | Merge `/admin/*` + `/user/*` routes |
| Keep Admin/User containers | Collapse permissions into one component |
| Extract accidental coupling (`dataHelpers`) | Capability-prop mega-components |
| Wave LOW risk first | Share LIVE/Kill/Recovery/credential CONTROL |

---

## 2. Existing shared surface

| Location | Contents |
|----------|----------|
| `components/common` | `StatusBadge`, `EmptyState`, `ComingSoon`, `PageContainer`, `AppLoading` |
| `shared/components` | `UnimplementedNotice` (+ re-exports) |
| **ALREADY_SHARED** | `ProfileWorkspace` — admin + user profile pages |
| Accidental coupling | User features import `@/features/admin/utils/dataHelpers` (6 files) · `useMarketSessionStatus` → `adminApi` |

`StatusBadge`는 header/dashboard 계열 — Order/Risk/Strategy 도메인 상태맵은 **미공용**.

---

## 3. Route pair matrix (실제 경로만)

| Domain | Admin route | User route | Admin page LOC | User page LOC | Scope Admin | Scope User | Permission hint |
|--------|-------------|------------|---------------:|-------------:|-------------|------------|-----------------|
| Account | `/admin/accounts` | `/user/accounts` (+kiwoom/upbit/paper) | 474 | 7→`AccountsView` | ALL_USERS / UBA / SYSTEM paper | USER_OWNER | `menu:accounts` vs user menu |
| Strategy | `/admin/strategies` | `/user/strategies` | 562 | 1431 | ALL_USERS registry | USER_OWNER + public | `menu:strategies` |
| Strategy Request | `/admin/strategy-requests` | `/user/strategy-requests` | 277 | 313 | ALL_USERS review | USER_OWNER | Admin role (no new menu:*) / user |
| Strategy Draft | `/admin/strategy-drafts` | `/user/strategy-drafts` | **5231** | 146 | ALL_USERS STEP12 hub | USER_OWNER RO | same pattern |
| Order | `/admin/orders` | `/user/orders` (+broker) | 732 | 332 + views | ALL_USERS / ACCOUNT ops | USER_OWNER | `menu:orders` |
| Trade | `/admin/trades` | legacy `/user/trades`→orders | — | redirect | ALL_USERS | USER_OWNER | — |
| Portfolio | `/admin/portfolio` | `/user/portfolio` | 65 | 708 | ACCOUNT selectable | USER_OWNER paper | `menu:portfolio` |
| Risk | `/admin/risk` | `/user/risk` | 519 | 520 | SYSTEM + any user | SELF + UBA | `menu:risk` |
| Notification | `/admin/notifications` | `/user/notifications` | 113 | 524 | SYSTEM ops channels | SELF inbox | `menu:notifications` |
| Backtest | `/admin/backtests` | `/user/backtests` | 59 | 73 | ALL_USERS list | USER_OWNER + run | `menu:backtests` |
| Candidate | `/admin/ai/candidate-*` | `/user/candidates/*` | multi | `CandidatesView` | SYSTEM governance | market screening | `menu:ai` vs user |
| LIVE Validation | `/admin/live-validation/upbit` | `/user/live-validation/upbit` | 377 | 132 | SYSTEM validation ops | USER_OWNER guided smoke | admin vs user |
| Profile | `/admin/profile` | `/user/profile` | 17 | 16 | SELF_PROFILE | SELF_PROFILE | self APIs |
| News* | `/admin/news` | `/user/news` | 101 | 552 | SYSTEM | USER feed | extra pair |
| Disclosures* | `/admin/disclosures` | `/user/disclosures` | 148 | 751 | SYSTEM | USER feed | extra pair |

\* Extra pairs with both sides present.  
**Route pairs counted for core M6 domains: 12** (+2 news/disclosures reference = 14).

**AuthGuard:** role + optional `enforceMenuPermission` / `permissionForPath` — M6에서 변경 **불필요**.  
**API:** Admin `adminApi` vs User `userApi` — 대부분 `DIFFERENT_ENDPOINT_DIFFERENT_SCHEMA` 또는 `DIFFERENT_ENDPOINT_SAME_SCHEMA`; Profile은 self user APIs (`SAME_ENDPOINT_SAME_SCOPE` 계열).

---

## 4. Duplication classification counts

| Class | Count | Domains |
|-------|------:|---------|
| **TRUE_UI_DUPLICATE** | **0** | — |
| **SHARED_PRESENTATION_DIFFERENT_ACTION** | **4** | Strategy Request · Strategy Draft (list) · Orders · Risk |
| **SAME_DOMAIN_DIFFERENT_WORKFLOW** | **3** | Accounts · Strategies · LIVE Validation |
| **SIMILAR_LABEL_ONLY** | **5** | Portfolio · Notifications · Backtests · Candidates · News/Disclosures(agg) |
| **ALREADY_SHARED** | **1** | Profile |

(News+Disclosures를 SIMILAR에 묶어 5; 분리하면 News/Disclosures 각각 SIMILAR.)

---

## 5. Domain verdicts

### 5.1 Account — KEEP_SEPARATE (presentation optional)
- Class: `SAME_DOMAIN_DIFFERENT_WORKFLOW` · Risk **HIGH**
- Admin: paper CRUD · sync · `AdminUpbitLiveUbaPanel` CONTROL · credential admin
- User: `AccountsView` · `BrokerCredentialPanel` owner CRUD
- Share candidate: credential **status** chips only (`SHARE_PRESENTATIONAL`)  
- **Exclude:** LIVE/ARM/Scheduler · pause · secret forms

### 5.2 Strategy — KEEP_SEPARATE
- Class: `SAME_DOMAIN_DIFFERENT_WORKFLOW` · Risk **HIGH**
- Admin governance vs User owned/catalog — optional `SHARE_TYPES` only

### 5.3 Strategy Request — SHARE_FORMATTER + SHARE_TABLE_COLUMNS
- Class: `SHARED_PRESENTATION_DIFFERENT_ACTION` · Risk **MEDIUM**
- Identical `STATUS_COLOR` maps duplicated in both pages
- Admin: approve/reject · User: create/cancel — **KEEP_SEPARATE** mutation UI
- API: different admin/user strategy-request endpoints · ownership server-side

### 5.4 Strategy Draft — SHARE_FORMATTER (list only)
- Class: list = `SHARED_PRESENTATION…` · overall `SAME_DOMAIN_DIFFERENT_WORKFLOW`
- Admin hub **5231 LOC** vs User RO **146** — **KEEP_SEPARATE** admin surface
- Dup `STATUS_COLOR` · Risk **HIGH** if merging containers

### 5.5 Order / Trade — SHARE_TABLE_COLUMNS (RO)
- Class: `SHARED_PRESENTATION_DIFFERENT_ACTION` · Risk **HIGH** for actions
- Similar columns (id/symbol/side/qty/price/status) · Admin submit/cancel/outbox gates
- User broker views largely **READ**
- Exclude Ambiguous / Outbox / all-user controls

### 5.6 Portfolio — KEEP_SEPARATE / NO_ACTION
- Class: `SIMILAR_LABEL_ONLY` · Risk **LOW**
- Admin thin JSON vs User rich holdings UX — low share value

### 5.7 Risk — SHARE_FORMATTER only
- Class: `SHARED_PRESENTATION_DIFFERENT_ACTION` · Risk **HIGH**
- Dup `rateToPercent` / `percentToRate`
- **KEEP_SEPARATE:** Kill · system config · LIVE/ARM residue · global mutation
- User kill **READ-only**

### 5.8 Notification — KEEP_SEPARATE
- Class: `SIMILAR_LABEL_ONLY` · Admin channel health vs User inbox

### 5.9 Backtest — KEEP_SEPARATE
- Class: `SIMILAR_LABEL_ONLY` · Admin list vs User MA runner — result renderer not shared yet

### 5.10 Candidate — KEEP_SEPARATE
- Class: `SIMILAR_LABEL_ONLY` · Admin AI lifecycle vs User scoreboard

### 5.11 LIVE Validation — KEEP_SEPARATE (+ optional run columns)
- Class: `SAME_DOMAIN_DIFFERENT_WORKFLOW` · Risk **HIGH**
- Optional `SHARE_TABLE_COLUMNS` for run history only

### 5.12 Profile — NO_ACTION (ALREADY_SHARED)
- Class: `ALREADY_SHARED` · Pattern E already: Shell prop + same workspace
- Do **not** confuse with `/admin/members`

### Excluded domains (reference only)
Runtime · Scheduler · Recovery · System ops · Upbit Hub (News/Scanner/A-B/Ops) · Admin LIVE CONTROL · Members · Credential admin · System settings → **KEEP_SEPARATE**

---

## 6. Share-action inventory

| Action | Candidates |
|--------|------------|
| SHARE_COMPONENT | none new (Profile done) |
| SHARE_PRESENTATIONAL | credential status chips (optional) · strategy request detail summary RO |
| SHARE_TABLE_COLUMNS | Strategy Request list · Order RO columns · LIVE run history (opt) |
| SHARE_FORMATTER | Strategy Request/Draft `STATUS_COLOR` · Risk rate↔% · money/% (opt) |
| SHARE_HOOK | relocate `dataHelpers` → `shared/utils` (decouple user→admin) · opt market session |
| SHARE_TYPES | Strategy row / Order row types (opt) |
| KEEP_SEPARATE | Accounts CONTROL · Strategies · Draft hub · Risk Kill · Notifications · Backtests · Candidates · LIVE execute · Upbit Hub · Recovery · Members |
| NO_ACTION | Profile |

---

## 7. Top 10 share candidates (ranked)

| # | Domain | What | Dup | Risk | Benefit | Pattern | Complexity |
|---|--------|------|-----|------|---------|---------|------------|
| 1 | Cross-cutting | Move `dataHelpers` to shared | HIGH accidental | LOW | Decouple user→admin | B/D | LOW |
| 2 | Strategy Request | `STATUS_COLOR` module | HIGH | LOW | DRY badges | B | LOW |
| 3 | Strategy Draft | `STATUS_COLOR` module | HIGH | LOW | DRY badges | B | LOW |
| 4 | Risk | `rateToPercent`/`percentToRate` | HIGH | LOW | DRY forms | B | LOW |
| 5 | Strategy Request | RO list column defs | MEDIUM | MEDIUM | Consistent table | B/E | LOW–MED |
| 6 | Orders | RO column defs | MEDIUM | MEDIUM | Consistent table | B/E | MED |
| 7 | Strategy Request | Detail summary presentational | MEDIUM | MEDIUM | Less copy | A/E | MED |
| 8 | LIVE Validation | Run history columns | LOW–MED | MEDIUM | Minor | B | LOW |
| 9 | Accounts | Credential status chips | MEDIUM | MEDIUM | Visual parity | A | MED |
| 10 | Strategy | Shared types only | LOW | LOW | Typing | SHARE_TYPES | LOW |

---

## 8. Top 10 do-not-share

1. Admin LIVE/ARM/Scheduler (`AdminUpbitLiveUbaPanel`)  
2. Risk Kill Switch / system risk save  
3. Recovery CONTROL panels  
4. Strategy Draft admin STEP12 hub (5231 LOC)  
5. Strategy approve/reject vs user create/cancel merged UI  
6. Order submit/cancel/outbox/Ambiguous  
7. Credential secret entry forms  
8. Upbit Hub Scanner/News/A-B/Ops  
9. Candidate promotion/lifecycle admin  
10. LIVE Validation execute / guided smoke confirm merge  

---

## 9. Capability-prop risk

Merging Admin Orders or Risk into one component with `isAdmin|canApprove|canKill|canLive|…` → **HIGH** — **KEEP_SEPARATE**.  
Preferred: **Pattern E** Separate container → shared view/formatter only.

---

## 10. Policy answers

| Question | Answer |
|----------|--------|
| Route merge needed? | **NO** |
| Backend/API change needed for M6? | **NO** (default) |
| Permission change? | **NO** |
| AuthGuard change? | **NO** |
| Owner isolation impact if waves follow design? | **None** (containers keep scope) |

---

## 11. Implementation waves (proposed)

| Wave | Scope | Risk |
|------|-------|------|
| **M6-A** | `shared/utils/dataHelpers` extract · Strategy Request/Draft `STATUS_COLOR` · Risk rate helpers | LOW |
| **M6-B** | Order RO table column module (no mutations) | LOW–MED |
| **M6-C** | Strategy Request RO list/summary presentational | MED |
| **M6-D** | Optional Draft RO list presentational (not admin hub) | MED |
| **M6-E** | Optional credential status chips · LIVE run columns — **gate separately** | MED |

한 번에 전체 공용화 **금지**.

---

## 12. Safety / M5 / WIP

| Check | Result |
|-------|--------|
| TradingOrder / Outbox / create_order / POST orders | **0** |
| LIVE/ARM/Scheduler/Kill/Recovery execution | **0** |
| M5 Hub regression | **none** (untouched) |
| production mutation | **0** |
| commit / push | **none** |

---

## 13. Limitations

1. No TRUE_UI_DUPLICATE beyond Profile (already shared) — consolidation value is **incremental DRY**, not page merge.  
2. Admin Strategy Draft size dwarfs User — never share containers.  
3. User→`admin/utils` coupling should be fixed early to avoid “fake shared via admin folder”.  
4. Residual Hub/Risk WIP out of scope.  
5. API schemas not byte-compared; classification uses call sites + UI structure.

---

## 14. Next STEP (exactly one)

**M6-A — LOW-risk shared formatters / utils extraction** (승인 후 · production 최소 · route/API 불변)

M6-A 구현은 본 PRECHECK에서 **시작하지 않음**.
