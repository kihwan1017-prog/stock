# TECHNICAL BAR COVERAGE IMPLEMENTATION PRECHECK

**MODE:** READ-ONLY / IMPLEMENTATION BOUNDARY FREEZE  
**Date:** 2026-08-15  
**Prior:** [TECHNICAL_BAR_COVERAGE_REMEDIATION_DESIGN.md](TECHNICAL_BAR_COVERAGE_REMEDIATION_DESIGN.md) · OPTION E  
**JSON:** [TECHNICAL_BAR_COVERAGE_IMPLEMENTATION_PRECHECK.json](TECHNICAL_BAR_COVERAGE_IMPLEMENTATION_PRECHECK.json)

**본 STEP: 구현·backfill·mutation·commit 금지.**

---

## 1. 최종 판정

**COVERAGE_IMPLEMENTATION_READY_WITH_LIMITATIONS**

| 항목 | 값 |
|------|-----|
| Completeness semantics | **RESOLVED** (OBSERVED / SOURCE_ABSENT_CONFIRMED / UNRESOLVED_MISSING) |
| Schema change | **NO** |
| Target price policy | **KEEP** (`last_known_price_at_target_v1`) |
| Path completeness | **NEW_SEPARATE_GATE** (COV-B) |
| First implementable slice | **COV-A** (observability only · no defer/gate yet) |
| Limitations | absence≠metaphysical no-trade; retry/max-age **PROPOSED**; APPLY historical **별도 승인** |
| CURRENT_TP | **6.0%** |
| TP_ANALYSIS_STATUS | **FROZEN_PENDING_COVERAGE_REMEDIATION** |
| OOS | **NOT_STARTED** |
| Next | **COV-A — PATH QUALITY OBSERVABILITY** (구현은 사용자 승인 후) |

---

## 2. Exact file / function matrix

| Area | FILE | FUNCTION/CLASS | CURRENT_ROLE | COV | CHANGE TYPE |
|------|------|----------------|--------------|-----|-------------|
| Client | `broker/upbit/market/client.py` | `UpbitQuotationClient.list_minute_candles` | REST fetch | C (maybe) | optional: expose sync outcome codes only — **prefer no change** |
| Collector | `collectors/upbit/minute_collector.py` | `UpbitMinuteCollector.collect` | range paginate | C | optional reliability/logging; **no synthetic bars** |
| Persist | `markets/service.py` | `CandleMinuteService.save_many` | upsert | C/D | no change for A; D may call existing upsert under approval |
| Persist | `markets/repository.py` | `CandleMinuteRepository.upsert_many` | ON CONFLICT | — | **no change** |
| Loader | `operation/upbit_opportunity_shadow/candle_loader.py` | `list_minute_bars_db` | DB read | A | **read helper reuse** |
| Loader | same | `ensure_shadow_minute_bars` | soft sync | **B/C** | return structured sync status; fail-closed signaling |
| Loader | same | `resolve_missing_target_minutes` | target absent confirm | A/B | **KEEP** for targets; path check **separate** |
| Path | `…/candle_path.py` | `select_final_window_close` / `observe_windows` | target FINAL | — | **KEEP** policy |
| Path | same | `compute_mfe_mae` / `compute_tp_sl` | path metrics | A | **no logic change in A**; consume real bars only |
| **NEW** | `…/path_quality.py` (**proposed**) | `compute_path_quality` / minute-state classify | — | **A** | **pure function** + unit tests |
| Evaluator | `…/evaluator.py` | `_compute_payload` | assemble windows/MFE/TP | **A** | attach `path_quality` into computed/detail (**observe only**) |
| Evaluator | same | `_apply_timeseries` | persist + COMPLETED | **B** | gate COMPLETED on path quality; defer |
| Evaluator | same | `evaluate_pending` / `dry_recompute` | batch / RO recompute | B / D | defer skip finalize; dry includes path_quality |
| Scheduler | `…/evaluator_scheduler.py` | `_run_tick` | ~180s ACTIVE eval | B | **reuse tick** — no new job |
| Entity | `…/entities.py` | `evaluation_detail` JSONB | provenance | A/B | **JSONB keys only** — no migration |
| Service | `…/service.py` | `to_public` | API shape | A/E | optional surface path_quality summary |
| Admin API | `api/v1/admin_upbit_opportunity_scanner.py` | evaluate / dry-recompute / status | ops | A/E | status fields optional |
| Mismatch | `…/mismatch.py` | `verify` / watch | RO compare | D/E | extend diff with path_quality |
| Reconciliation | `…/reconciliation.py` | preview / apply | MANUAL apply | **D** | PREVIEW/COMPARE first; APPLY gated phrase |
| Tests | `tests/test_upbit_shadow_*.py` + **new** `test_upbit_shadow_path_quality.py` | — | — | A–E | cases §21 |
| Frontend | Upbit Technical panels | — | display | E (later) | **out of A–C** |

