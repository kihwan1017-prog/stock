# UPBIT 20:39+ NO-TRADE ROOT + DATA TRUST

**FINAL_VERDICT:** UPBIT_RECURRING_FAILURE_ROOT_FIXED_DATA_TRUST_ENABLED

**CURRENT_KST:** 2026-08-27T23:28:04.297769+09:00

## CURRENT INCIDENT

| Field | Value |
|------|------|
| LAST_REAL_BEFORE | 1904 SELL KRW-RE 20:38:58 KST |
| FIRST_POST_FIX | 1905 BUY + 1906 SELL KRW-DRV ~23:23 KST |
| MINUTES_NO_TRADE | 164.1 |
| FIRST_ZERO_NOW | ENTRY_SIGNAL / SHORT_MA_NOT_ABOVE_LONG_MA |
| PRIMARY_ROOT | STALE_PRE_RESTORE_WAITING false-positive on ENTRY_PENDING persist |
| CLASSIFICATION_THEN | SYSTEM_FAILURE (NEW_FAILURE_MODE) |
| CLASSIFICATION_NOW | NORMAL_NO_SIGNAL |

## WHY REPEATED

Watchdog saw healthy stack and inflated ENTRY_PASS funnel; did not heal persist-gate STALE when waiting_at=None after egin_entry.

## FIX

- Skip restore-epoch STALE when slot is no longer WAITING (NOT_WAITING_SLOT)
- waiting is None blocks only while outage_active
- Force WAITING revalidation after restore
- Funnel ENTRY_* counts E0 only
- Data Trust windows + quarantine columns + incident ledger (dq1a2b3c4d5e)

## DATA TRUST

- Window#1 DEGRADED (WAITING_SLOT_STARVATION) closed
- Window#2 VALID (NORMAL_NO_SIGNAL) open
- RAW_DATA_DELETED=false
- Shadow promotion metrics: VALID_ONLY

## DEPLOY

- Migration dq1a2b3c4d5e
- Backend restart **1** (PROD, reload=false)
- Natural proof: orders 1905/1906 FILLED (not forced)

## SAFETY

FORCED_REAL_ORDER=0 · REAL policy unchanged · KIWOOM_MUTATION=0 · CAN_SAFELY_CONTINUE=true
