# CURRENT_WORK

**역할:** 현재 진행 중인 작업만 기록한다.  
**최종 갱신:** 2026-08-21 (ORDER_LIMIT_V2 READY — NEXT TRADING DAY)

---

## Parallel policy

**TRACK U** / **TRACK K** / **SHARED** — U+K commit 혼합 금지

---

## Current Phase

| Track | STEP | Verdict | Next |
|-------|------|---------|------|
| **U** | UBA1380 | isolation maintained | KEEP |
| **K** | ORDER_LIMIT_V2 | **`KIWOOM_DAILY_ORDER_POLICY_V2_READY_FOR_NEXT_TRADING_DAY`** | NEXT KRX DAY RETRY FILL SMOKE USING V2 |
| **SHARED** | — | code committed; no live restart today | — |

2026-08-21: legacy V1 `daily_order_limit=1` / #1798 counted — **unchanged**.  
V2 (`daily_submit_limit` / `daily_filled_entry_limit`) opt-in from **2026-08-22+** after admin save. UBA1381 V2 fields remain NULL (no auto-relax).

DDL: `database/sql/order_limit_v2_additive.sql` (applied idempotent; Alembic cycle not joined).

---

## Next Gate

**Exactly one:** NEXT_KRX_DAY_RETRY_FIRST_REAL_FILL_SMOKE_USING_ORDER_POLICY_V2
