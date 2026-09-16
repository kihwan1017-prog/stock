# TECHNICAL SHADOW 52 LONG_ACTIVE TARGET_BLOCKED PRECHECK

**MODE:** READ-ONLY / HYGIENE · **no mutation · no force COMPLETE · no APPLY**  
**Date:** 2026-08-16  
**HEAD:** `3bbf0cd`  
**Verdict:** **`LONG_ACTIVE_TERMINATION_FIX_RECOMMENDED`**  
**JSON:** [TECHNICAL_SHADOW_52_LONG_ACTIVE_PRECHECK.json](TECHNICAL_SHADOW_52_LONG_ACTIVE_PRECHECK.json)

---

## 0. Isolation

| Gate | Value |
|------|-------|
| COVERAGE_REMEDIATION_REOPEN | **NO** |
| TP_ANALYSIS_REOPEN | **NO** |
| CURRENT_TP / SL | **6%** / **3%** unchanged |

---

## 1. Identity

| Field | Value |
|-------|-------|
| shadow_id | **52** |
| symbol | **KRW-PRL** |
| status | **ACTIVE** |
| entry_price | 536 |
| detected_at | `2026-08-13T21:19:40.472Z` |
| created_at | `2026-08-15T01:39:12.339Z` (delayed create vs detect) |
| updated_at | `2026-08-16T03:00:35.449Z` (still refreshed) |
| completed_at | null |
| evaluated_5m / 15m | set |
| evaluated_30m / 60m | **null** |
| path_quality | `technical_path_quality_v2` · unresolved=0 · unavailable=false · resolved_coverage=1.0 |
| path gate | **PASS** (not the blocker) |
| classification | **LONG_ACTIVE_TARGET_BLOCKED** |

Active age (detect→last update) ≈ **53.7h**.

---

## 2. Lifecycle timeline

| Time (UTC) | Event |
|------------|-------|
| 2026-08-13T21:19:40 | `detected_at` (observation window start) |
| 2026-08-13T21:19:00 | SL first_hit on path (bars_checked=16) |
| 2026-08-13T21:24:00 | 5m EXACT_TARGET_CANDLE OK |
| 2026-08-13T21:32:00 | last candle before 15m/30m gap |
| 2026-08-13T21:34:00 | 15m target start · ABSENT_CONFIRMED · prior 21:32 lag **120s** ≤180 → LAST_KNOWN OK |
| 2026-08-13T21:49:00 | 30m target start · ABSENT · nearest prior 21:32 lag **1020s** >180 → MISSING |
| 2026-08-13T22:13:00 | last DB candle in window |
| 2026-08-13T22:19:00 | 60m target start · ABSENT · nearest prior 22:13 lag **360s** >180 → MISSING |
| 2026-08-13T22:19:40 | observation terminal (`detected+60m`) |
| 2026-08-15T01:39:12 | row `created_at` / enter ACTIVE eval |
| 2026-08-15T01:40:40 | evaluated_5m + evaluated_15m stamped |
| … | ACTIVE retries; target_resolve + path_quality refreshed |
| 2026-08-16T03:00:35–42 | latest `updated_at` / source_reconcile tick |

Status transitions observed: **ACTIVE only** (no COMPLETED).

---

## 3. Target block root cause

Contract (`candle_path.select_final_window_close` · `DEFAULT_MAX_PRIOR_LAG_SECONDS=180` · `last_known_price_at_target_v1`):

1. exact target minute missing  
2. Upbit API confirm → `TARGET_CANDLE_ABSENT_CONFIRMED` (`api_rows=5`, exact not in set)  
3. prior completed candle only if lag ≤ **180s**  
4. else `MISSING_CANDLE` + `fallback_reason=TARGET_CANDLE_ABSENT_CONFIRMED` · **no FINAL** · no `evaluated_*m_at`

| Window | target_at | candle_start | exact | nearest prior | prior lag | fallback |
|--------|-----------|--------------|-------|---------------|----------:|----------|
| 5m | …21:24:40 | 21:24:00 | YES | — | 40.5s | EXACT OK |
| 15m | …21:34:40 | 21:34:00 | NO (confirmed) | 21:32:00 | **120s** | LAST_KNOWN OK |
| 30m | …21:49:40 | 21:49:00 | NO (confirmed) | 21:32:00 | **1020s** | **FAIL** |
| 60m | …22:19:40 | 22:19:00 | NO (confirmed) | 22:13:00 | **360s** | **FAIL** |

DB KRW-PRL 1m bars in window: **16** only (sparse / thin trade). Source reconcile: absent_confirmed **45**, `db_missing_source_present=0`.

**TARGET_BLOCK_ROOT_CAUSE:**

1. **SOURCE_ABSENT** (exact minutes confirmed missing at exchange)  
2. **NO_PRIOR_WITHIN_FALLBACK** (30m 1020s · 60m 360s > 180)  
3. **POLICY_CONSTRAINT** (COMPLETED requires all windows OK including 60m; path PASS alone insufficient)

