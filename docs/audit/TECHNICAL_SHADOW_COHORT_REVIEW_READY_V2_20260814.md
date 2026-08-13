# Technical Shadow Cohort REVIEW_READY Performance Review v2

**Date:** 2026-08-14  
**Mode:** READ-ONLY (no Scanner/AI/TP-SL/Trading mutation)  
**Artifact JSON:** [TECHNICAL_SHADOW_COHORT_REVIEW_READY_V2_20260814.json](./TECHNICAL_SHADOW_COHORT_REVIEW_READY_V2_20260814.json)  
**Script:** `scripts/technical_shadow_cohort_review_v2.py`

## Verdict

`TECHNICAL_COHORT_REVIEW_COMPLETE_CHANGE_CANDIDATES`  
(+ note: `MORE_SAMPLE_RECOMMENDED_AT_50`)

## Milestone (DB)

| Gate | Value |
|------|-------|
| status | `SHADOW_COHORT_30_REVIEW_READY` |
| completed / active | 35 / 2 |
| VALID cohort | 32 (≥30) |
| NEW_POLICY MATCH | 16 (≥10) |
| mismatch_count | 0 |
| already_notified | true |

## Headline (VALID n=32, observational)

- 60m win≈40.6% · avg≈+0.17% · median=0 · bootstrap 95% CI mean **[-0.25, +0.66]**
- trimmed 10% mean60≈0.004 → **outlier-sensitive** (HOLO #15 alone moves avg)
- TP hit 0/32 · SL hit 1/32 · MFE≥6% = **0/32** → TP policy **CHANGE_CANDIDATE** (no auto-change)
- Path: `early_down_then_recover` ≈34% still dominant
- Confidence: all 0.80–0.89 → discrimination **INCONCLUSIVE**
- News A/B **not** mixed into these stats

## Policy enums (no apply)

- **CHANGE_CANDIDATE:** TP (+6% rarely reachable by MFE)
- **KEEP:** Top-N, liquidity, exclusions, cooldown
- **REVIEW_LATER:** SL, score ranking
- **INSUFFICIENT_DATA:** AI ALLOW/REDUCE, confidence, risk

## Next

Accumulate to **n≈50** VALID, then re-review TP candidate (still no auto apply).  
News track remains separate natural accumulation.
