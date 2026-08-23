# CURRENT_WORK

**역할:** 현재 진행 중인 작업만 기록한다.  
**최종 갱신:** 2026-08-23 (Upbit Exit Policy Candidate A Shadow A/B)

---

## Parallel policy

**TRACK U** / **TRACK K** / **SHARED** — U+K commit 혼합 금지

---

## Current Phase

| Track | STEP | Verdict | Next |
|-------|------|---------|------|
| **U** | Exit Policy Candidate #1 Shadow A/B | **TP_TRAIL_CANDIDATE_A_REJECTED** | KEEP_BASELINE_EXIT_POLICY |
| **SHARED** | Dynamic FREE symbol first AUTO BUY | **BROKER_REJECTED** (PROM / order 1799) | FIX_UPBIT_MARKET_BUY_KRW_AMOUNT_MAPPING… |
| **K** | ORDER_LIMIT_V2 | unchanged | NEXT_KRX_DAY… |

---

## U — Exit A/B (Shadow/Paper only)

- Baseline TP10/Trail3 vs Candidate A TP1 / trail act+0.5 / dist 0.3
- REAL policy/order/LIVE/ARM/Risk/Slot/UBA1381 mutation: **0**
- Forward sample: **459** completed shadows (`exit_ab` backfill)
- Candidate: higher win rate / lower fee-only churn, but **worse net** → rejected for REAL promotion

Evidence: `.run/k_upbit_tp_trailing_candidate_a_shadow_ab.json`

---

## Next Gate

**Exactly one (U exit):** KEEP_BASELINE_EXIT_POLICY
