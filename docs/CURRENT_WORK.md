# CURRENT_WORK

**역할:** 현재 진행 중인 작업만 기록한다.  
**최종 갱신:** 2026-08-24 (Kiwoom Next Trading Day Lifecycle)

---

## Parallel policy

**TRACK U** / **TRACK K** / **SHARED** — U+K commit 혼합 금지

---

## Current Phase

| Track | STEP | Verdict | Next |
|-------|------|---------|------|
| **U** | Entry B1 Forward Validation | **SAMPLE_COLLECTION_IN_PROGRESS** | COLLECT_MORE_NEW_UNSEEN_FORWARD |
| **K** | Next Trading Day Auto Start + EOD Lifecycle | **IMPLEMENTED_FAIL_CLOSED** (uncommitted) | CONFIRM_OPT_IN → next KRX session observe |
| **K** | #1822 Entry Provenance | **BROKER_IMPORTED_POSITION** (no historical mutate) | Future BUY→binding→SELL link |

---

## K — Next Trading Day Lifecycle (2026-08-24)

- Service: `KiwoomTradingDayLifecycleService` + scanner hook
- Opt-in phrase: `ENABLE KIWOOM NEXT DAY AUTO START`
- Fail-closed precheck (13 gates); Activation successor only
- Evidence: `.run/k_kiwoom_next_trading_day_lifecycle.json` / `.md`

---

## Next Gate

**K:** CONFIRM_NEXT_DAY_OPT_IN_THEN_OBSERVE_NEXT_KRX_SESSION  
**U:** COLLECT_MORE_NEW_UNSEEN_FORWARD
