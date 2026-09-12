# PARALLEL TRACK PRECHECK SUMMARY — U-TERM-A0 + K-G0

**Date:** 2026-08-16 · **HEAD:** `3bbf0cd` · **MODE:** READ-ONLY  
**Policy:** TRACK U / TRACK K / SHARED · no mixed production commit · SHARED WRITE serial

| Track | Verdict | Next STEP |
|-------|---------|-----------|
| **U** | `TERMINATION_IMPLEMENTATION_READY_TARGET_ONLY` | `SHADOW LONG_ACTIVE TERMINATION IMPLEMENTATION (TARGET_ONLY)` |
| **K** | `KIWOOM_LIVE_BLOCKED` | `KIWOOM_P0-2_LIVE_POSITION_WRITE` |

---

## Collision audit

### U_ONLY_FILES
- `src/stock_platform/operation/upbit_opportunity_shadow/evaluator.py`
- `src/stock_platform/operation/upbit_opportunity_shadow/termination.py` (planned)
- `tests/test_upbit_shadow_long_active_termination.py` (planned)
- Upbit news/shadow/scanner paths (background)

### K_ONLY_FILES
- `src/stock_platform/broker/kiwoom/**`
- `src/stock_platform/broker/live_fill_ledger_service.py`
- `src/stock_platform/broker/recovery_adapters/kiwoom.py`
- Kiwoom WS bridge / account sync

### SHARED_FILES
- `order/` TradingOrder · Outbox worker/resolver
- `risk_engine/` · `trading/runtime_control_gates.py`
- `trading/user_account_service.py` · UBA · Auth
- Scheduler common · `api/v1/admin_live_ops_readiness.py` (if generalized)

### COLLISION_FILES
- `api/v1/admin_live_ops_readiness.py` (U-centric today; K extension = conflict if simultaneous)
- `realtime/risk_integrated_order_executor.py` (P0-1 SHARED)
- Outbox/TradingOrder entities (both consume; schema write = SHARED STEP)

**PARALLEL_WRITE_SAFE = YES_WITH_BOUNDARIES**

Boundaries:
1. U termination vs K P0-2 Position WRITE — **SAFE_PARALLEL** (disjoint files)
2. Either track needing Outbox/TradingOrder/Risk/UBA schema — **HOLD** → SHARED STEP
3. One commit = one track (or SHARED-only)

---

## Runtime snapshot

| Metric | Value |
|--------|-------|
| TradingOrder | 241 |
| Outbox | 52 |
| Upbit LIVE | false |
| Kiwoom LIVE | false |
| outbox_scheduler_running | false |
| News MATCHED completed | 3 |
| News NO_NEWS completed / active | 30 / 10 |
| News EXCLUDED | 5 |
| News milestone | ACCUMULATING |

production mutation **0** · DB mutation **0** · commit **NO** · push **NO**
