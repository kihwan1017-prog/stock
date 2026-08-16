# TECHNICAL SHADOW LONG_ACTIVE TERMINATION — IMPLEMENTATION (TARGET_ONLY)

**STEP:** U-TERM-A · **MODE:** production code + tests · **Date:** 2026-08-16  
**HEAD baseline:** `3bbf0cd` · **Verdict:** **`TERMINATION_TARGET_ONLY_READY`**  
**JSON:** [TECHNICAL_SHADOW_LONG_ACTIVE_TERMINATION_IMPL.json](TECHNICAL_SHADOW_LONG_ACTIVE_TERMINATION_IMPL.json)

---

## Implemented

| Item | Value |
|------|-------|
| Predicate | ACTIVE + 60m mature + MISSING + ABSENT_CONFIRMED + reconcile OK + unresolved=0 + unavailable=false + prior lag>180 + grace |
| Grace | `first_blocked_at` + 3×interval (540s); bootstrap = `target_candle_end(60m)` |
| Terminal | `CANCELLED` / `TARGET_PERMANENTLY_UNRESOLVABLE` |
| SOURCE_UNAVAILABLE | ACTIVE retry (max-age **not** implemented) |
| Fake metrics | **none** on terminate |
| Schema / migration | **NO** |
| Shadow 52 production UPDATE | **NO** (fixture 9052 only) |

## Files

- `src/stock_platform/operation/upbit_opportunity_shadow/termination.py` (new)
- `src/stock_platform/operation/upbit_opportunity_shadow/evaluator.py`
- `tests/test_upbit_shadow_long_active_termination.py` (new)

## Tests

A–H + grace/candidate unit · COV path_defer regression **PASS**

## Next

**TERM-B — UPBIT TERMINATION RUNTIME LOAD + NATURAL OBSERVATION**
