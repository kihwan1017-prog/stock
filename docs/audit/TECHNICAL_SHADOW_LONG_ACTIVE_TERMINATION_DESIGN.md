# TECHNICAL SHADOW LONG_ACTIVE TERMINATION DESIGN

**MODE:** READ-ONLY DESIGN ONLY · **no implementation · no shadow52 mutation · no migration**  
**Date:** 2026-08-16  
**HEAD:** `3bbf0cd`  
**Basis:** [TECHNICAL_SHADOW_52_LONG_ACTIVE_PRECHECK.md](TECHNICAL_SHADOW_52_LONG_ACTIVE_PRECHECK.md)  
**Verdict:** **`TERMINATION_DESIGN_READY`**  
**Recommended:** **OPTION E** (grace + permanent-absence terminal + SOURCE_UNAVAILABLE max-age safeguard)  
**JSON:** [TECHNICAL_SHADOW_LONG_ACTIVE_TERMINATION_DESIGN.json](TECHNICAL_SHADOW_LONG_ACTIVE_TERMINATION_DESIGN.json)

---

## 0. Isolation

| Contract | Value |
|----------|-------|
| COVERAGE_REMEDIATION_REOPEN | **NO** |
| TP_ANALYSIS_REOPEN | **NO** |
| CURRENT_TP / SL | **6%** / **3%** |
| OOS | **NOT_STARTED** |

This is lifecycle hygiene — **not** TP optimization.

---

## 1. Existing lifecycle contract

| Status | Create | Transition | Meaning (as coded) |
|--------|--------|------------|--------------------|
| **ACTIVE** | `service` on scanner create | start state | under evaluation |
| **COMPLETED** | — | evaluator when `evaluated_60m_at` set | all required finals done; cohort/stats/TP eligible |
| **CANCELLED** | constant only | **never written** | reserved string |

**CANCELLED_USAGE = DEFINED_BUT_UNUSED**

Evidence:

- `constants.py` defines three statuses  
- `evaluator.py` selects `status==ACTIVE` only; writes `COMPLETED` only  
- `service._has_active_shadow` / cooldown use ACTIVE (+ COMPLETED for cooldown)  
- `cohort_milestone._is_valid_cohort_row` / `stats.compute_shadow_stats` require **COMPLETED**  
- Admin status API lists only `active` + `completed` arrays  
- DB: `status String(20)` **no CHECK** — CANCELLED fits without migration  

---

## 2. CANCELLED semantic safety

| Question | Answer |
|----------|--------|
| User-cancel meaning today? | **No** — never used in shadow runtime |
| System “cannot finalize” reuse? | **Yes, with explicit reason object** |
| Stats/cohort pollution? | **No** if filters stay COMPLETED-only |
| Cooldown / active-symbol lock? | CANCELLED **releases** symbol (`_has_active_shadow` ignores it) — desired |
| FE confusion? | Low if reason shown; today CANCELLED would be **invisible** on status panel (not in active/completed lists) |

**CANCELLED_REUSE = SAFE_WITH_REASON**

New status (**OPTION F**) is last resort — unnecessary given unused CANCELLED + String(20).

---

## 3. Exact terminal predicate (permanent absence)

```text
TERMINATE_PERMANENT_ABSENCE iff ALL of:

1. status == ACTIVE
2. now >= target_candle_end(60m)          # target due / mature
3. windows["60"].status == MISSING_CANDLE
4. windows["60"].fallback_reason == TARGET_CANDLE_ABSENT_CONFIRMED
   OR target_resolve[candle_start].status == TARGET_CANDLE_ABSENT_CONFIRMED
5. source_reconcile / path_quality:
     source_check_performed == true
     source_unavailable == false
     unresolved_missing == 0
6. nearest_prior_lag_seconds(60m) is None OR > max_prior_lag_seconds (180)
7. grace elapsed since first_permanent_block_at (see §5)
```

**Do not** terminate on raw coverage &lt;0.8 alone.  
**Do not** terminate on `SOURCE_UNAVAILABLE` via this predicate.

---

## 4. Required windows

| Window | Role |
|--------|------|
| 5 / 15 | early observation; not completion gate |
| 30 | intermediate; can stay null without blocking COMPLETED if 60 OK |
| **60** | **completion gate** (`evaluated_60m_at` → COMPLETED) |

**Recommendation: A — 60m permanent unresolved ⇒ terminal**

Rationale: matches evaluator COMPLETED contract; shadow 52 is blocked on 60m (and 30m). Terminating on 30m alone would be premature if 60m later finalizes via LAST_KNOWN.

---

