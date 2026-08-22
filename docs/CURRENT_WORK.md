# CURRENT_WORK

**역할:** 현재 진행 중인 작업만 기록한다.  
**최종 갱신:** 2026-08-22 (COMMON MANUAL open-order AUTO risk isolation)

---

## Parallel policy

**TRACK U** / **TRACK K** / **SHARED** — U+K commit 혼합 금지

---

## Current Phase

| Track | STEP | Verdict | Next |
|-------|------|---------|------|
| **SHARED** | MANUAL open ≠ AUTO max_open_orders | **COMMON_MANUAL_OPEN_ORDER_AUTO_RISK_ISOLATION_COMPLETE** (deploy/restart/proof pending in-session) | RETRY_SINGLE_MINIMUM_REAL_AUTO_BUY |
| **U** | Natural autotrading | running | observe after GEOD retry |
| **K** | ORDER_LIMIT_V2 | unchanged | NEXT_KRX_DAY… |

---

## Semantics (SoT)

- `auto_open_orders` only vs `max_open_orders`
- unmapped remote wait → **MANUAL** (AUTO count 제외)
- `unknown_open_orders > 0` → fail-closed
- same-symbol MANUAL+AUTO → SymbolOwnership conflict (계좌 전체 pause 금지)

---

## Next Gate

**Exactly one:** RETRY_SINGLE_MINIMUM_REAL_AUTO_BUY
