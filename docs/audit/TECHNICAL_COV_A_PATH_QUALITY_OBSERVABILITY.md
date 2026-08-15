# TECHNICAL COV-A — PATH QUALITY OBSERVABILITY

**MODE:** IMPLEMENTATION ONLY / NO GATE / NO POLICY CHANGE  
**Date:** 2026-08-15  
**Verdict:** **PATH_QUALITY_OBSERVABILITY_READY_WITH_LIMITATIONS**

**COV_A_DOES_NOT_GATE_COMPLETION = true**

---

## Summary

| Item | Value |
|------|-------|
| path_quality_version | `technical_path_quality_v1` |
| New module | `operation/upbit_opportunity_shadow/path_quality.py` |
| Evaluator wire | `_compute_payload` → `path_quality`; `_apply_timeseries` writes `evaluation_detail.path_quality` |
| Schema migration | **NO** |
| COMPLETED / TP / SL / MFE / MAE | **unchanged** |
| New network fetch | **NO** (target `absent_by_target` evidence only) |
| Synthetic candles | **NO** |
| Frontend | **0** |
| commit / push | **0** |

### Limitations

- Without COV-C range confirmation, most intermediate DB holes stay **UNRESOLVED_MISSING** (`source_absent_confirmed` only from existing target-minute resolve map).
- Existing COMPLETED history is **not** backfilled (no row rewrite this STEP).
- Soft-sync still log-and-continue (COV-C).

---

## Semantics (implemented)

| Token | Definition |
|-------|------------|
| expected_minutes | `floor(detected)` … `floor(detected+60m)` matured slots (`candle_end <= now`) |
| observed_candles | bars whose floor(`candle_at`) ∈ expected |
| source_absent_confirmed | minutes in expected ∩ `absent_by_target` evidence, not observed |
| unresolved_missing | expected − observed − absent_confirmed |
| coverage_ratio_raw | observed / expected (diagnostic) |
| coverage_ratio_resolved | (observed + absent_confirmed) / expected |
| max_gap_minutes | max consecutive expected minutes **without observed bar** |
| source_unavailable | target resolve unavailable map **or** sync `ok=False` — observe only |

---

## Tests

`pytest tests/test_upbit_shadow_path_quality.py` + timeseries / missing_candle / window_finalization → **PASS**

## Dry examples (READ-ONLY, no DB UPDATE)

See [TECHNICAL_COV_A_PATH_QUALITY_DRY.json](TECHNICAL_COV_A_PATH_QUALITY_DRY.json):

| shadow_id | symbol | observed | unresolved | raw cov |
|----------:|--------|---------:|-----------:|--------:|
| 1 | KRW-VIRTUAL | 51 | 10 | 0.836 |
| 22 | KRW-ONDO | 58 | 3 | 0.951 |
| 49 | KRW-GRVT | 24 | 37 | 0.393 |

---

## Safety

TradingOrder / Outbox / create_order / POST /orders / LIVE / ARM / Scheduler / Scanner / Gate / TP / SL delta = **0**  
News: MATCHED 2/20 · NO_NEWS 22/20 · ACCUMULATING

---

## Next STEP (exactly one)

**COV-B — REALTIME PATH COMPLETENESS DEFER GATE PRECHECK**

( defer 구현 금지 — PRECHECK only after approval )

---

## STOP

COV-B implement · COMPLETED gate · soft-sync fail-closed · backfill · TP · OOS · LIVE · commit/push — **not done**.