## 5. Grace

**GRACE_PERIOD_REQUIRED = YES**

Not because minutes are expected to appear days later, but to absorb:

- same-tick race between absent confirm and bar merge  
- 1–2 subsequent 180s ticks for reconfirm  

**RECOMMENDED_GRACE = 3 × evaluator_interval**  
(default interval 180s → **540s**)

Grounding: operational tick count, not an arbitrary market hypothesis.  
Shadow 52 already far exceeds any grace.

---

## 6. Retry / backoff

| Option | Verdict |
|--------|---------|
| A fixed 180s forever | status quo — reject |
| B exponential backoff framework | overkill / likely schema |
| C `next_retry_at` column | schema — avoid |
| **D grace with existing 180s ticks then terminal** | **preferred** |

No new scheduler framework. During grace: keep current ACTIVE evaluation. After grace + predicate: terminal once.

---

## 7. Max age / attempts (SOURCE_UNAVAILABLE safeguard)

Permanent-absence predicate does **not** cover long `SOURCE_UNAVAILABLE`.

| Control | Required? | Proposal |
|---------|-----------|----------|
| MAX_ACTIVE_AGE (unavailable path) | **YES** | `now > detected_at + 60m + grace` **and** still SOURCE_UNAVAILABLE on required 60m → terminal reason `SOURCE_UNAVAILABLE_MAX_AGE` |
| MAX_ATTEMPTS counter column | **NO** | derive from grace/tick wall-clock |
| MAX_SOURCE_UNAVAILABLE_RETRY column | **NO** | same |

Do **not** COMPLETE or invent returns on max-age.

---

## 8. Terminal status + reasons + detail

**terminal status = CANCELLED** (reuse)

**reason set (minimal):**

| reason | When |
|--------|------|
| `TARGET_PERMANENTLY_UNRESOLVABLE` | §3 predicate (preferred umbrella) |
| `SOURCE_UNAVAILABLE_MAX_AGE` | unavailable safeguard |

(Avoid proliferating TARGET_SOURCE_ABSENT / TARGET_FALLBACK_EXCEEDED as separate statuses — fold evidence into detail.)

**evaluation_detail.termination** (additive JSON; first-write wins):

```json
{
  "version": "shadow_termination_v1",
  "reason": "TARGET_PERMANENTLY_UNRESOLVABLE",
  "terminated_at": "<iso>",
  "target_window_minutes": 60,
  "target_at": "<iso>",
  "target_candle_start": "<iso>",
  "source_absent_confirmed": true,
  "nearest_prior_at": "<iso|null>",
  "prior_lag_seconds": 360,
  "fallback_limit_seconds": 180,
  "grace_seconds": 540,
  "first_blocked_at": "<iso>",
  "last_checked_at": "<iso>",
  "path_quality_version": "technical_path_quality_v2",
  "unresolved_missing": 0,
  "source_unavailable": false
}
```

On terminate:

- set `status=CANCELLED`  
- set `updated_at`  
- **do not** set `evaluated_60m_at` / `completed_at`  
- **do not** fill return/MFE/MAE/tp/sl for unresolved windows  

---

## 9. Statistics isolation

| Consumer | Filter today | After CANCELLED |
|----------|--------------|-----------------|
| cohort / STRICT | COMPLETED + windows | **unchanged — excluded** |
| `cohort_n` / REVIEW_READY | completed_count | **unchanged** |
| TP discovery / reanalysis scripts | COMPLETED + cutoff | **unchanged** |
| `active_count` | ACTIVE | decreases when terminated |
| cooldown | ACTIVE/COMPLETED | CANCELLED **not** in list → new shadow allowed |

**TERMINATED ≠ COMPLETED** — hard rule.

Optional stats keys: `cancelled_count`, `terminated_target_unresolvable_count` (observability).

---

## 10. Shadow 52 handling (design only)

| Option | Note |
|--------|------|
| A keep forever | rejects hygiene goal |
| B migration backfill | unnecessary |
| C one-time remediation script | optional ops later |
| **D runtime next ticks apply new policy** | **recommended** |

Once implemented, 52 already past grace → terminate on subsequent ACTIVE eval without special-case ID.

---

## 11. Future flow (state)

```text
ACTIVE
  ├─ target not mature → ACTIVE
  ├─ exact / LAST_KNOWN OK → finalize windows
  │     └─ evaluated_60m_at set → COMPLETED
  ├─ SOURCE_UNAVAILABLE → ACTIVE retry
  │     └─ past observation_end + grace → CANCELLED
  │           reason=SOURCE_UNAVAILABLE_MAX_AGE
  └─ ABSENT confirmed + lag>180
        └─ within grace → ACTIVE recheck (180s)
        └─ grace elapsed → CANCELLED
              reason=TARGET_PERMANENTLY_UNRESOLVABLE
```

