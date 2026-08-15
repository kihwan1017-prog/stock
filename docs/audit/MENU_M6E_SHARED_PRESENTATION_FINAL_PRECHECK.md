# MENU M6-E0 — Optional Shared Presentation Final Precheck

**Mode:** READ-ONLY PRECHECK ONLY · **production mutation = 0**  
**Date:** 2026-08-15  
**Baseline:** M6-C `a3612c0` · M6-D0 Draft **SKIP** · M6-0 `SHARED_COMPONENT_CONSOLIDATION_DESIGN_READY` · M5 Hub CLOSE  
**Verdict:** `SHARED_COMPONENT_CONSOLIDATION_COMPLETE_WITH_LIMITATIONS`

> **M6-E = SKIP** · formal **M6-F** FINAL REGRESSION / CLOSE audit next.  
> production · route/API/permission · commit/push **금지**.

---

## 0. Purpose

Not “what else *could* be shared?” but “does **additional** share still pay for itself?”  
Primary M6 waves (A–C) already delivered the high-value presentation DRY. Remaining optional items from M6-0 are **marginal** or **HIGH_COUPLING**.

---

## 1. M6 baseline (do not regress)

| Wave | Outcome |
|------|---------|
| M6-0 | DESIGN_READY |
| M6-A | shared utils/formatters · user→admin dataHelpers **0** · shim retained |
| M6-B | Order COMMON_READ **7** columns |
| M6-C | Strategy Request COMMON_READ **4** columns |
| M6-D0 | Draft formatter sufficient · **M6-D SKIP** |
| M5 | Upbit Hub CLOSE_WITH_LIMITATIONS |

---

## 2. Domains surveyed (7+ primary)

| Domain | Admin | User | Workflow | Classification |
|--------|-------|------|----------|----------------|
| Account | `/admin/accounts` (~452 LOC) + LIVE UBA panel | `AccountsView` (~732) + credential | CONTROL vs owner CRUD + LIVE tags | **KEEP_SEPARATE** |
| Portfolio | thin JSON table (~60) | rich holdings (~666) + WIP rowKey | SIMILAR_LABEL_ONLY | **NO_ACTION** |
| Risk | Kill + system/user forms | self/UBA limits | formatter shared; Kill KEEP | **ALREADY_SHARED** (+ KEEP Kill) |
| Notification | channel health (~104) | inbox (~498) | different schemas | **KEEP_SEPARATE** |
| Backtest | list (~51) | MA runner (~68) | SIMILAR_LABEL_ONLY | **KEEP_SEPARATE** |
| Candidate | AI lifecycle/promotion multi | scoreboard/candidates | governance vs screening | **HIGH_COUPLING_REJECT** |
| LIVE Validation | execute + runs (~361) | Guided smoke + history (~124) | execute vs guided | **KEEP_SEPARATE** / **HIGH_COUPLING_REJECT** |
| Orders | (done M6-B) | (done M6-B) | — | **ALREADY_SHARED** |
| Strategy Request | (done M6-C) | (done M6-C) | — | **ALREADY_SHARED** |
| Strategy Draft | STATUS color (M6-A) · hub KEEP | RO list | — | **ALREADY_SHARED** (+ SKIP columns) |
| Profile | `ProfileWorkspace` + Shell prop | same | Pattern E | **ALREADY_SHARED** / **NO_ACTION** |
| Strategy catalog | admin governance | user catalog | — | **KEEP_SEPARATE** |
| Upbit Hub / Recovery / Runtime | — | — | ops CONTROL | **HIGH_COUPLING_REJECT** |

### Classification tally (surveyed rows above)

| Class | Count (approx) |
|-------|---------------:|
| ALREADY_SHARED | **5** (Orders, Request, Draft color, Risk rate helpers, Profile) |
| SHARE_SMALL_FORMATTER (remaining worth a STEP) | **0** |
| SHARE_SMALL_PRESENTATION (remaining worth a STEP) | **0** |
| KEEP_SEPARATE | **6** (Account, Notification, Backtest, LIVE Val, Strategy, + Kill side of Risk) |
| NO_ACTION | **2** (Portfolio asymmetry, Profile done) |
| HIGH_COUPLING_REJECT | **3** (Candidate promotion, LIVE execute merge, Hub/Recovery/Runtime) |

---

## 3. Optional M6-0 leftovers — gate against §4 criteria

