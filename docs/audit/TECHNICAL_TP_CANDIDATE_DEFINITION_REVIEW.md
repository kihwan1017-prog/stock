# TECHNICAL TP CANDIDATE DEFINITION REVIEW

**Mode:** READ-ONLY ANALYSIS ONLY · **no TP apply · no OOS start**  
**Date:** 2026-08-15  
**HEAD:** `4f0df10`  
**Script:** `scripts/technical_tp_candidate_definition_review.py`  
**Verdict:** `CANDIDATE_EVIDENCE_INSUFFICIENT`  
**FROZEN_CANDIDATE_TP:** **null**  
**Operational note:** Discovery evidence favors **KEEP_6** (not a freeze for change)

---

## 1. Freeze / method

| Item | Value |
|------|-------|
| Discovery rule | `shadow_id ≤ 51` ∧ `completed_at ≤ 2026-08-14T23:25:40.424Z` ∧ COMPLETED |
| Baseline TP | **6.0%** |
| Candidates | **2% / 3% / 4%** |
| SL | **3.0%** (unchanged) |
| Policy | `compute_tp_sl` · **SAME_CANDLE_SL_CONSERVATIVE** |
| Candles | `market.candle_minute` **DB only** (no sync / no API write) |
| LOOK_AHEAD_VIOLATION | **0** |

Exit return = first_hit exit at TP/SL price, else TIMEOUT = last bar close in 60m window.

---

## 2. Sample counts

| Metric | n |
|--------|--:|
| Discovery COMPLETED (under cutoff) | **50** |
| STRICT_VALID | **47** |
| return_missing excluded | **3** |
| missing bars | **0** |
| **PAIRED_VALID_N** (ok for all TP) | **47** |

Note: Prior ops baseline COMPLETED=51; one COMPLETED falls outside cutoff/`completed_at` filter → discovery **50**. Analysis uses **47** paired STRICT rows.

---

## 3. Paired results (n=47)

| TP | mean exit | median | +rate | loss | TP-hit | SL-exit | timeout | mean MFE | mean MAE |
|---:|----------:|-------:|------:|-----:|-------:|--------:|--------:|---------:|---------:|
| **2%** | **−0.0487** | 0.0 | 0.4468 | 0.4255 | 0.1489 | 0.0638 | 0.7872 | 0.7757 | −0.68 |
| **3%** | **0.0331** | 0.0 | 0.4468 | 0.4255 | 0.1064 | 0.0638 | 0.8298 | 0.7757 | −0.68 |
| **4%** | **−0.0007** | 0.0 | 0.4255 | 0.4255 | 0.0426 | 0.0638 | 0.8936 | 0.7757 | −0.68 |
| **6%** | **0.0629** | 0.0 | 0.4255 | 0.4255 | 0.0213 | 0.0638 | 0.9149 | 0.7757 | −0.68 |

same_candle ambiguous on paired set: **0**.

---

## 4. Paired delta vs 6%

| Candidate | Δ mean | Δ median | Δ +rate | Δ loss | Δ TP-hit |
|----------:|-------:|---------:|--------:|-------:|---------:|
| 2% | **−0.1116** | 0.0 | +0.0213 | 0.0 | +0.1276 |
| 3% | **−0.0298** | 0.0 | +0.0213 | 0.0 | +0.0851 |
| 4% | **−0.0636** | 0.0 | 0.0 | 0.0 | +0.0213 |

**No candidate beats 6% on primary paired mean exit return.**

---

## 5. Guards / robustness

| Check | Result |
|-------|--------|
| Downside (loss rate / SL-exit) | **no degradation vs 6%** (identical); but **mean return worse** for 2/3/4 |
| Median | all **0** — no median edge |
| Neighboring TP | 2% worst mean · 3% least-bad among candidates · 4% mid · **6% best** |
| Concentration 2% | **MEDIUM** (positive deltas on few symbols; overall still negative) |
| Concentration 3% | **HIGH** (`leave-one-symbol-out` sign flips) |
| Concentration 4% | **LOW** |
| TP-hit-only selection | **rejected** (2% highest hit, lowest mean) |

---

## 6. Selection

| Field | Value |
|-------|-------|
| Verdict | **`CANDIDATE_EVIDENCE_INSUFFICIENT`** |
| FROZEN_CANDIDATE_TP | **null** |
| Why not freeze 2/3/4 | Discovery counterfactual shows **KEEP_6** superior on primary metric; freezing a losing band for OOS would be unjustified optimization theater |
| OOS freeze package | **NOT READY** |

### Metrics (for future, if ever re-opened)

- PRIMARY: paired counterfactual exit return %  
- GUARDS: loss rate, median return, MAE, SL-exit rate, symbol concentration, same-candle count  

---

## 7. News / safety

News: MATCHED **2/20** · NO_NEWS **22/20** · isolated.  
production/DB/Trading/LIVE mutation = **0** · commit/push = **no**

---

## 8. Next STEP (exactly one)

**TECHNICAL OBSERVATION DATA REVIEW**

(Confirm discovery cutoff completeness / STRICT_VALID gaps; **do not** expand TP grid; **do not** apply TP.)
