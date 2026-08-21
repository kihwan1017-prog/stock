# CURRENT_WORK

**역할:** 현재 진행 중인 작업만 기록한다.  
**최종 갱신:** 2026-08-21 (KIWOOM TODAY COMPLETION — V2 OPTED-IN / NEXT DAY FILL)

---

## Parallel policy

**TRACK U** / **TRACK K** / **SHARED** — U+K commit 혼합 금지

---

## Current Phase

| Track | STEP | Verdict | Next |
|-------|------|---------|------|
| **U** | UBA1380 | isolation maintained | KEEP |
| **K** | ORDER_LIMIT_V2 + DRY completion | **V2 5/1 opted-in; today V1; 2026-08-24 V2** | NEXT_KRX_DAY_FIRST_REAL_FILL_AND_EXIT_PROOF |
| **SHARED** | risk-limits Decimal fix; KIWOOM exit loader flag | code path ready | — |

UBA1381: `daily_submit_limit=5`, `daily_filled_entry_limit=1`, `daily_order_limit=1` (legacy unchanged).  
#1798 risk_counted unchanged. REAL ENTRY today 금지.

Runbook: `docs/trading/KIWOOM_UBA1381_20260824_ONE_SHOT_REAL_FILL_RUNBOOK.md`

---

## Next Gate

**Exactly one:** NEXT_KRX_DAY_FIRST_REAL_FILL_AND_EXIT_PROOF