COMPLETED and CANCELLED paths never merge.

---

## 12. SOURCE_UNAVAILABLE

Keep **recoverable** under §3.  
Only §7 max-age hygiene may terminal with distinct reason.  
Never treat as SOURCE_ABSENT.

---

## 13. Idempotency

1. If `status != ACTIVE` → skip  
2. If `evaluation_detail.termination` already present → skip overwrite of `terminated_at` / reason  
3. Single write: status + termination blob + updated_at  
4. No metric fabrication on repeat ticks  

---

## 14. Concurrency

Reuse existing session transaction in `evaluate_active_shadows`:

- load ACTIVE only  
- after CANCELLED, row disappears from next select  
- optional optimistic: only update when `status=='ACTIVE'` in same unit of work  

No new lock framework.

---

## 15. API / FE

| Layer | Impact |
|-------|--------|
| API `to_public` | already returns `status` string — CANCELLED works |
| `/status` shadows lists | **optional**: add `cancelled` list or include in stats |
| FE panel | **optional LOW** — today CANCELLED invisible; MVP OK if stats show count |
| FE required for correctness? | **NO** |

Minimum later UX: Tag CANCELLED + termination.reason from detail.

---

## 16. Observability

| Metric | Priority |
|--------|----------|
| active_count | existing |
| completed_count | existing |
| cancelled_count | **optional** |
| terminated_by_reason | optional |
| target_blocked_active | optional diagnostic |

---

## 17. Implementation file matrix

| File | Change | Risk | Test |
|------|--------|------|------|
| `evaluator.py` | predicate + terminate write | MED | yes |
| `constants.py` | reason string consts (optional) | LOW | — |
| `path_quality.py` | **NONE** (reuse evidence) | — | — |
| `stats.py` | optional cancelled_count | LOW | yes |
| `service.py` | optional list CANCELLED; cooldown already OK | LOW | yes |
| API router | optional status payload | LOW | — |
| FE panel | optional | LOW | — |
| entities / alembic | **NONE** | — | — |
| tests `test_upbit_shadow_*` | new cases | MED | yes |

---

## 18. Test plan (expected)

| ID | Scenario | Expect |
|----|----------|--------|
| A | source present | COMPLETED |
| B | absent + prior ≤180 | LAST_KNOWN → COMPLETED |
| C | absent + prior >180 + grace | CANCELLED + termination reason |
| D | SOURCE_UNAVAILABLE | stay ACTIVE |
| E | unavailable then recover | COMPLETED |
| F | terminal next tick | no reprocess / no detail clobber |
| G | CANCELLED | excluded from STRICT/cohort/TP |
| H | shadow-52-equivalent fixture | CANCELLED after grace |
| I | any path | TradingOrder/Outbox Δ0 |

---

## 19. Options scorecard

| Opt | correctness | complexity | schema | ops | risk | Verdict |
|-----|-------------|------------|--------|-----|------|---------|
| A keep | poor | 0 | 0 | bad | low | reject |
| B immediate CANCELLED | ok | low | 0 | ok | race | weak |
| C grace + CANCELLED | good | low | 0 | good | low | strong subset |
| D max-age only | partial | low | 0 | ok | may delay clear cases | incomplete |
| **E grace+absence terminal + unavailable max-age** | **best** | low–med | **0** | best | low | **SELECT** |
| F new status | good | med | likely | ok | FE/API churn | unnecessary |

---

## 20. Recommendation

**OPTION E**

1. correctness / no fake COMPLETED  
2. stop infinite ACTIVE  
3. no schema/migration  
4. minimal evaluator change  
5. stats isolation via COMPLETED-only filters  
6. CANCELLED + `evaluation_detail.termination`  

**SCHEMA_CHANGE_REQUIRED = NO**  
**MIGRATION_REQUIRED = NO**

---

## 21. Safety snapshot (READ)

TradingOrder **241** · Outbox **52** · LIVE OFF · execution false.  
News: MATCHED 3 · NO_NEWS 30+10 · EXCLUDED 5 · ACCUMULATING.  
production/DB mutation **0** · commit/push **NO**.

## 22. Next STEP (exactly one)

**SHADOW LONG_ACTIVE TERMINATION IMPLEMENTATION PRECHECK**

## STOP

No code · no shadow52 change · no APPLY · no TP/Coverage reopen · no LIVE · no commit/push.