---

## 3–4. Completeness definition

| Token | Meaning | Gate use |
|-------|---------|----------|
| **A. OBSERVED_BAR_COUNT** | DB(+merged API exact) 1m bars in `[floor(detected), detected+60m]` | diagnostic |
| **B. SOURCE_ABSENCE_CONFIRMED** | range/API reconcile: minute **not returned** by Upbit for that slot | **not** unresolved; **not** synthetic candle |
| **C. UNRESOLVED_MISSING** | clock minute with no observed bar **and** absence **not** confirmed | **production block** |

**Production completeness (proposed):**  
`path_quality_ok ⇔ unresolved_missing_count == 0 ∧ source_unavailable == false ∧ targets_finalizable`

Raw `actual/expected` remains **diagnostic only**.

---

## 5. No-trade state model (implementable)

| State | Implementable? | How |
|-------|----------------|-----|
| **DB_PRESENT** | YES | bar in DB/merged set |
| **DB_MISSING_SOURCE_PRESENT** | YES | absent DB; range fetch returns that `candle_at` → persist/merge |
| **SOURCE_ABSENT_CONFIRMED** | YES (operational) | after successful range fetch covering slot, minute not in returned set |
| **SOURCE_UNAVAILABLE** | YES | rate-limit/exception/empty-untrusted fetch |
| **SOURCE_NOT_CHECKED** | YES | no successful reconcile yet → counts as unresolved for gate |

**Limitation:** Upbit omission ≈ no-trade **operationally**, not legal proof of zero prints. Label as `SOURCE_ABSENT_CONFIRMED`, not `NO_TRADE_PROVEN`.  
**Synthetic OHLC: forbidden.**

---

## 6. Target vs path policy

| Policy | Verdict |
|--------|---------|
| TARGET_PRICE_POLICY | **KEEP** — `last_known_price_at_target_v1`, max prior lag 180s |
| PATH_COMPLETENESS_POLICY | **NEW_SEPARATE_GATE** |

Compatible: target FINAL may use last_known when target minute SOURCE_ABSENT_CONFIRMED; path gate still requires unresolved_missing==0 across **all** expected minutes (absent-confirmed minutes simply contribute zero bars to MFE/TP — they do not invent OHLC).

---

## 7–8. Realtime state · evaluation_detail

**Status enum:** keep `ACTIVE` / `COMPLETED` / `CANCELLED` only.  
**SCHEMA_CHANGE_REQUIRED = NO**

Flow (COV-B design; not implemented now):

```text
ACTIVE → soft sync → path_quality inspect
  OK → existing window finalization → COMPLETED
  UNRESOLVED / SOURCE_UNAVAILABLE → stay ACTIVE; detail.path_quality.defer_*
  bounded exhaust → ACTIVE + terminal_incomplete (or operator CANCELLED) — NEVER silent COMPLETED
```

### `evaluation_detail.path_quality` (JSONB · no migration)

Compatible with existing keys (`windows`, `window_finalization`, `mfe_mae`, `tp_sl`, `mismatch_watch`, `source`, …):

```json
"path_quality": {
  "path_quality_version": "v1",
  "expected_minutes": 61,
  "observed_candles": 0,
  "source_absent_confirmed": 0,
  "unresolved_missing": 0,
  "coverage_ratio_raw": 0.0,
  "coverage_ratio_resolved": 0.0,
  "max_gap_minutes": 0,
  "first_candle_at": null,
  "last_candle_at": null,
  "sync_attempts": 0,
  "sync_last_result": null,
  "defer_reason": null,
  "source_unavailable": false
}
```

