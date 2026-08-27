# UPBIT RESTART RELIABILITY + DATA TRUST PROOF

**FINAL_VERDICT:** UPBIT_RESTART_RELIABILITY_REGRESSION_FIXED

**CURRENT_KST:** 2026-08-28T00:01:45.128669+09:00

## RESTART
- Count: **2** (1st exposed regression, 2nd loaded L0 restore-epoch ensure)
- PROD · workers=1 · reload=false · listener=1

## LEASE
- BEFORE=6 AFTER=6 · NEW_LEASE_CREATED=false

## STACK
- Runtime/Runner/Worker/Exit/Scanner/Feed: RUNNING / REAL_FRESH
- Watchdog + Supervisor started · 3 ticks observed healthy

## WAITING REGRESSION
- After 1st restart: PORTFOLIO_STALE_PRE_RESTORE_WAITING loop (startup feed-pending skipped mark_restored)
- Fix: Watchdog L0 _ensure_restore_epoch_when_stack_healthy + L1 heal on PIPELINE_STALL
- After 2nd restart: **STALE false-positive count = 0** · startup stack_ok + waiting_nudge=3

## PIPELINE / FIRST ZERO
- CLASSIFICATION: NORMAL_NO_SIGNAL
- FIRST_ZERO: ENTRY_SIGNAL / SHORT_MA_NOT_ABOVE_LONG_MA

## DATA TRUST
- Restart1 downtime: INVALID FEED_DOWN window#4 recorded (not hidden)
- Current: VALID window#6 · SoT divergence=false
- False INVALID-only incident after policy: false

## TRADE QUALITY
- #1905/#1906 KRW-DRV RT: VALID window span
- RAW mutation=0

## SAFETY
FORCED_REAL_ORDER=0 · REAL policy unchanged · NEW_LEASE=0 · CAN_SAFELY_CONTINUE=true

## NEXT
CONTINUE_VALID_TRAILING_SHADOW_N10_COLLECTION
