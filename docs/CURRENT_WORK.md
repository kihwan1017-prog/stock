# CURRENT_WORK

**역할:** 현재 진행 중인 작업만 기록한다.  
**최종 갱신:** 2026-08-23 (Entry Candidate final promotion review)

---

## Parallel policy

**TRACK U** / **TRACK K** / **SHARED** — U+K commit 혼합 금지

---

## Current Phase

| Track | STEP | Verdict | Next |
|-------|------|---------|------|
| **U** | Entry final promotion review | **ENTRY_RSI65_VOL08_PREFERRED_BUT_NOT_PROFITABLE** | COLLECT_MORE_FORWARD_SAMPLE_WITH_PREFERRED_ENTRY_CANDIDATE |
| **U** | Exit Candidate A | **REJECTED** | KEEP_BASELINE_EXIT_POLICY |
| **SHARED** | Dynamic FREE first AUTO BUY | **BROKER_REJECTED** | FIX_UPBIT_MARKET_BUY… |
| **K** | ORDER_LIMIT_V2 | unchanged | NEXT_KRX_DAY… |

---

## U — Entry promotion review (READ/SHADOW)

- Preferred: **RSI65_VOL08** (B1) — Volume≥1.0 추가 불필요
- Absolute profitable: **NO** (net still negative, PF&lt;1)
- REAL_PROMOTION_RECOMMENDED: **NO**
- Mutations: all **0**

Evidence: `.run/k_upbit_entry_candidate_final_promotion_review.json`

---

## Next Gate

**Exactly one:** COLLECT_MORE_FORWARD_SAMPLE_WITH_PREFERRED_ENTRY_CANDIDATE
