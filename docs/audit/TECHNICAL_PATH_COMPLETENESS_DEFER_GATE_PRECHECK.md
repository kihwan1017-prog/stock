# TECHNICAL PATH COMPLETENESS DEFER GATE PRECHECK (COV-B0)

**MODE:** READ-ONLY / NO PRODUCTION MUTATION  
**Date:** 2026-08-15  
**JSON:** [TECHNICAL_PATH_COMPLETENESS_DEFER_GATE_PRECHECK.json](TECHNICAL_PATH_COMPLETENESS_DEFER_GATE_PRECHECK.json)  
**Dry:** [TECHNICAL_PATH_COMPLETENESS_DEFER_GATE_PRECHECK_DRY.json](TECHNICAL_PATH_COMPLETENESS_DEFER_GATE_PRECHECK_DRY.json)

---

## 1. 최종 판정

**PATH_COMPLETENESS_GATE_BLOCKED_BY_SOURCE_RECONCILIATION**

| 항목 | 값 |
|------|-----|
| PATH_QUALITY_REUSABLE_FOR_GATE | **YES** (pure + detail contract) |
| COV_B_CAN_GATE_WITH_CURRENT_COV_A_EVIDENCE | **NO** (false defer ~72%) |
| COV_B_BLOCKED_BY_COV_C | **true** |
| Recommended order | **COV-C → COV-B** |
| Recommended option | **OPTION C** (source reconciliation first) |
| Schema change | **NO** |
| CURRENT_TP | **6.0%** · TP **FROZEN_PENDING_COVERAGE_REMEDIATION** · OOS **NOT_STARTED** |
| Next | **COV-C — SOURCE ABSENCE / SOFT-SYNC RECONCILIATION** |

---

## 2. COV-A reusable?

**PATH_QUALITY_REUSABLE_FOR_GATE = YES**

| Piece | Location | Gate reuse |
|-------|----------|------------|
| Pure compute | `path_quality.compute_path_quality` | YES |
| Version | `technical_path_quality_v1` | YES |
| Detail write | `evaluator._apply_timeseries` → `evaluation_detail.path_quality` | YES |
| Payload attach | `evaluator._compute_payload` | YES |
| Evidence limit | absence only from target `absent_by_target` / stored `target_resolve` | **PARTIAL evidence** → blocks safe gate |

---

## 3. Current finalization flow

```text
evaluator_scheduler._run_tick (~180s)
  → UpbitOpportunityShadowEvaluator.evaluate_pending
    → select ACTIVE rows
    → _apply_timeseries(persist=True)
         → _compute_payload
              → ensure_shadow_minute_bars (soft sync)
              → resolve_missing_target_minutes (target only)
              → observe_windows / compute_mfe_mae / compute_tp_sl
              → compute_path_quality (COV-A, ungated)
         → stamp window columns when status==OK
         → write evaluation_detail (+ path_quality)
         → if evaluated_60m_at and ACTIVE → status=COMPLETED
    → session.commit()
```

| Step | FILE | FUNCTION | INPUT | OUTPUT | MUTATION | FAILURE |
|------|------|----------|-------|--------|----------|---------|
| Tick | `evaluator_scheduler.py` | `_run_tick` | schedule | eval+mismatch | none (session) | log, return ok=False |
| Entry | `evaluator.py` | `evaluate_pending` | ACTIVE rows | counts | commit | empty → no-op |
| Soft sync | `candle_loader.py` | `ensure_shadow_minute_bars` | symbol, range | bars, sync | may upsert candles | log, continue |
| Target resolve | `candle_loader.py` | `resolve_missing_target_minutes` | missing targets | absent/unavailable maps | may upsert exact | mark unavailable |
| Payload | `evaluator.py` | `_compute_payload` | row | windows/MFE/TP/path_quality | none | ok flags |
| Apply | `evaluator.py` | `_apply_timeseries` | computed | changed/just_completed | columns + detail + status | skip incomplete windows |
| COMPLETED | `evaluator.py` | `_apply_timeseries` | evaluated_60m_at | COMPLETED | **status, completed_at** | — |

---

## 4. COMPLETED mutation point

| Field | Value |
|-------|-------|
| COMPLETED_MUTATION_FILE | `operation/upbit_opportunity_shadow/evaluator.py` |
| COMPLETED_MUTATION_FUNCTION | `UpbitOpportunityShadowEvaluator._apply_timeseries` |
| COMPLETED_MUTATION_CONDITION | `persist` and `evaluated_60m_at is not None` and `status == ACTIVE` → `status=COMPLETED`, `completed_at=now` (~L291–298) |

**Safe gate insert:** immediately **before** that `if` block, after `evaluation_detail` / path_quality write — if path gate fails: keep ACTIVE, do **not** set COMPLETED (still allow detail provenance update).

---

## 5. Target finalization gate

| Item | Value |
|------|-------|
| Present | **YES** — `select_final_window_close`: `now < target_candle_end` → `NOT_MATURED` |
| Correct | **YES** (race fix kept) |
| KEEP | **YES** — COV-B must not alter last_known@target ≤180s |

Path gate is **orthogonal** to target fallback.

---

## 6–7. Path gate candidate & evidence

**PATH_GATE_CANDIDATE:**  
`unresolved_missing == 0 AND source_unavailable == false`