Not: SOURCE_UNAVAILABLE · DATA_DEFECT (persistence gap) · BOUNDARY (maturity already passed).

---

## 4. Retry / cost

| Item | Finding |
|------|---------|
| Scheduler | `upbit_scanner_shadow_evaluator_interval_seconds` default **180** |
| Selection | all `status=ACTIVE` (currently **1** row = 52) |
| updated_at | advances; last ~2026-08-16T03:00Z |
| target_resolve | 3 absent targets retained · API confirm path per missing start |
| source_reconcile | still performed (latest check ~03:00:42) |
| RETRY_BEHAVIOR | **REDUNDANT_RETRY** / **LOW_COST_REPEAT** (not tight hot-loop, but no progress possible) |
| Est. cost | ≤ ~20 ticks/hour · up to ~3 target API + 1 range reconcile/tick if unsynced skips absent |
| RESOURCE_IMPACT | **LOW–MEDIUM** (single row; infinite horizon) |

---

## 5. Terminal policy inventory

| Status enum (constants) | Used by evaluator |
|-------------------------|-------------------|
| ACTIVE | yes |
| COMPLETED | yes (only when `evaluated_60m_at` set) |
| CANCELLED | **defined, unused** in evaluator/service transitions |

| Policy | Result |
|--------|--------|
| LONG_ACTIVE_TERMINATION_POLICY | **NONE** |
| max active age | **NO_MAX_AGE** |
| max evaluation attempts | **NO_MAX_ATTEMPT** |
| max target retry | **NO_MAX_TARGET_RETRY** |
| stale cleanup job | **NO_STALE_CLEANUP** |

Path gate PASS cannot COMPLETE without 30m/60m OK observations.

---

## 6. Mutability / retry value

| Field | Value |
|-------|-------|
| TARGET_ABSENCE_MUTABILITY | **LIKELY_FINAL** (past targets · exchange absent confirmed · DB still sparse · lag permanently >180) |
| FUTURE_RETRY_VALUE | **NONE / LOW** |
| unresolved=0 meaning | missing minutes classified SOURCE_ABSENT, not unresolved DB gap — **does not unlock** window FINAL |

---

## 7. Similar cases

| Query | Count |
|------:|------|
| ACTIVE + 60m ABSENT_CONFIRMED + evaluated_60m null | **1** (shadow 52 only) |
| COMPLETED + 60m LAST_KNOWN_BEFORE_TARGET | **4** (fallback succeeded within 180s) |
| COMPLETED + 60m still MISSING_CANDLE | **0** |
| RECOVERED_AFTER_TARGET_ABSENT (later exact appear → COMPLETE) | **0 observed** in current rows |

---

## 8. Options

| Opt | Idea | correctness | complexity | schema | risk |
|-----|------|-------------|------------|--------|------|
| A | Keep infinite ACTIVE | low (waste) | none | none | ops noise |
| B | Terminal on absent+fallback fail | high | low–med | reuse CANCELLED/detail | need clear semantics ≠ COMPLETED |
| C | max-age / max-attempt → terminal | high | low | none/low | pick thresholds carefully |
| D | manual review only | partial | low | none | does not stop retries |
| **E** | backoff + eventual terminal | high | med | none/low | best ops cost control |

**Recommended:** **OPTION E** (with C-like max bound), terminal via existing **CANCELLED** (or documented non-COMPLETED terminal) + `evaluation_detail` reason — **not** fake COMPLETED / not 0% return invent.

**Minimal fix sketch (design only):**

1. If window mature ∧ `TARGET_CANDLE_ABSENT_CONFIRMED` ∧ prior lag > 180 ∧ age/attempts over bound → stop target API spam (backoff)  
2. After bound → set status **CANCELLED** (or equivalent) with reason `TARGET_FALLBACK_EXCEEDED` · leave math columns null  
3. No synthetic candle · no historical rewrite · TP/Coverage untouched  

**SCHEMA_CHANGE_REQUIRED = NO** (prefer status+detail reuse).

---

## 9. Production impact (if later designed)

| Area | Impact |
|------|--------|
| evaluator | **MEDIUM** |
| domain status | **LOW** (CANCELLED already exists) |
| repository | **LOW** |
| scheduler | **LOW** |
| API | **NONE–LOW** |
| frontend | **LOW** (display CANCELLED) |
| tests | **MEDIUM** |

---

## 10. Safety / News

News: MATCHED 3 · NO_NEWS 30+10 · EXCLUDED 5 · ACCUMULATING · unused.  
TradingOrder **241** · Outbox **52** · LIVE OFF · execution false.  
production/DB mutation **0** · commit/push **NO**.

## 11. Next STEP (exactly one)

**SHADOW LONG_ACTIVE TERMINATION DESIGN**

## STOP

shadow52 unmodified · no APPLY · no TP/Coverage reopen · no LIVE · no commit/push.