COV-A: **write/compute for observability** (even on COMPLETED dry paths) without blocking finalize.  
COV-B: **enforce** defer using same blob.

---

## 9. Coverage metric v2

| Metric | Formula | Role |
|--------|---------|------|
| raw coverage | OBSERVED / expected | diagnostic (OVERSTATES_MISSING) |
| resolved_minutes | OBSERVED + SOURCE_ABSENT_CONFIRMED | logical minutes “accounted for” |
| resolved_coverage | resolved_minutes / expected | quality progress |
| unresolved_missing_count | expected − resolved_minutes | **gate** |

Absent-confirmed minutes: **do not** add synthetic candles to MFE/TP/SL.

---

## 10. Source absence check cost

**Method (required):** one (or few) **range** fetches via existing `UpbitMinuteCollector.collect(start, end)` / soft-sync — **not** N+1 per missing minute.

| Approach | Est. requests / shadow / tick (60m) |
|----------|--------------------------------------|
| Reuse soft-sync range collect | **~1** (≤200 rows) |
| Compare expected set vs returned | 0 extra |
| Narrow retry only if SOURCE_UNAVAILABLE | **+0–1** PROPOSED |
| Per-minute GET | **FORBIDDEN** (~tens) |

---

## 11. Soft-sync behavior matrix (COV-C design)

| Sync outcome | Evaluator action |
|--------------|------------------|
| success (full resolve possible) | proceed to path_quality → EVALUATE or DEFER |
| partial (some still unresolved after success fetch) | **DEFER** if unresolved&gt;0 |
| source unavailable | **DEFER** / fail-closed — **not** complete |
| rate-limited | **DEFER** |
| exception | **DEFER** (log) |

**Never:** SOURCE_UNAVAILABLE ⇒ treat as complete.  
Current “log and continue to COMPLETED” is the defect COV-B/C remove.

---

## 12. Retry / defer (PROPOSED — not ratified)

| Item | Design |
|------|--------|
| Counter storage | `evaluation_detail.path_quality.sync_attempts` (+ optional `defer_count`) |
| Scheduler | **existing** evaluator tick only (~180s) |
| max attempts | **PROPOSED** (e.g. N ticks) — freeze in COV-B pre-apply note |
| max age from detected+60m | **PROPOSED** wall-clock bound |
| Infinite ACTIVE risk | mitigate with terminal_incomplete marker + ops alert |
| Outage | remain ACTIVE; SOURCE_UNAVAILABLE; no COMPLETED |

---

## 13. COMPLETED finalization gate (COV-B)

```text
COMPLETED ⇔
  status was ACTIVE
  AND all target windows finalizable under KEEP policy (now ≥ target_candle_end + OK/last_known)
  AND path_quality_gate:
        unresolved_missing == 0
        AND source_unavailable == false
```

| Condition | COMPLETED? |
|-----------|------------|
| SOURCE_UNAVAILABLE | **NO** |
| UNRESOLVED_MISSING &gt; 0 | **NO** |
| SOURCE_ABSENT_CONFIRMED only (unresolved=0) | **YES** (path uses observed bars only) |

Code insert point: `evaluator._apply_timeseries` **before** setting `evaluated_60m_at` / status COMPLETED (after windows OK computed).

---

## 14. MFE / MAE / TP / SL contract

| Rule | Value |
|------|-------|
| Bars | actual OHLC only |
| SOURCE_ABSENT_CONFIRMED | **no** bar added |
| Synthetic / prior-fill gap candles | **FORBIDDEN** |
| SAME_CANDLE_SL_CONSERVATIVE | **KEEP** |
| compute_tp_sl / compute_mfe_mae | unchanged semantics; gated by who may COMPLETED |

---

## 15–17. Historical

**Mode:** BACKFILL_AND_COMPARE  

1. Preserve original stored columns + detail  
2. Optional backfill (approved STEP) via existing sync/upsert  
3. `dry_recompute` + path_quality on current DB  
4. Diff original vs recompute (+ coverage provenance)  
5. WRITE/APPLY only via `ReconciliationService` fingerprint + approval phrase  

