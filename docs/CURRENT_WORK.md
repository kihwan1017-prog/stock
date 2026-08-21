# CURRENT_WORK

**역할:** 현재 진행 중인 작업만 기록한다.  
**최종 갱신:** 2026-08-21 (KIWOOM SETTLEMENT-AWARE DAILY LOSS EQUITY)

---

## Parallel policy

**TRACK U** / **TRACK K** / **SHARED** — U+K commit 혼합 금지

---

## Current Phase

| Track | STEP | Verdict | Next |
|-------|------|---------|------|
| **U** | UBA1380 AUTOTRADING + TELEGRAM INTEGRATED RUNNING CHECK | **`UPBIT_PORTFOLIO_RUNNING_TELEGRAM_RECOVERED`** | OBSERVE FIRST PORTFOLIO BUY SIGNAL AND FILL |
| **K** | KIWOOM DAILY LOSS SETTLEMENT-AWARE EQUITY | **`KIWOOM_SETTLEMENT_AWARE_DAILY_LOSS_IMPLEMENTED`** | NEXT KRX DAY BASELINE (V2) THEN RE-EVAL ENTRY; NO MID-DAY BASELINE REWRITE |
| **SHARED** | STRATEGY_CANDIDATE_MENU_FULL_AUDIT_AND_UX_CONSOLIDATION | **`STRATEGY_CANDIDATE_UX_CONSOLIDATION_COMPLETE`** | LEGACY page extract/cleanup |

Kiwoom Daily Loss: V2 settlement-aware equity (estimated asset → d2+stock fallback).
Today #715 baseline stays legacy V1; mid-day mixing 금지. Dry: adjusted loss ≈305,964 > 100,000 → ENTRY still BLOCKED.
Ops reload/migration apply는 별도 단계.

---

## Next Gate

**Exactly one:** APPLY MIGRATION + RELOAD ON NEXT KRX DAY (V2 BASELINE); DO NOT REWRITE TODAY BASELINE
