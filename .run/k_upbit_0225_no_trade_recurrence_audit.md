# UPBIT 02:25+ No-Trade — Final Recurrence Audit

**FINAL_VERDICT:** `UPBIT_0225_FAILURE_ROOT_FIXED`  
**CURRENT_KST:** 2026-08-28 (audit window)

## TRADE

| Field | Value |
|-------|--------|
| LAST_REAL_TRADE | 2026-08-28 **02:25:19** KST · order **1925** BUY KRW-ADA FILLED |
| MATCH_USER_TIME | **true** (user 02:25:17, Δ≈2s) |
| MINUTES_NO_TRADE | ~270+ |

## ROOT CAUSE

**PRIMARY:** `EXIT_PENDING_ZERO_FILL_STUCK`

- Slot 4 **KRW-ADA** status `EXIT_PENDING` since ~02:31
- SELL order **1926** status `ACCEPTED`, filled_qty=0 since **02:29:50**
- Age at detection ≈ **4.4h**

**SECONDARY:**

1. E0 `ENTRY_PASS` ×5 (ENA/DRV/STX/SHIB/XPL) with no subsequent BUY → intermittent `PIPELINE_STALL`
2. Majority of 3407 ENTRY_EVAL blocked by `SHORT_MA_NOT_ABOVE_LONG_MA` (normal signal wait)
3. Backend restart ~06:22 (market-data deploy) → in-memory LIVE/ARM OFF → Data Trust `INVALID/STACK_DOWN`

Daily quota **not** blocking (8/20, remaining 12).

## FIRST ZERO (corrected)

- STAGE: **EXIT**
- REASON: **EXIT_PENDING_ZERO_FILL_STUCK**
- Prior misread: ORDER / ENTRY_PASS_WITHOUT_ORDER (masked the exit stuck)

## DATA TRUST

| Since 02:25 | Seconds |
|-------------|---------|
| VALID | ~10733 |
| DEGRADED | ~3536 |
| INVALID | ~1488 (from 06:23 STACK_DOWN) |

**DATA_TRUST_CLASSIFICATION_BUG=true** (pre-fix): exit stuck window was not INVALID.  
**Fix:** `EXIT_PENDING_STUCK` → INVALID.

## RECURRENCE

- SIGNATURE: `EXIT_PENDING_ZERO_FILL_STUCK:ACCEPTED_SELL`
- COUNT: 1
- CLASSIFICATION: **NEW_FAILURE_MODE** (related family: OPEN_ORDER_RESTORE_BLOCK / protective SELL WAIT not auto-cancelled)

## WATCHDOG

- Pre-fix: **did not** classify EXIT_PENDING ACCEPTED stuck → user noticed no-trade first
- JUDGEMENT: `WATCHDOG_CLASSIFICATION_GAP` + `DATA_TRUST_GAP`
- Post-fix L1: **fill_sync + lifecycle reconcile only** (no forced SELL)

## FIX

| Item | Done |
|------|------|
| Detection `exit_pending_stuck.py` | yes |
| Health reason + SYSTEM_FAILURE escalate | yes |
| Data Trust INVALID | yes |
| Watchdog L1 fill-sync heal | yes |
| User-friendly EXIT reason | yes |
| Regression tests (5) | PASS |

## SAFETY

FORCED_REAL_ORDER=0 · REAL policy/threshold unchanged · LIVE_ARM_MANUAL_MUTATION=0 · KIWOOM_MUTATION=0

## Evidence scripts

- `.run/k_upbit_0225_no_trade_recurrence_audit.py`
- `.run/_uba1380_0225_detail_probe.json`
