# TECHNICAL COV-C — SOURCE ABSENCE / SOFT-SYNC RECONCILIATION

**MODE:** IMPLEMENTATION WITH SAFETY BOUNDARY · **NO COMPLETED GATE**  
**Date:** 2026-08-15  
**Verdict:** **SOURCE_RECONCILIATION_READY**  
**COV_C_DOES_NOT_GATE_COMPLETION = true**  
**PATH_GATE_EVIDENCE_READY = YES**

**Dry:** [TECHNICAL_COV_C_SOURCE_RECONCILE_DRY.json](TECHNICAL_COV_C_SOURCE_RECONCILE_DRY.json)

---

## Summary

| Item | Value |
|------|-------|
| path_quality version | `technical_path_quality_v2` |
| New module | `source_range_reconcile.py` |
| Wire | `evaluator._compute_payload` after target resolve |
| Range fetch | 1 collect/window when DB missing (~1 req for 60m) |
| COMPLETED / TP / SL / MFE / MAE / target fallback | **unchanged** |
| Historical DB mutation | **0** |
| commit / push | **0** |

### Dry N=47 (GET only · no upsert)

| | Before | After (absence confirmed) |
|--|--------:|--------:|
| WOULD_PASS | 13 | **47** |
| WOULD_DEFER | 34 | **0** |
| DEFER_RATE | 72.3% | **0.0%** |
| SOURCE_ABSENT_CONFIRMED rows/min | ~14/22 (target) | **34 / 503** |
| DB_MISSING_SOURCE_PRESENT | — | **0 / 0** |
| SOURCE_UNAVAILABLE | 0 | **0** |

**SOURCE_RECONCILIATION_EFFECT = HIGH**  
Discovery “holes” are overwhelmingly **source-absent** (API range에도 없음) — not unsynced exchange candles. Gate false-defer collapses once absence evidence is applied.

---

## Flow

```text
DB load → expected minutes → if missing:
  range collect (no N+1)
  classify DB_PRESENT / DB_MISSING_SOURCE_PRESENT / SOURCE_ABSENT_CONFIRMED / UNAVAILABLE
  upsert present via existing MinuteSync(resume=False)  [realtime only]
  reload bars
→ compute_path_quality(v2) + source_reconcile provenance
→ existing evaluator (COMPLETED ungated)
```

States: DB_PRESENT · DB_MISSING_SOURCE_PRESENT · SOURCE_ABSENT_CONFIRMED · SOURCE_UNAVAILABLE · SOURCE_NOT_CHECKED  
Absent ≠ “no-trade proven” — means successful range response lacked that minute.

---

## Safety

TradingOrder/Outbox/LIVE/Scanner/Gate/TP delta = **0**  
News: 2/20 · 22/20 ACCUMULATING  

## Next STEP (exactly one)

**COV-B — REALTIME PATH COMPLETENESS DEFER GATE**

## STOP

COV-B 구현 · COMPLETED gate · historical rewrite · commit — **미실행**.
