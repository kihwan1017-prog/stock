# WRK-019 H2/H3 Frozen Forward-Shadow

**WORK_ID:** `WRK-20260829-019-UPBIT-H2-H3-FROZEN-FORWARD-SHADOW`  
**PARENT:** `WRK-20260829-018-UPBIT-POSITIVE-OUTCOME-FEATURE-DISCOVERY`  
**FINAL_VERDICT:** `H2_H3_FORWARD_SHADOW_INFRA_READY`

## Frozen

| | Rule Hash | Boundaries |
|--|-----------|------------|
| H2 | `0cfb35c4590f404b` | dist_ma20≤-0.20964360587002462, ret_1m≤-0.09191176470588758 |
| H3 | `80893dfac2d5b2ea` | ret_1m≤-0.09191176470588758, dist_low≤0.06131207847945852 |

- QUANTILES_RECALCULATED=false
- FORWARD_VALIDATION_STARTED_AT=2026-08-29T01:00:00+00:00
- HISTORICAL_DATA_REUSED_AS_FORWARD=false
- Primary horizon=60m (WRK-018)

## Storage / Jobs

- Table: `operation.upbit_h2_h3_forward_shadow`
- Migration: `h2h3fs1a2b3c4d` applied
- Scheduler: `upbit_h2_h3_forward_shadow` (interval ~180s; wires on process restart)
- Outcome: 30/60/120 catch-up on restart
- Dedupe: 15m sample grid + unique(strategy,symbol,evaluated_at,rule_hash)

## Forward sample (infra)

- H2 / H3 readiness: `NOT_ENOUGH_FORWARD_DATA` (N≪300 — expected)
- Infra seed rows exist; natural accumulation continues after STARTED_AT
- Historical WRK-018 bars are **not** counted as forward promotion sample

## Safety

- SHADOW_ONLY=true
- StrategySignal published=0
- REAL orders by shadow=0
- USER_APPROVAL_REQUIRED=true (no auto promotion)
- REAL_POLICY_CHANGED=false

## Tests

- pytest: `tests/test_upbit_h2_h3_forward_shadow.py` PASS

## Remaining

Forward N accumulates automatically. Do not force next development stage.
