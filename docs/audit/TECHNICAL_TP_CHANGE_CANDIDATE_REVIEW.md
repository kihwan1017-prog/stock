# TECHNICAL TP CHANGE_CANDIDATE REVIEW

**Mode:** READ-ONLY / NO POLICY APPLY  
**Date:** 2026-08-15  
**HEAD:** `4f0df10`  
**Verdict (FINAL_TP_DECISION):** `CHANGE_CANDIDATE_NEEDS_OOS_VALIDATION`  
**TP_APPLY_READY:** **NO**

> TP/SL/Top-N/cooldown/Scanner/Gate/DB/LIVE/주문 **변경·실행 금지**.  
> commit/push **금지**.

---

## 1. Current sample (DB READ)

| Metric | Value |
|--------|------:|
| COMPLETED | **51** |
| ACTIVE | **1** |
| STRICT_VALID | **48** |
| return_missing | **3** |
| mismatch | **0** |

Baseline unchanged vs prior milestone status.

---

## 2. What v2 actually decided (no guess)

Source: `scripts/technical_shadow_cohort_review_v2.py` + `docs/audit/TECHNICAL_SHADOW_COHORT_REVIEW_READY_V2_*`

### CHANGE_CANDIDATE condition (exact)

```text
IF MFE>=6% rate == 0 AND MFE>=2% rate > 0
  → judge TP = CHANGE_CANDIDATE
ELSE
  → judge TP = REVIEW_LATER
```

### Metrics used

- Observed: `mfe_pct` reach table (0.5…6%), `tp_hit`/`sl_hit` counts, return_60m stats  
- Counterfactual: **MFE reach rates** at TP thresholds `{1, 1.5, 2, 3, 4, 6}%` — **not** re-simulated exits under alternate TP policies  
- **No** mean/median return grid by alternate TP  
- **No** explicit improvement threshold / tie rule / regression guard beyond narrative risk notes  
- Minimum VALID for n≈50 re-review note: script `if len(valid) < 50` → `MORE_SAMPLE_RECOMMENDED_AT_50` (soft gate, not hard reject)

### Candidate definition

Not a single TP. Hypothesis text:

> “consider TP candidate band **2–4%** in later experiment”

---

## 3. CURRENT_TP provenance

| Layer | Value |
|-------|-------|
| **Effective CURRENT_TP** | **6.0%** |
| Settings default | `settings.upbit_scanner_shadow_tp_pct: float = 6.0` (`src/stock_platform/common/settings.py`) |
| Evaluator consume | `evaluator.py` → `getattr(settings, "upbit_scanner_shadow_tp_pct", 6.0)` |
| ENV override key | pydantic field → env `UPBIT_SCANNER_SHADOW_TP_PCT` (no committed `.env` override found in repo search) |
| DB column for policy TP | **none** (per-row `tp_hit` is evaluation result under configured TP) |
| Strategy/runtime TP | separate risk/strategy domains — **not** Shadow Paper TP source |

**Provenance class:** CONFIG (settings default) · consumed by Shadow evaluator.

SL companion: `upbit_scanner_shadow_sl_pct = 3.0` (unchanged this STEP).

---

## 4. CANDIDATE_TP / DELTA

| Item | Value |
|------|-------|
| CURRENT_TP | **6.0%** |
| CANDIDATE_TP | **band 2–4%** (hypothesis only; not a single applied value) |
| DELTA | **−4pp … −2pp** vs 6% (band); **no single delta** |

---

## 5. TP “grid” available from script (MFE reach only)

STRICT_VALID n=48 (this review):

| Threshold (counterfactual) | MFE reach count | MFE reach rate |
|---------------------------:|----------------:|---------------:|
| ≥1.0% | 11 | 0.2292 |
| ≥1.5% | 9 | 0.1875 |
| ≥2.0% | 7 | 0.1458 |
| ≥3.0% | 5 | 0.1042 |
| ≥4.0% | 2 | 0.0417 |
| ≥6.0% (CURRENT TP level) | **1** | **0.0208** |

**Not available from script (do not invent):** per-TP hit rate under re-run evaluator, mean/median return under alternate TP, PnL delta Current vs Candidate.

---

## 6. Current cohort summary (STRICT_VALID=48)

