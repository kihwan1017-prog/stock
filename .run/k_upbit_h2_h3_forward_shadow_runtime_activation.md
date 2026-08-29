# WRK-019A — H2/H3 Forward Shadow Runtime Activation

**WORK_ID:** `WRK-20260829-019A-UPBIT-H2-H3-FORWARD-SHADOW-RUNTIME-ACTIVATION`  
**PARENT:** `WRK-20260829-019-UPBIT-H2-H3-FROZEN-FORWARD-SHADOW`  
**FINAL_VERDICT:** `RESTART_SKIPPED_ACTIVE_ORDER_SAFETY`

## History

| Work | DB | Verdict |
|------|----|---------|
| WRK-019 | COMPLETED | H2_H3_FORWARD_SHADOW_INFRA_READY (`aa00943`) |
| WRK-018 | **missing row** | parent id only on WRK-019 |

코드 재감사/재구현 없음.

## Precheck (HTTP ops-status SoT)

- LIVE=ON · ARM=ON · LEASE=ACTIVE · STACK=4/4 · FEED=REAL_FRESH · AUTO_TRADING_READY=true
- Remote open orders: **5 manual** (`UPBIT_REST_WAIT_WATCH`, FRESH)
- Funnel ENTRY_PENDING=**1** (stuck=0) · open_positions=1
- Local DB non-terminal trading_order: **0**
- Forced cancel/cleanup: **금지 → 수행 안 함**

**RESTART_SAFE=false** → STOP.

## Wiring

- Source: `evaluator_scheduler.configure` → `UpbitH2H3ForwardShadowScheduler` **등록됨**
- Process after restart: **N/A (restart skipped)**
- Wiring fix: **none**

## Restart

- PERFORMED=false
- UNATTENDED_RESTORE=false
- MANUAL_LIVE_ARM_MUTATION=false

## Natural proof

- EVALUATOR_RAN=false (현재 process에 job 미로드 상태 유지)
- Forced sample / historical backfill: false

## Existing rows

| id | strategy | source | promotion |
|----|----------|--------|-----------|
| 1 | H2 KRW-BTC | BOOTSTRAP_MANUAL (synthetic close=100) | **invalid** |
| 3 | H3 KRW-ETH | BOOTSTRAP_MANUAL (synthetic close=200) | **invalid** |

DB row 삭제/rewrite 없음 — evidence로 provenance만 기록.

## Safety

REAL_POLICY_CHANGED=false · H2/H3 StrategySignal/Executor/Order = 0

## Status

**FORWARD_SHADOW_AUTOMATIC_COLLECTION=NOT_READY**

## Remaining

원격 open order / ENTRY_PENDING 해소 후 WRK-019A restart-only 재시도.  
새 전략 개발 금지.