| Attribute | Verdict |
|-----------|---------|
| DETERMINISTIC | YES given path_quality inputs |
| FALSE_DEFER_RISK | **HIGH** under COV-A evidence |
| COV_B_CAN_GATE_WITH_CURRENT_COV_A_EVIDENCE | **NO** |

Reason: intermediate minutes without range absence confirmation remain UNRESOLVED → no-trade minutes look like data gaps → permanent ACTIVE risk.

---

## 8–9. Dry sample (Discovery STRICT, cutoff, N=47, no DB write)

| Metric | Value |
|--------|------:|
| unresolved_missing == 0 | **13** |
| unresolved_missing > 0 | **34** |
| source_unavailable | **0** |
| WOULD_PASS | **13** |
| WOULD_DEFER | **34** |
| WOULD_DEFER_RATE | **72.3%** |

| Dist | min | p25 | med | p75 | max | mean |
|------|----:|----:|----:|----:|----:|-----:|
| unresolved | 0 | 0 | 6 | 19 | 35 | 10.2 |
| raw coverage | 0.39 | 0.67 | 0.90 | 1.0 | 1.0 | 0.82 |
| resolved coverage | 0.43 | 0.69 | 0.90 | 1.0 | 1.0 | 0.83 |
| max_gap | 0 | 0 | 2 | 3 | 9 | 2.1 |

Defer classification (no API proof): mostly **UNKNOWN** (could be no-trade **or** real gap). **KNOWN_REAL_DATA_GAP** not claimable without COV-C.

---

## 10. Source absence utility (COV-A)

| Evidence | Dry result |
|----------|------------|
| Rows with any `source_absent_confirmed` (from stored `target_resolve`) | **14 / 47** |
| Total confirmed-absent minutes | **22** (target windows only) |
| Intermediate-path confirmation | **≈0** (COV-A did not range-confirm) |
| source_unavailable in dry | **0** (field under-powered today) |

→ **COV-C must precede COV-B.**

---

## 11–13. Defer state / write order / reasons

| Item | Verdict |
|------|---------|
| ACTIVE_DETAIL_WRITE_SUPPORTED | **YES** — `_apply_timeseries` already writes detail + path_quality while ACTIVE |
| SCHEMA_CHANGE_REQUIRED | **NO** |
| REPOSITORY_CHANGE_REQUIRED | **NO** |
| Recommended write strategy | **OPTION A** — ACTIVE detail update (path_quality + defer_reason), skip COMPLETED |
| Minimal defer_reason | `PATH_UNRESOLVED_MISSING` · `PATH_SOURCE_UNAVAILABLE` (JSON string in path_quality) |

---

## 14–16. Retry / infinite / unavailable

| Item | Verdict |
|------|---------|
| AUTOMATIC_RETRY_SUPPORTED | **YES** — `evaluate_pending` selects all ACTIVE each tick (~180s); no age filter |
| Attempt limit / expiry | **NONE** |
| INFINITE_DEFER_RISK | **YES** without COV-C + future policy bound (**PROPOSED later**, not this STEP) |
| source_unavailable usefulness now | **LOW** until soft-sync surfaces failures into path_quality reliably (COV-C) |

---

## 17–18. Target fallback · math delta

- Case A (target absent + prior ≤180s): **KEEP** — not blocked by path gate alone if unresolved==0 after COV-C confirms other minutes.
- Case B (mid-path missing): path gate defer — intended.
- Future COV-B math delta target: TP/SL/MFE/MAE/returns **0** (gate only).

---

## 19–22. Options & order

| Opt | Summary | Correctness | False defer | Impl risk | Schema | Ops |
|-----|---------|-------------|-------------|-----------|--------|-----|
| A | Gate on COV-A now | Low | **Very high (72%)** | Low | NO | Bad |
| B | Raw coverage threshold | Low | High/biased | Low | NO | Bad |
| **C** | **COV-C first** | High | Controlled | Med | NO | Best |
| D | COV-B+C combined | High | Controlled | High | NO | Heavy |
| E | Limited COV-B observe-only reasons | Med | N/A | Low | NO | Weak |

**Recommended: OPTION C — COV-C then COV-B.**  
Do **not** preserve roadmap “B before C” against evidence.

---

## 23–27. Test plan / freeze / safety

Future gate tests: complete→COMPLETED; unresolved→ACTIVE; unavailable→ACTIVE; absence confirmed→allow; target fallback intact; gap resolve next tick; provenance; math unchanged; same-candle SL; retry; no order mutation.

Historical: rewrite/backfill/recompute **0** this STEP.  
TP freeze maintained. News baseline 2/20 · 22/20.  
All mutations **0**.

---

## 28–31. Next

**next STEP exactly one:**  
**COV-C — SOURCE ABSENCE / SOFT-SYNC RECONCILIATION**

(After COV-C raises `source_absent_confirmed` / fail-closed sync evidence → revisit **COV-B DEFER GATE** implementation.)

---

## Limitations

- Dry used DB bars + stored target_resolve only (no live API).  
- WOULD_DEFER mixes true gaps and possible no-trade.  
- No max-defer policy designed/ratified.

## STOP

COV-B/C 구현 · production · DB · TP · commit/push — **미실행**.