| Metric | Value |
|--------|------:|
| TP hit count / rate | **1 / 0.0208** |
| SL hit count / rate | **4 / 0.0833** |
| mean / median return_60m | **0.0513 / 0.0000** |
| mean / median MFE | **0.6676 / 0.2086** |
| mean / median MAE | **−0.7939 / −0.6866** |
| max MFE | **10.0939** (single symbol) |

v2 (n=32): TP hit 0/32 · MFE≥6% **0/32** · MFE≥2% 5/32.  
Now: MFE≥6% **1/48** → **exact v2 boolean `mfe6_rate==0` no longer holds** → script would emit **REVIEW_LATER** today, while directional rarity of TP6 remains (1/48).

---

## 7. Current vs Candidate (honest comparison)

| Metric | Current TP 6% | Candidate band 2–4% | Delta |
|--------|---------------|---------------------|-------|
| sample n | 48 | same cohort (no separate arm) | — |
| TP hit rate (observed under 6%) | 0.0208 | **N/A** (not simulated) | — |
| MFE reach @6% | 0.0208 | — | — |
| MFE reach @2% / @3% / @4% | 0.1458 / 0.1042 / 0.0417 | used as **reach proxy only** | higher reach ≠ proven better exit PnL |
| mean/median return | 0.0513 / 0.0 | **N/A under alternate TP** | — |

**Conclusion:** Candidate is **not proven superior** on return metrics; only MFE-reach counterfactual suggests lower TP levels are touched more often.

---

## 8. Return-missing 3 (excluded from STRICT_VALID)

| shadow_id | symbol | missing | MFE/MAE/TP/SL | Note |
|----------:|--------|---------|---------------|------|
| 4 | KRW-ID | return_5m | present; tp/sl false | early COMPLETED; partial windows |
| 6 | KRW-EDGE | return_5m, return_15m | present; tp/sl false | same detect batch |
| 10 | KRW-LSK | return_30m | present; **sl_hit true** | partial window null |

**Cause:** incomplete intermediate window fills (candle/path), not TP policy corruption.  
**In comparison?** **Excluded** (STRICT_VALID filter).  
**MISSING_DATA_BIAS:** **LOW**

---

## 9. Sample sufficiency

| Gate | Result |
|------|--------|
| OPERATIONS_SAMPLE (COMPLETED≥50) | **YES** (51) |
| STRICT_ANALYSIS_READY | **YES** for observational re-check (n=48); script soft note preferred n≥50 VALID → **borderline** |
| Explicit hard STRICT minimum in code | **NO_EXPLICIT_STRICT_MINIMUM** (only soft `MORE_SAMPLE_RECOMMENDED_AT_50`) |

---

## 10. Robustness / concentration / OOS

| Check | Result |
|-------|--------|
| mean vs median return | mean≈0.05 · median=0 → **outlier-sensitive** |
| MFE≥6% concentration | **1/48 = KRW-GRVT only** (max MFE≈10.1) |
| MFE≥2% symbols | GRVT, AVNT, KAITO, WLD, HOLO (small n) |
| CONCENTRATION_RISK | **MEDIUM** (single name drives MFE≥6 break of v2 boolean) |
| OOS | **IN_SAMPLE_ONLY** — discovery (v2) + this re-check share same Shadow cohort |

---

## 11. Other policies (reconfirm only)

| Policy | Status |
|--------|--------|
| SL | **REVIEW_LATER** (not reviewed for apply) |
| Top-N | **KEEP** |
| cooldown | **KEEP** |

---

## 12. Final decisions

| Flag | Value |
|------|-------|
| FINAL_TP_DECISION | **CHANGE_CANDIDATE_NEEDS_OOS_VALIDATION** |
| TP_APPLY_READY | **NO** |
| Why not APPLY | no alternate-TP PnL proof; in-sample only; candidate is a band; v2 hard trigger weakened by 1 outlier |

---

## 13. News baseline (untouched)

MATCHED **2/20** · NO_NEWS **22/20** · `NEWS_AB_SAMPLE_ACCUMULATING`

---

## 14. Safety

TradingOrder/Outbox/create_order/POST orders/LIVE/ARM/Scheduler/strategy/TP mutation = **0**  
DB mutation = **0** · production code mutation = **0**

---

## 15. Next STEP (exactly one)

**TECHNICAL TP OOS VALIDATION DESIGN**

(Design holdout / forward window / counterfactual evaluator plan — still no TP apply.)
