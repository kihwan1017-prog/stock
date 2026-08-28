# WRK-011 — Upbit 24h no-trade + ADA #1925 + DOS root cause

## Verdict

`ROOT_CAUSE_IDENTIFIED_UI_READ_FIXED_POLICY_CHANGE_REQUIRED_FOR_BUY`

## 24h facts (canonical)

Rolling 24h (UBA 1380): **BUY/SELL orders & fills = 0**.  
`NO_TRADE_24H_TRUE=true`.

Last BUY = ADA **#1925** FILLED (2026-08-28 02:25 KST).  
Last SELL = ADA **#1926** CANCELLED (MA_DEAD_CROSS @299, recovery-cancelled 07:30).

## ADA #1925 — why no sell

1. Entry FILLED @300, qty 33.33333333, slot OPEN, binding OPEN.
2. ~4 minutes later MA_DEAD_CROSS SELL **#1926** LIMIT 299 accepted but **never filled**.
3. Cancelled by `K1926_SAFE_RESOLUTION` (~5h later). Binding records `last_cancelled_exit_order_id=1926`.
4. **No later SELL** orders for ADA.
5. At investigation time **exit_monitor / stack STOPPED** (feed DISCONNECTED) — cannot evaluate new exits until restore.

**PRIMARY_NO_SELL_REASON:** unfilled MA exit then recovery cancel; no subsequent sell.  
**SECONDARY:** exit monitor not running after restart.

Protective Exit UI “ALWAYS ON” ≠ SL/TP/Trailing configured. Those remain `—`; MA strategy exit is separate.

Screen “대기 시간 24시간 8분” matched **opened_at** holding age, but UI always said “대기 시간” (wrong for OPEN). **Fixed:** OPEN → 보유 시간 / `age_kind=HOLDING` from `opened_at`.

PnL was blank in UI despite `trading.broker_position_snapshot` having qty/entry/current/pnl. **Fixed:** list_slots READ enrich + Ops panel wiring.

## DOS — why no buy

When technical PASS + signal emitted:

- BEGIN_ENTRY_ACCEPTED → **EXECUTOR_REJECTED `MAX_OPEN_POSITIONS_REACHED`**
- **FIRST_MISSING_STAGE = ORDER_CREATED**
- Later SIGNAL_EMIT_SUPPRESSED = **normal dedup** after those emits (not stale-only bug)

Root count: `broker_position_snapshot` qty>0 = **5** (ADA+BTC+ETH+DOGE+SKY) ≥ safety `max_open_positions=5`.  
AUTO OPEN bindings = **1** only.

→ Portfolio slot capacity free, but **account-wide safety max-open blocks BUY**.

**POLICY_CHANGE_REQUIRED** to raise max_open or count only STRATEGY_OWNED — **not auto-changed**.

Not WRK-004/007 regression (no 100k fallback / no dust reject; never reached order create).

Current DOS row: `reserved_amount_krw=null`, recommended≈27556. Screen “예약 10000” was not a live reserved DB field at probe (ACCOUNT_MAX_ORDER sizing pattern).

## UI fixes applied (no trading policy change)

- OPEN age label / `opened_at` anchor
- PnL/qty/entry/current from broker snapshot READ
- why_still_holding_ko
- MAX_OPEN_POSITIONS_REACHED Korean explanation

## Remaining

- Approve policy decision for max_open vs manual holdings
- Unattended stack restore did not recover within 60s after this restart (LIVE/ARM left ON, no manual mutation)
