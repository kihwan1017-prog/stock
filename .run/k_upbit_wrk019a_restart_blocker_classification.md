# WRK-019B Restart Safety Blocker Classification

**WORK_ID:** WRK-20260829-019B-UPBIT-RESTART-SAFETY-BLOCKER-CLASSIFICATION  
**PARENT:** WRK-20260829-019A-UPBIT-H2-H3-FORWARD-SHADOW-RUNTIME-ACTIVATION  
**BASE_HEAD:** 4395f93b7e137f4f20201cfb6ff6340f430bd3b5  
**FINAL_CASE:** SAFE_NOW  
**CLASSIFICATION:** RESTART_BLOCKER_PARTIALLY_FALSE_POSITIVE  
**NEXT_ACTION:** RUN_WRK019A_RESTART_ACTIVATION_ONLY

## History
- WRK-019 COMPLETED (infra ready)
- WRK-019A COMPLETED (restart skipped)
- WRK-014 evidence exists; no DB work_history row (out of scope)

## HTTP Runtime
LIVE=ON ARM=ON LEASE=ACTIVE STACK=4/4 FEED=REAL_FRESH AUTO_TRADING_READY=true

## Remote Open Orders
TOTAL=5 AUTO=0 MANUAL=5 UNKNOWN=0 RESTART_SENSITIVE=false

All 5 are Upbit wait limit **ask** orders, **unmapped** to local TradingOrder → platform class MANUAL.
Symbols: KRW-BTC×2, KRW-SKY, KRW-DOGE, KRW-ETH.
No StrategySignal / EntryExecutionTrace / ExitIntent / Recovery link.

**Restart impact:** MANUAL unmapped remotes are outside AUTO cancel/recovery; restart does not create/cancel them; wait-watch reloads; AUTO open-order gate uses auto_open_count only.

## ENTRY_PENDING
COUNT_NOW=0 FUNNEL_NOW=0  
CLASSIFICATION=NONE_NOW_PRIOR_LIKELY_RESOLVED  
WRK-019A 당시 funnel ENTRY_PENDING=1 은 **현재 슬롯에 없음** (자연 해소 또는 일시 상태). STALE row 없음.

Slots now: ADA OPEN, NEAR/DOS/ORBS WAITING_SIGNAL, TRUMP COOLDOWN.

## Active lifecycles
CANCEL=NONE RECOVERY=NONE EXIT_INTENT=NONE ORDER_SUBMISSION=NONE EXECUTOR=NONE

## Restart semantics
1. MANUAL remote open ≠ 무조건 restart unsafe (AUTO gate 비포함)
2. AUTO ENTRY_PENDING with live broker order ⇒ unsafe
3. Unattended restore: LIVE/ARM/Activation from lease; MANUAL remotes untouched
4. Must not restart: AUTO in-flight submit/cancel/exit-intent

WRK-019A precheck was **over-conservative** (PARTIALLY_FALSE_POSITIVE).

## H2/H3
PROCESS_REGISTERED=false SCHEDULER_ENABLED=false LAST_RUN=null  
VALID_FORWARD_SAMPLES=0 BOOTSTRAP_MANUAL=2 (shadow_id 1/3 synthetic)

## Safety
CODE_CHANGED=false RESTART_COUNT=0 LIVE_ARM_MUTATED=false ORDERS_CREATED=0 ORDERS_CANCELLED=0

## Decision
SAFE_NOW — do **not** restart in this WRK; next = RUN_WRK019A_RESTART_ACTIVATION_ONLY