| Candidate (M6-0 #) | Consumers | Pure RO? | Capability risk | Verdict |
|--------------------|-----------|----------|-----------------|---------|
| Credential status chips (#9) | AdminBrokerCredentialCard · User BrokerCredentialPanel | partial (next to secret CRUD / LIVE) | MED–HIGH | **KEEP_SEPARATE** — not M6-E |
| LIVE run history columns (#8) | Admin live-validation · User guided history | RO subset only | MED (adjacent execute_live) · schema drift (`internal_status` vs `display_status`) | **KEEP_SEPARATE** — benefit LOW |
| Request detail summary (#7) | Admin/User drawers | RO | MED layout diverge | **DEFER / NO_ACTION** (M6-C list enough) |
| Strategy shared types (#10) | typing only | n/a | LOW | **NO_ACTION** (not presentation STEP) |
| money/`toLocaleString` helpers | mostly **User**-local (portfolio/dashboard/trading) + `utils/format.ts` | yes | LOW | **NO_ACTION for M6-E** — not Admin↔User consolidation; optional later outside M6 |

**M6-E implementation candidates:** **none** that pass all §4 gates with clear maintenance payoff.

---

## 4. Existing shared inventory

### `frontend/src/shared/`

| Area | Contents | Consumers (≥2?) | Audit |
|------|----------|-----------------|-------|
| `shared/utils/dataHelpers` | `asRecord`, `cell`, `extractRows` | many Admin (+ User via direct import) | OK · presentation helpers |
| `shared/utils/strategyStatusColors` | REQUEST + DRAFT maps | Admin+User Request/Draft pages | OK |
| `shared/utils/riskRatePercent` | `rateToPercent` / `percentToRate` | Admin+User risk pages | OK |
| `shared/orders/orderReadColumns` | 7 COMMON_READ | Admin orders · User orders · BrokerOrdersView (**3**) | OK · no mutation/API/permission |
| `shared/strategyRequests/…` | 4 COMMON_READ + status Tag | Admin+User strategy-requests (**2**) | OK · capability props **0** |
| `shared/components` | UnimplementedNotice re-exports | legacy | OK |

### Outside `shared/` but M6-relevant

| Item | Path | Notes |
|------|------|-------|
| StatusBadge / EmptyState / PageContainer | `components/common/` | pre-existing shell UI |
| ProfileWorkspace | `features/user/profile/` | Admin profile imports User workspace (intentional Pattern E) |
| Admin dataHelpers shim | `features/admin/utils/dataHelpers.ts` | re-export only · **keep** (~60 consumers) |

### Import / graph

| Check | Result |
|-------|--------|
| user → `@/features/admin/utils/dataHelpers` | **0** |
| user → `@/features/admin/*` (app+features user tree) | **0** |
| admin → `@/features/user/` | Profile page (**intentional**) · test file only otherwise |
| circular shared dependency | **0** observed |
| capability mega-props on M6 shared columns | **0** |
| shared hooks created in M6 | **0** |
| shared React mega page components in M6 | **0** |
| route / API / permission merges in M6 | **0** |

---

## 5. Domain notes (evidence)

### Account
Admin paper list ≠ User broker/LIVE status Tags + credential CRUD. LIVE CONTROL on accounts surface stays **KEEP_SEPARATE** (M4 canonical). Chips alone do not justify a wave.

### Portfolio
Admin: `symbol` / `quantity` / `average_entry_price` only.  
User: exchange, prices, valuation, return, weight, history — **asymmetric**. WIP rowKey **untouched**.

### Risk
M6-A helpers already used both sides. Kill Switch / system save / LIVE residue **KEEP_SEPARATE**. Residual risk WIP **untouched**.

### Notification / Backtest / Candidate
Label similarity only · different workflows · **KEEP_SEPARATE** / Candidate promotion **HIGH_COUPLING_REJECT**.

### LIVE Validation
Run tables overlap partially (`run_id`, broker status, market, order_id) but status fields differ; Admin has `executeMut` / `execute_live`. Sharing columns next to LIVE execute **rejected**.

---

## 6. Over-abstraction check (M6 new modules)

| Module | Consumers | Mutation/route/perm? | Over-abstracted? |
|--------|-----------|----------------------|------------------|
| `orderReadColumns` | 3 | No | **No — KEEP** |
| `strategyRequestReadColumns` | 2 | No | **No — KEEP** |
| formatters (STATUS, rate) | ≥2 each | No | **No — KEEP** |

---

## 7. M6 scorecard (presentation mission)

| Metric | Approx |
|--------|-------:|
| New shared utils/helpers (M6-A) | **7** (asRecord, extractRows, cell, 2 STATUS maps, rate↔%, index) |
| Shared COMMON_READ column keys (B+C) | **11** (7+4) |
| Shared presentation column modules | **2** |
| Shared hooks (M6) | **0** |
| Shared mega components (M6) | **0** |
| Capability props (M6 shared) | **0** |
| user→admin utils imports removed | **13 → 0** (M6-A) |
| admin→user (non-Profile) | **0** product pages |
| Route merges | **0** |
| API merges | **0** |
| Permission merges | **0** |

Mission check: M6 stayed **presentation / formatter / RO columns** — **PASS**.

---

## 8. Regressions (this STEP)

| Area | Result |
|------|--------|
| M6-A / shim / cross-import | OK (docs only) |
| M6-B orders / M6-C requests | **untouched** |
| M6-D SKIP | **confirmed** |
| M5 Hub production | **untouched** |
| M4 LIVE on accounts · Risk LIVE mutation removed | **not reopened** |
| TradingOrder / Outbox / create_order / POST orders | **0** |
| Scanner / News A/B policy | **0** |
| residual WIP | **untouched** |
| production mutation | **0** |

---

## 9. Decision

| Question | Answer |
|----------|--------|
| M6-E needed? | **NO — SKIP** |
| Recommended final verdict | **`SHARED_COMPONENT_CONSOLIDATION_COMPLETE_WITH_LIMITATIONS`** |
| M6 CLOSE possible? | **YES** (pending formal **M6-F** regression/CLOSE audit — no auto-close here) |

Limitations (carry to M6-F): Admin shim not bulk-migrated · Draft hub / Account LIVE / Portfolio asymmetry remain · optional money helper not in M6 · residual Hub/Risk/portfolio WIP out of scope.

---

## 10. Next STEP (exactly one)

**M6-F — FINAL REGRESSION / M6 CLOSE** (승인 후 · audit-first; production only if blockers found).  
M6-E 구현 · M7 · commit/push **금지** in this STEP.
