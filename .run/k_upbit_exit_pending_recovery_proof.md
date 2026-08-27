# UPBIT EXIT_PENDING Recovery Proof

**FINAL_VERDICT:** `UPBIT_EXIT_PENDING_REMOTE_WAIT_BLOCKED`  
**BASE:** `7af4508`  
**CURRENT_KST:** 2026-08-28T07:08:51+09:00

## ORDER #1926

| Field | Value |
|-------|--------|
| LOCAL_STATUS | ACCEPTED |
| REMOTE_STATUS | **wait** |
| ORD_TYPE | limit @ **299** |
| FILLED | 0 |
| REMAINING | 33.33333333 |
| LOCAL_REMOTE_DIVERGENCE | false |
| FINAL_STATUS | still ACCEPTED/wait (not terminal) |

## POSITION ADA

| Field | Value |
|-------|--------|
| SLOT | EXIT_PENDING (slot_id=4) |
| ENTRY | #1925 FILLED |
| EXIT ORDER | #1926 ACCEPTED 0-fill |
| BINDING | position_binding_id=60 |

## DETECTION (7af4508 proven)

- EXIT_PENDING_STUCK_DETECTED=**true**
- age ≈ 16742s ≫ 900s threshold
- classification=SYSTEM_FAILURE
- first_zero=EXIT / EXIT_PENDING_ZERO_FILL_STUCK
- AUTO_DETECT_PROVEN=true

## L1 FILL-SYNC

- SELF_HEAL_LEVEL=L1
- FILL_SYNC_ATTEMPTED=true
- RESULT=ok, remote state still `wait`, executed_volume=0
- NEW_ORDERS_DELTA=0
- NEW_SELL_CREATED=**false**

## TERMINAL RECOVERY

**BLOCKED** — remote WAIT protective SELL

- Policy: `BLOCKED_AUTO_SELL_WAIT` (startup reconciliation)
- CANCEL_ATTEMPTED=false
- NEW_SELL=0
- Chicken-and-egg: lease `restore_from_active_lease` → `successor validate failed` while open SELL wait remains; exit stack cannot manage fill without LIVE/ARM restore

## LEASE / STACK

| Field | Value |
|-------|--------|
| LEASE | ACTIVE until ~07:45 KST (reused, not recreated) |
| gates_ok | true (pre-restore) |
| restore | FAILED: LiveUnattendedError successor validate failed |
| LIVE/ARM after | OFF / OFF (no manual toggle) |
| Feed (watchdog L1) | REAL_FRESH (ADA subscribed) |
| Scanner | RUNNING (SHADOW) |
| Runtime/Runner/Worker/Exit | STOPPED |
| AUTO_TRADING_READY | false |

## DATA TRUST

- Current open window remains **INVALID** (window 33; evaluate prioritized FEED_DOWN/STACK while in-proc down)
- Historical VALID/DEGRADED rows **not rewritten** (audit preserved; raw not deleted)
- EXIT stuck now continuously re-detected as SYSTEM_FAILURE / health_reason EXIT_PENDING_ZERO_FILL_STUCK
- Shadow: entry_signal / trailing counts recorded in JSON (quarantine of past VALID windows not force-mutated)

## PIPELINE

- FIRST_ZERO=EXIT
- FIRST_ZERO_REASON=EXIT_PENDING_ZERO_FILL_STUCK
- User-facing: "매도 주문 체결 대기 이상" (UX order fix committed)

## RECURRENCE

| Item | Result |
|------|--------|
| SIGNATURE | EXIT_PENDING_ZERO_FILL_STUCK:ACCEPTED_SELL |
| AUTO_DETECT_PROVEN | true |
| AUTO_RECOVERY_PROVEN | false (remote WAIT blocks) |
| TELEGRAM_DEDUPE | existing edge policy (documented) |

## TESTS

`tests/test_exit_pending_stuck_and_no_trade_class.py` → **9 passed**

## SAFETY

NEW_REAL_BUY=0 · NEW_REAL_SELL=0 · FORCED=0 · LIVE_ARM_MANUAL=0 · DAILY=0 · KIWOOM=0

## OPERATOR NEXT (out of this STEP)

Remote limit SELL @299 is still open on Upbit. Full stack restore stays blocked until that order reaches **done/cancel** via market fill **or** an **explicit Admin recovery-cancel** (not auto this STEP).
