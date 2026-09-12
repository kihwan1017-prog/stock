# KIWOOM P0-2 POSITION WRITE — IMPLEMENTATION

**STEP:** K-B · **MODE:** K_ONLY wiring + tests · **Date:** 2026-08-16  
**HEAD baseline:** `3bbf0cd` · **Verdict:** **`KIWOOM_P0_2_READY_WITH_LIMITATIONS`**  
**JSON:** [KIWOOM_P0_2_POSITION_WRITE_IMPL.json](KIWOOM_P0_2_POSITION_WRITE_IMPL.json)

---

## Scope

| Field | Value |
|-------|-------|
| **P0_2_SCOPE_CONFIRMED** | **YES** |
| LIVE Position model | `trading.broker_position_snapshot` + `broker_account_snapshot` (FILL_DRIVEN) |
| SHARED write | **NO** (`LiveFillLedgerService` / `ExecutionSyncService` / TradingOrder / Outbox **미수정**) |
| Root cause | Kiwoom WS/Mock sync 후 ledger silent 실패·Recovery Position 미기록 |

## Implemented (K_ONLY)

1. `broker/kiwoom/fill_position_write.py` — idempotent ledger 재적용 wrapper  
2. `ws_manager.py` / `mock_gateway.py` — sync 후 `ensure_kiwoom_position_after_sync`  
3. `recovery.py` — 증분 fill → FILL_DRIVEN position (`RECOVERY:{oid}:{qty}` id)  
4. `tests/test_kiwoom_p0_2_position_write.py` — BUY/SELL/dup/partial/UBA/recovery idempotency  

## Readiness (unchanged except Position WRITE)

| Key | Value |
|-----|-------|
| **KIWOOM_POSITION_WRITE_READY** | **YES** (with limitations) |
| credential | still **blocker** |
| preflight | still **blocker** |
| paper | **NO** |
| LIVE | **NO** — not promoted |

## Limitations

- `ExecutionSyncService` still swallows ledger exceptions (SHARED 미수정) — Kiwoom ensure가 보완  
- Account sync wipe vs FILL_DRIVEN 보존 = SHARED 후속  
- 실 Broker/LIVE 주문 미실행  

## Next K STEP

**KIWOOM_CREDENTIAL_UBA_ALIGNMENT**
