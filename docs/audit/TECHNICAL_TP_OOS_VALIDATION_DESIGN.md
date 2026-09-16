# TECHNICAL TP OOS VALIDATION DESIGN

**Mode:** READ-ONLY DESIGN ONLY · **production mutation = 0**  
**Date:** 2026-08-15  
**HEAD:** `4f0df10`  
**Baseline review:** `TECHNICAL_TP_CHANGE_CANDIDATE_REVIEW`  
**Verdict:** `CANDIDATE_DEFINITION_REQUIRED`

> TP/settings/DB/LIVE/주문 **변경 금지**. OOS **미시작**. commit/push **금지**.

---

## 0. Why not OOS-ready yet

| Blocker | Detail |
|---------|--------|
| Candidate | **2–4% band** — not a single freezable TP |
| Evidence | MFE reach proxy only · **no** alternate-TP PnL on discovery cohort |
| Freeze rule | Selecting 2 vs 3 vs 4% from same in-sample MFE table = new optimization |

→ OOS start **blocked** until a single candidate is frozen by a dedicated definition STEP.  
OOS *method* below remains the preferred design once freeze succeeds.

---

## 1. Existing data capability

### Stored on `trading.upbit_opportunity_shadow`

| Concept | Column / JSON | Source |
|---------|---------------|--------|
| entry | `entry_price` | scanner create |
| windows | `price_*m`, `return_*m_pct`, `evaluated_*m_at` | evaluator + `observe_windows` |
| MFE/MAE | `mfe_pct`, `mae_pct` | `compute_mfe_mae` (max high / min low) |
| TP/SL flags | `tp_hit`, `sl_hit`, `tp_hit_at`, `sl_hit_at` | `compute_tp_sl` @ **configured** TP/SL |
| path meta | `evaluation_detail.tp_sl` (`first_hit`, prices, bars_checked) | evaluator payload |
| MFE detail | `evaluation_detail.mfe_mae_detail` | max_high/min_low used |
| windows meta | `evaluation_detail.windows` | selection_type / lag |
| identity | `shadow_id`, `scanner_run_id`, `symbol`, `scanner_rank`, `scanner_score` | create |
| times | `detected_at`, `completed_at` | create / complete |
| snapshot | `entry_snapshot` JSONB | create |

### Not stored on shadow row

| Missing | Implication |
|---------|-------------|
| Full 1m OHLC path | Cannot recompute alternate TP from row alone |
| Exit price under alternate TP | Must re-run `compute_tp_sl` on bars |
| Per-bar sequence dump | Available only via reload |

### Reload path (existing)

`ensure_shadow_minute_bars` → `market.candle_minute` (+ sync) → `candle_path.compute_tp_sl(..., tp_pct=X, sl_pct=3)`.

Same-candle both-touch policy already coded: **`SAME_CANDLE_SL_CONSERVATIVE`** (SL first). Intrabar true order unknown → **AMBIGUOUS** at minute grain; policy makes it **deterministic**, not estimated.

---

## 2. Counterfactual feasibility

| Mode | Feasibility |
|------|-------------|
| Shadow columns only (MFE≥X as “would hit TP”) | **PARTIAL** — ignores SL path / first_hit |
| Reload bars + existing `compute_tp_sl` for TP∈{2,3,4,6} | **EXACT** under documented SL-conservative minute rule |
| True intrabar tick order | **NOT_SUPPORTED** |

**COUNTERFACTUAL_PNL = PARTIAL** (stored) / **EXACT-under-policy** (recompute).  
Overall design label: **PARTIAL** with clear recompute upgrade path (no schema invention required).

**TP/SL ordering availability:** YES via `first_hit` + `tp_hit_at`/`sl_hit_at` for current TP; for alternate TP must recompute (same policy).

---

## 3. Discovery / OOS unit

| Item | Proposal |
|------|----------|
| **DISCOVERY_COHORT** | All `status=COMPLETED` with `shadow_id ≤ 51` **OR** `completed_at ≤ 2026-08-14T23:25:40.424Z` (max COMPLETED as of design) |
| Freeze ids | shadow_id **1…51** COMPLETED (+ ACTIVE at design time excluded from discovery outcomes) |
| **OOS_START** | First new `COMPLETED` with `shadow_id > 51` **and** `completed_at > 2026-08-14T23:25:40.424Z` |
| Rule | Discovery rows **never** enter OOS metrics |

---

## 4. Candidate freeze

| Check | Result |
|-------|--------|
| Single TP freezable from discovery evidence? | **NO** |
| Reasons | Band hypothesis; MFE proxy; no PnL ranking 2 vs 3 vs 4; picking one = in-sample opt |
| Status | **`CANDIDATE_NOT_FREEZABLE`** |
| Frozen candidate proposal | **none** (must wait for definition STEP) |

---

## 5. Design options

