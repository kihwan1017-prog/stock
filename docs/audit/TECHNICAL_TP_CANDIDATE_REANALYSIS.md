# TECHNICAL TP CANDIDATE REANALYSIS

**MODE:** READ-ONLY ANALYSIS · **no production TP/SL change · no OOS · no POST_COV in selection**  
**Date:** 2026-08-15  
**HEAD:** `5c6ad67`  
**Script:** `scripts/technical_tp_candidate_reanalysis.py`  
**Verdict:** **`FROZEN_CANDIDATE_TP = null`** · reason **`KEEP_6_SUPERIOR`**  
**JSON:** [TECHNICAL_TP_CANDIDATE_REANALYSIS.json](TECHNICAL_TP_CANDIDATE_REANALYSIS.json)

---

## 1. Sample reconciliation

| Metric | Value |
|--------|------:|
| DISCOVERY_COMPLETED | **50** |
| DISCOVERY_STRICT_VALID | **47** |
| PAIRED_VALID_N | **47** |
| SAMPLE_RECONCILIATION | **PASS** |

Cutoff: `shadow_id ≤ 51` ∧ `completed_at ≤ 2026-08-14T23:25:40.424Z` ∧ COMPLETED.

### Excluded from STRICT (in-cutoff)

| shadow_id | symbol | reason |
|----------:|--------|--------|
| 4 | KRW-ID | RETURN_WINDOW_MISSING:5 |
| 6 | KRW-EDGE | RETURN_WINDOW_MISSING:5,15 |
| 10 | KRW-LSK | RETURN_WINDOW_MISSING:30 |

### Not in discovery (provenance only)

| id | note |
|----|------|
| 51 | POST_DISCOVERY_PRE_COV (µs past cutoff) · **unused** |
| 52 | TARGET_BLOCKED · **unused** |
| 53+ | POST_COV OOS reserve · **unused** |

raw coverage threshold **미적용** (SOURCE_ABSENT 재해석 반영).

---

## 2. Paired metrics (n=47 · SL=3% · fee/slippage=none)

| TP | mean | median | +rate | loss | TP-hit | SL-exit | timeout | MFE mean | MAE mean |
|---:|-----:|-------:|------:|-----:|-------:|--------:|--------:|---------:|---------:|
| **2%** | **−0.0487** | 0.0 | 0.4468 | 0.4255 | 7 (0.1489) | 3 (0.0638) | 37 (0.7872) | 0.7757 | −0.68 |
| **3%** | **0.0331** | 0.0 | 0.4468 | 0.4255 | 5 (0.1064) | 3 (0.0638) | 39 (0.8298) | 0.7757 | −0.68 |
| **4%** | **−0.0007** | 0.0 | 0.4255 | 0.4255 | 2 (0.0426) | 3 (0.0638) | 42 (0.8936) | 0.7757 | −0.68 |
| **6%** | **0.0629** | 0.0 | 0.4255 | 0.4255 | 1 (0.0213) | 3 (0.0638) | 43 (0.9149) | 0.7757 | −0.68 |

same-candle ambiguous: **0** all TP.

---

## 3. Deltas vs baseline 6%

| Cand | Δ mean | Δ median | Δ +rate | Δ loss | better / worse / equal |
|------|-------:|---------:|--------:|-------:|------------------------|
| 2% | **−0.1116** | 0.0 | +0.0213 | 0.0 | 4 / 3 / 40 |
| 3% | **−0.0298** | 0.0 | +0.0213 | 0.0 | 2 / 3 / 42 |
| 4% | **−0.0636** | 0.0 | 0.0 | 0.0 | 0 / 2 / 45 |

PRIMARY = paired counterfactual exit return — **no candidate beats 6% mean**.

TP-hit는 2/3/4가 더 높으나 mean 열세 → hit-only 선택 **금지** (gate F fail).

---

## 4. Concentration / LOSO

| TP | concentration | LOSO | note |
|----|---------------|------|------|
| 2% | **MEDIUM** | **ROBUST** | stably worse vs 6 |
| 3% | **HIGH** | **INCONCLUSIVE** | sign-flip under LOSO |
| 4% | **HIGH** | **ROBUST** | stably worse; top abs share high |

---

## 5. Candidate gates

| Check | 2% | 3% | 4% |
|-------|----|----|----|
| A clear mean > 6% | FAIL | FAIL | FAIL |
| B median not worse | PASS | PASS | PASS |
| C loss not worse | PASS | PASS | PASS |
| D MAE ok | PASS | PASS | PASS |
| E conc not HIGH/FRAGILE | PASS | FAIL | FAIL |
| F not hit-only | FAIL | FAIL | FAIL |
| G same-candle | PASS | PASS | PASS |
| **PASSED** | **NO** | **NO** | **NO** |

---

## 6. Decision

| Field | Value |
|-------|-------|
| FINAL_CANDIDATE_DECISION | `FROZEN_CANDIDATE_TP=null` |
| FROZEN_CANDIDATE_TP | **null** (analysis freeze only) |
| reason | **KEEP_6_SUPERIOR** |
| CURRENT_TP (production) | **6%** unchanged |
| CURRENT_SL | **3%** unchanged |
| OOS_CANDIDATE_FREEZE_READY | **NO** |
| OOS_START_READY | **NO** |

---

## 7. OOS contamination

| Item | Value |
|------|------:|
| POST_COV_ROWS_AVAILABLE | 14 |
| POST_COV_ROWS_USED_FOR_SELECTION | **0** |
| OOS_CONTAMINATION | **0** |
| shadow52 used | **false** |

---

## 8. Safety / News

TradingOrder **241** · Outbox **52** · LIVE OFF · execution false.  
News: MATCHED 3 · NO_NEWS 30+10 · EXCLUDED 5 · ACCUMULATING · unused.  
production/DB mutation **0** · commit/push **no**.

## 9. Next STEP (exactly one)

**TECHNICAL TP KEEP_6 CLOSEOUT**

## STOP

POST_COV unused · TP/SL production unchanged · OOS not started · no commit/push.
