# WRK-20260829-010 — Daily Report Ops-Status Optimization

## Verdict

`DAILY_REPORT_OPS_STATUS_OPTIMIZED` — daily-report HTTP p50 **~3771ms → ~251ms** (target &lt;2s met).

## Root cause (measured, not guessed)

WRK-009 attributed residual cost to “ops-status aggregate”. In-process call-graph on this pass showed:

| Component | Before (p50 ms) | Notes |
|-----------|-----------------|-------|
| `build_cross_market_research_status` (UPBIT+KIWOOM) | ~2807 | **PRIMARY** — horizon metrics / PERCENTILE_CONT |
| `build_uba_operational_summary` UPBIT | ~205–1588 | SECONDARY — master_gate×2, open-order remote, get_or_create, health |
| `build_uba_operational_summary` KIWOOM | ~50 | light |

Daily Report UI only needs research **sample counts** (E0/E2/K0 VALID + NATURAL_OPPORTUNITY_POOL), not full research SoT.

## Changes (READ reporting path only)

1. **`projection="daily_report"`** on `build_uba_operational_summary` / `build_uba_daily_report_ops_projection`
   - Skip duplicate master_gate before health (health still runs gate once for UPBIT feed)
   - Skip open-order remote exposure, full-market `get_or_create`, scanner candidate payload, ghost duplicate
   - Attach `reliability.funnel` from health; KIWOOM funnel from health for post-close classification
2. **Full `/ops-status` path**: master_gate blockers+feed **deduped to 1 call** (was 2 before health)
3. **`build_cross_market_research_status_for_daily_report`**: sample-count slim projection; full research API unchanged
4. Daily report wires slim ops + slim research

## Equivalence

In-process: LIVE/ARM/feed/ready/health_state/no_trade + research pool/E0/E2/K0 VALID — all matched full vs slim.

Displayed daily-report fields (health, LIVE/ARM, orders/fills/positions, incidents, why-no-trade, funnel via reliability) preserved; research payload intentionally slim (schema tag `daily_report_slim_v1`).

## Performance

| Metric | Before (WRK-009 post) | After |
|--------|----------------------|-------|
| daily-report HTTP p50 | 3770.7 ms | **250.9 ms** |
| improvement | — | **~93.3%** |
| research in-process | ~2807 ms | **~3.9 ms** |
| ops UPBIT slim | ~205 ms full | **~129 ms** |

`TARGET_UNDER_2S=true`. `INDEX_ADDED=0`.

## Safety

No trading/risk/portfolio/strategy/order-execution logic change. No LIVE/ARM mutation. Backend restart ×1. Natural restore READ: LIVE ON, ARM ON, activation ACTIVE, feed REAL_FRESH, stack 4/4 RUNNING, ready true.

## Remaining

- Full Admin research status page still ~2.8s if opened (out of scope).
- First HTTP sample after cold restart can be ~2s; warm p50 ≪ 1s.
- Daily-report overall may still be ORANGE from open incidents / no-trade classification (not a perf regression).
