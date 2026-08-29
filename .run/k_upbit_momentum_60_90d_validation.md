# WRK-017 Momentum 60/90d Edge Validation

**Classification:** `C_MOMENTUM_EDGE_REJECTED`
**Achieved days:** 90.0 (target 90 / min 60)
**Selected OOS horizon:** 120m
**Signals:** 3405 · symbols=16
**Research DB:** `.run\research_candles\upbit_minute_research.sqlite` (prod candles not written)

## Frozen rule
```
{
  "source": "WRK-016 families.evaluate_families MOMENTUM",
  "ret15_min_pct": 0.25,
  "ret60_min_pct": 0.4,
  "ma5_slope_min_pct": 0.0,
  "volume_surge_min": 1.0,
  "ret15_max_pct": 3.0,
  "require_ma5_gt_ma20": true,
  "score": "ret60 + ret15*0.5 + surge*0.2"
}
```

## TEST (selected horizon)
- N=681 PF=0.903 NET=-7914.8 MDD=22470.2
- slip sensitivity: {"1.0bps": {"n": 681, "opportunities_day": 37.83, "trades_day": 37.83, "win_rate": 42.3, "pf": 0.919, "avg_net_trade": -9.62, "median_net_trade": -35.58, "total_net": -6552.8, "mdd": 21636.2, "best_regime": null, "confidence": "MEDIUM_HIGH"}, "2.0bps": {"n": 681, "opportunities_day": 37.83, "trades_day": 37.83, "win_rate": 42.1, "pf": 0.903, "avg_net_trade": -11.62, "median_net_trade": -37.58, "total_net": -7914.8, "mdd": 22470.2, "best_regime": null, "confidence": "MEDIUM_HIGH"}, "5.0bps": {"n": 681, "opportunities_day": 37.83, "trades_day": 37.83, "win_rate": 41.3, "pf": 0.857, "avg_net_trade": -17.62, "median_net_trade": -43.58, "total_net": -12000.8, "mdd": 24972.2, "best_regime": null, "confidence": "MEDIUM_HIGH"}}

## Horizon full-sample PF/NET
- 30m: n=3405 pf=0.664 net=-66197.1 tpd=37.83
- 60m: n=3405 pf=0.741 net=-68115.2 tpd=37.83
- 90m: n=3405 pf=0.783 net=-67303.0 tpd=37.83
- 120m: n=3405 pf=0.808 net=-68536.0 tpd=37.83
- 180m: n=3405 pf=0.816 net=-76470.4 tpd=37.83

## Recommendation: **C_MOMENTUM_EDGE_REJECTED**

No REAL apply. Frozen Momentum rejected on 90d OOS. Do not apply REAL. Next: new entry family research (not threshold retune) or longer multi-family EV with stricter filters.

`REAL_POLICY_CHANGED=false`

PROD market.candle_minute untouched (min still 2026-08-07).

STOP.