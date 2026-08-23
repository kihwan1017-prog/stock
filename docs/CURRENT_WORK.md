# CURRENT_WORK

**역할:** 현재 진행 중인 작업만 기록한다.  
**최종 갱신:** 2026-08-23 (Entry B1 Forward Validation Phase)

---

## Parallel policy

**TRACK U** / **TRACK K** / **SHARED** — U+K commit 혼합 금지

---

## Current Phase

| Track | STEP | Verdict | Next |
|-------|------|---------|------|
| **U** | Entry B1 Forward Validation | **SAMPLE_COLLECTION_IN_PROGRESS** | COLLECT_MORE_NEW_UNSEEN_FORWARD |
| **U** | Exit Candidate A | **REJECTED** | KEEP_BASELINE_EXIT_POLICY |
| **SHARED** | Dynamic FREE first AUTO BUY | **BROKER_REJECTED** | FIX_UPBIT_MARKET_BUY… |
| **K** | ORDER_LIMIT_V2 | unchanged | NEXT_KRX_DAY… |

---

## U — Entry B1 Forward Validation (SHADOW ONLY)

- Preferred: **B1 RSI65 / VOL0.8** (Candidate B VOL1.0 excluded)
- LEGACY_FORWARD 459 preserved · NEW_UNSEEN_FORWARD separated
- Targets: combined ≥1000 · new ≥500
- REAL_PROMOTION_RECOMMENDED: **NO** (auto-promote forbidden)
- REAL_POLICY_MUTATION: **0**

Evidence: `.run/k_upbit_entry_b1_forward_validation.json`

---

## Next Gate

**Exactly one:** COLLECT_MORE_NEW_UNSEEN_FORWARD
