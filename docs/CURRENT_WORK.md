# CURRENT_WORK

**역할:** 현재 진행 중인 작업만 기록한다.  
**최종 갱신:** 2026-08-20 (UPBIT 24H AUTO TRADING OPERATION UX)

---

## Parallel policy

**TRACK U** / **TRACK K** / **SHARED** — U+K commit 혼합 금지

---

## Current Phase

| Track | STEP | Verdict | Next |
|-------|------|---------|------|
| **K** | KIWOOM STRATEGY 17579 DERIVED CLONE PROVENANCE ALIGNMENT | **`KIWOOM_STRATEGY_17579_DERIVED_PROVENANCE_ALIGNED_READY_FOR_PROMOTION_COMMIT`** | **KIWOOM STRATEGY 17579 PROMOTION COMMIT** |
| **U** | UPBIT 24H AUTO TRADING OPERATION UX | **`UPBIT_24H_OPS_UX_SIMPLIFIED`** (`5b40dd8`) | LIVE/ARM 승인 후 Unattended Enable → 운영 스택 시작 |

Runtime/Worker/Exit: Modal 확인만(문구 타이핑 제거). Backend confirmation phrase·safety gate 유지. 운영 스택 START = Preflight → LIVE/ARM/Activation gate → Worker → Exit → Runtime (FAIL CLOSED). LIVE ON / 24H Unattended / Kill Switch 해제는 강한 승인 유지.

---

## Next Gate

**Exactly one:** **KIWOOM STRATEGY 17579 PROMOTION COMMIT** (K) 또는 TRACK U 운영 스택 기동(승인 후)
