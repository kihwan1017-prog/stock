# TECHNICAL COV-B — REALTIME PATH COMPLETENESS DEFER GATE

**MODE:** IMPLEMENTATION · **REALTIME ACTIVE ONLY** · **NO HISTORICAL REWRITE** · **NO TP/LIVE**  
**Date:** 2026-08-15  
**Verdict:** **PATH_COMPLETENESS_DEFER_GATE_READY_WITH_LIMITATIONS**  
**JSON:** [TECHNICAL_PATH_COMPLETENESS_DEFER_GATE.json](TECHNICAL_PATH_COMPLETENESS_DEFER_GATE.json)  
**Dry:** [TECHNICAL_PATH_COMPLETENESS_DEFER_GATE_DRY.json](TECHNICAL_PATH_COMPLETENESS_DEFER_GATE_DRY.json)

---

## 1. 최종 판정

| 항목 | 값 |
|------|-----|
| Verdict | **PATH_COMPLETENESS_DEFER_GATE_READY_WITH_LIMITATIONS** |
| GATE_SCOPE | **REALTIME_ACTIVE_ONLY** |
| HISTORICAL_COMPLETED_MUTATION | **0** |
| PATH_GATE_BEFORE_COMPLETION_WRITE | **true** |
| path_quality | `technical_path_quality_v2` (semantics unchanged) |
| COV_B_ADDITIONAL_NETWORK_CALLS | **0** |
| CURRENT_TP | **6.0%** · TP **FROZEN_PENDING_COVERAGE_REMEDIATION** |
| OOS | **NOT_STARTED** |
| commit / push | **0** |
| Next | **COV-A/C/B SELECTIVE COMMIT PRECHECK** (not COV-D) |

---

## 2. Gate

**Location:** `evaluator._apply_timeseries` — after `_compute_payload` / `path_quality`, **before** window column stamps / `evaluated_*_at` / COMPLETED.

**Predicate (COV-C contract):**

```text
PATH_COMPLETE =
  unresolved_missing == 0
  AND source_unavailable == false
```

No new coverage threshold. `raw_coverage` / `resolved_coverage` = diagnostic only.

---

## 3. Behavior

| Path | Behavior |
|------|----------|
| PASS | Existing `_apply_timeseries` finalization → COMPLETED (math unchanged) |
| DEFER | status **ACTIVE** · `evaluated_60m_at` **unset** · no final MFE/TP/SL columns · write `evaluation_detail.path_quality` + `path_defer` only |

DEFER ≠ FAILED / CANCELLED / COMPLETED.

**defer reasons:** `PATH_UNRESOLVED_MISSING` · `SOURCE_UNAVAILABLE` (복합 허용)

**Retry:** `evaluate_pending` selects `status == ACTIVE` → deferred rows remain on next ~180s tick. No new scheduler. No MAX_RETRY policy (observability: `defer_count` / `first_deferred_at` / `last_deferred_at` / `defer_age_seconds`).

**SOURCE_ABSENT_CONFIRMED:** excluded from `unresolved_missing` → can PASS without synthetic candles.

**Target policy:** KEEP `last_known@target` — unchanged; orthogonal to path gate.

---

## 4. Dry N=47 (DB UPDATE 없음)

COV-C post-reconcile evidence + COV-B predicate:

| | Value |
|--|------:|
| WOULD_PASS | **47** |
| WOULD_DEFER | **0** |
| DEFER_RATE | **0%** |

---

## 5. Tests

Focused pytest: **63 passed** (`path_defer_gate` + `path_quality` + `source_reconcile` + `timeseries` + `missing_candle` + `window_finalization`).

Cases: A complete · B unresolved DEFER · C unavailable DEFER · D absent PASS · E NOT_CHECKED DEFER · defer→complete retry.

---

## 6. Safety / WIP

TradingOrder / Outbox / LIVE / ARM / Scheduler / Scanner / AI Gate / TP/SL: **unchanged**.  
Frontend / migration / historical COMPLETED: **0**.  
Production ACTIVE `shadow_id=52` READ only (no force evaluate).  
Residual WIP (NewsCollector, Ambiguous, risk, portfolio, …) untouched.

---

## 7. Limitations

1. **INFINITE_DEFER_RISK = YES** — MAX_RETRY 정책 미도입 (별도 review).  
2. Production realtime DEFER 관찰은 다음 ACTIVE 60m tick 이후.  
3. COV-A/C/B 미커밋 — selective commit precheck 필요.  
4. Historical COMPLETED remediation = COV-D 이후 (이번 STEP 금지).

## STOP

COV-D · historical APPLY · TP/SL · OOS · frontend · LIVE · commit/push — **미실행**.