| Option | Idea | Pros | Cons | Code | DB | Runtime | Look-ahead | Ops risk |
|--------|------|------|------|------|-----|---------|------------|----------|
| **A** | New OOS observe only under frozen single candidate vs 6% | Simple compare | Needs freeze first; dual bookkeeping | LOW–MED | NONE–LOW | LOW | OK if freeze | LOW |
| **B** | Parallel shadow TP 6/2/3/4 on same new signals | Fair same-path | Multi-policy storage; higher complexity | **HIGH** | MED | MED | Careful | MED |
| **C (preferred)** | Keep live Shadow TP=**6%**; OOS post-hoc recompute 2/3/4/6 via `candle_path` on **new** COMPLETED only | No policy change; reuses evaluator math; no orders | Needs candle availability; same-candle ambiguity policy | **LOW–MED** | NONE | LOW (batch/read job) | Strong if cutoff frozen | **LOW** |

**Recommended:** **OPTION C** after candidate freeze. Until freeze: do **not** start OOS accumulation for apply decisions.

---

## 6. Metrics (freeze before OOS)

### Primary (proposed — no existing OOS policy)

**Counterfactual exit return %** at first_hit under `{TP_candidate, SL=3%}` using `compute_tp_sl` + exit at hit bar (or 60m mark if neither).

Rationale: closest to existing evaluator semantics; return_60m alone ignores early TP/SL exit.

### Guards (report-only)

| Guard | Source |
|-------|--------|
| MAE / loss rate / median return | existing fields or recompute |
| STRICT_VALID rate | same VALID definition as milestone |
| Symbol concentration of wins | report MFE/exit by symbol |
| Coverage / bars_checked | `evaluation_detail` / recompute |

### Existing OOS sample policy

**`NO_EXISTING_OOS_SAMPLE_POLICY`**

### Proposed (explicitly non-canonical)

| Gate | n | Anchor |
|------|--:|--------|
| **MIN_REVIEW** | **30** | `VALID_COHORT_THRESHOLD` |
| **TARGET_REVIEW** | **50** | soft `MORE_SAMPLE_RECOMMENDED_AT_50` |

---

## 7. OOS decision rule (design-only; not applied)

Assume one frozen candidate `C` and primary = counterfactual exit return.

| Outcome | Sketch |
|---------|--------|
| **KEEP_6** | OOS primary(C) ≤ primary(6) within noise / guards worse |
| **CHANGE_TO_CANDIDATE** | primary(C) > primary(6) **and** guards not worse **and** n≥TARGET **and** concentration not single-symbol driven — still needs separate APPLY PRECHECK |
| **EXTEND_OOS** | n &lt; TARGET or unstable |
| **REJECT_CANDIDATE** | primary(C) worse or guards fail materially |
| **INSUFFICIENT_VALID** | STRICT_VALID OOS too sparse |

Exact numeric deltas left to freeze STEP (avoid inventing thresholds here).

---

## 8. Look-ahead protection

| Control | Design |
|---------|--------|
| Discovery cutoff | shadow_id≤51 / completed_at≤ cutoff above |
| Candidate freeze | required **before** OOS scoring |
| Metric freeze | primary + guards locked before OOS-C |
| Sample targets | MIN/TARGET locked before OOS-C |
| Mixing | discovery excluded from OOS aggregates |
| Mid-OOS candidate change | **forbidden** |

**LOOK_AHEAD_PROTECTION_DESIGN = PASS** (as design); **operational PASS only after freeze**.

---

## 9. Missing-data / concentration

| Topic | Rule |
|-------|------|
| Discovery missing-3 | Stay in discovery; never OOS |
| OOS missing windows | Same STRICT_VALID: exclude from primary; flag PARTIAL/INVALID |
| Concentration | Report symbol share of candidate advantage; no hard per-symbol n |

---

## 10. News isolation

MATCHED 2/20 · NO_NEWS 22/20 · **no** Technical OOS coupling.

---

## 11. Required change matrix (future implement — not now)

| Area | Level | Note |
|------|-------|------|
| frontend | **NONE–LOW** | optional audit display only |
| backend | **LOW–MED** | read-only recompute job / admin report API |
| DB migration | **NONE** (Option C) |
| scheduler | **NONE–LOW** | optional batch; not trading scheduler |
| shadow evaluator | **NONE** for production TP; optional offline twin |
| API | **LOW** | report endpoint optional |
| audit/tests | **MED** | cutoff/freeze/metric tests |
| TradingOrder/Outbox/LIVE/ARM | **NONE** — must assert no wiring |

---

## 12. Safety invariant (future)

OOS job may call `ensure_shadow_minute_bars` + `compute_tp_sl` only.  
Must **not** import/create orders, touch LIVE/ARM, or mutate `upbit_scanner_shadow_tp_pct`.

---

## 13. Implementation waves (after candidate definition)

| Wave | Scope |
|------|-------|
| **(pre)** | **TP CANDIDATE DEFINITION REVIEW** — freeze single TP or reject band |
| OOS-A | cutoff + metric + sample freeze docs/tests |
| OOS-B | Option C recompute tooling (read-only) |
| OOS-C | accumulate new COMPLETED |
| OOS-D | OOS review → still no auto-apply |

---

## 14. Final verdict

**`CANDIDATE_DEFINITION_REQUIRED`**

OOS design preferred path is clear (Option C), but **cannot start OOS-A freeze** until a single candidate exists.

---

## 15. Next STEP (exactly one)

**TP CANDIDATE DEFINITION REVIEW**

(Choose/freeze one of 2/3/4% with discovery-only rules, or reject to KEEP_6 — still no apply.)
