# CURRENT_WORK

**역할:** 현재 진행 중인 작업만 기록한다.  
**최종 갱신:** 2026-08-23 (Upbit Entry Candidate B Shadow A/B)

---

## Parallel policy

**TRACK U** / **TRACK K** / **SHARED** — U+K commit 혼합 금지

---

## Current Phase

| Track | STEP | Verdict | Next |
|-------|------|---------|------|
| **U** | Entry Candidate B Shadow A/B | **ENTRY_CANDIDATE_B_FORWARD_VALIDATED** | REVIEW_ENTRY_CANDIDATE_B_FOR_REAL_PROMOTION |
| **U** | Exit Candidate A Shadow A/B | **TP_TRAIL_CANDIDATE_A_REJECTED** | KEEP_BASELINE_EXIT_POLICY |
| **SHARED** | Dynamic FREE first AUTO BUY | **BROKER_REJECTED** | FIX_UPBIT_MARKET_BUY… |
| **K** | ORDER_LIMIT_V2 | unchanged | NEXT_KRX_DAY… |

---

## U — Entry A/B (Shadow only)

- Baseline RSI≤70 / VOL≥0.8 vs Candidate B RSI≤65 / VOL≥1.0
- Exit 고정: TP10 / trail3 (Candidate A exit **unused**)
- Forward: 459 opportunities · Baseline entries 192 · Candidate B 116
- Net / PF / filter-benefit 개선 → **forward validated** (REAL 미적용 — review only)
- Mutations: REAL/LIVE/ARM/Risk/Slot/UBA1381 = **0**

Evidence: `.run/k_upbit_entry_candidate_b_shadow_ab.json`

---

## Next Gate

**Exactly one (U entry):** REVIEW_ENTRY_CANDIDATE_B_FOR_REAL_PROMOTION