**Selection rule (proposed):**  
Start from raw cov&lt;0.8 (n=19) **as review set** → run absence reconcile → remediate/compare only rows with **unresolved_missing &gt; 0** or SOURCE_UNAVAILABLE history; pure SOURCE_ABSENT_CONFIRMED may be “explained thin path,” not forced rewrite.

**Reconciliation:** PREVIEW / COMPARE now; APPLY = existing safety pattern, **separate approval** — not in COV-A/B/C.

---

## 18. Observability

| Field | API today | Plan |
|-------|-----------|------|
| path_quality blob | no | COV-A in `evaluation_detail`; optional `to_public` summary |
| Admin Technical UI | limited | COV-E display |
| Scheduler status | tick metrics | optional defer counters later |

---

## 19–20. Waves & COV-A boundary

| Wave | Scope | Files (primary) | DB schema | API | FE | Tests | Risk |
|------|-------|-----------------|-----------|-----|----|-------|------|
| **COV-A** | Pure path_quality compute + detail provenance; **no defer** | **new** `path_quality.py`; `evaluator._compute_payload` attach; tests | NO | optional | NO | YES | **LOW** |
| **COV-B** | Completeness gate + ACTIVE defer | `evaluator._apply_timeseries` | NO | status fields | NO | YES | MED |
| **COV-C** | Soft-sync structured outcomes / fail-closed | `candle_loader.ensure_shadow_minute_bars` | NO | NO | NO | YES | MED |
| **COV-D** | Historical PREVIEW/COMPARE | `reconciliation` / mismatch / scripts | NO* | preview | NO | YES | MED (*backfill writes need approval) |
| **COV-E** | Validation + unfreeze criteria docs | audit + optional UI | NO | status | optional | YES | LOW |

### COV-A minimal boundary (next implementable)

1. `compute_path_quality(...)` pure  
2. Wire into `_compute_payload` → `evaluation_detail.path_quality` when persisting **or** dry output  
3. Unit tests for states / metrics  
4. **Explicitly out of scope:** COMPLETED blocking, sync rewrite, FE, TP, backfill  

---

## 21. Test plan (COV-A–C)

1. full candles → unresolved=0  
2. DB missing + API present → merge → observed↑  
3. DB missing + API absent → SOURCE_ABSENT_CONFIRMED  
4. source unavailable → flag; unresolved or unavailable  
5. distributed gaps  
6. consecutive gaps / max_gap  
7. target absence + prior fallback (**target OK**, path separate)  
8. path gap without target gap  
9. same-candle TP/SL unchanged  
10. soft sync failure → DEFER (B/C)  
11. defer then next tick complete (B)  
12. COMPLETED only after quality gate (B)  
13. historical stored immutable without APPLY (D)

---

## 22. Acceptance contract (deterministic)

Remediation “good enough” for a row / new cohort member:

- `unresolved_missing == 0`  
- `source_unavailable == false`  
- target finalization complete under KEEP policy  
- `path_quality` provenance recorded (`path_quality_version`)  
- raw coverage threshold **not** required for pass  

---

## 23–25. Freeze / News / Safety

| Item | Value |
|------|-------|
| CURRENT_TP | **6.0%** |
| TP_ANALYSIS_STATUS | **FROZEN_PENDING_COVERAGE_REMEDIATION** |
| OOS | **NOT_STARTED** |
| News | MATCHED **2/20** · NO_NEWS **22/20** · ACCUMULATING |
| production/DB/migration/backfill/orders/LIVE/commit | **0** |

---

## 26–28. Limitations · Next

**Limitations:** operational absence ≠ proven no-trade; PROPOSED retry bounds; Discovery 19 need reconcile before historical rewrite decisions; COV-A alone does not fix COMPLETED race.

**Next STEP (exactly one):**  
**COV-A — PATH QUALITY OBSERVABILITY**  
(구현은 사용자 승인 후에만.)

---

## STOP

source 수정 · DB · backfill · gate 적용 · TP · LIVE · commit — **전부 미실행**.
