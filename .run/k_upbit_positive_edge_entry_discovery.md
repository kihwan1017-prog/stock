# WRK-016 Upbit Positive-Edge Entry Discovery

**Verdict:** `UPBIT_POSITIVE_EDGE_ENTRY_DISCOVERY_COMPLETE`
**Classification:** `B_PROMISING_BUT_MORE_DATA_REQUIRED`
**Window:** 21d_available (21.0d) · opps=5005 · symbols=28

## Family comparison (cost-aware, primary horizon 30m)

| Strategy | N | Opp/day | Win% | PF | Avg net | Total net | MDD | Best regime | Conf |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| M0_CURRENT | 1333 | 63.42 | 41.3 | 0.849 | -8.37 | -11154.0 | 14463.2 | SIDEWAYS | MEDIUM_HIGH |
| MOMENTUM | 1189 | 56.57 | 44.4 | 1.029 | 1.59 | 1888.2 | 5039.7 | SIDEWAYS | MEDIUM_HIGH |
| BREAKOUT | 571 | 27.16 | 38.7 | 0.832 | -9.4 | -5368.0 | 5409.3 | BEAR_TREND | MEDIUM_HIGH |
| VOLUME_SURGE | 1091 | 51.9 | 39.7 | 0.826 | -9.83 | -10728.7 | 12117.6 | SIDEWAYS | MEDIUM_HIGH |
| PULLBACK | 33 | 1.57 | 30.3 | 0.588 | -38.31 | -1264.1 | 2222.5 | SIDEWAYS | LOW |
| MEAN_REVERSION | 788 | 37.49 | 49.4 | 0.984 | -0.87 | -681.8 | 3873.1 | BULL_TREND | MEDIUM_HIGH |
| BEST_MULTI_STRATEGY | 0 | 0.0 | None | None | None | 0.0 | 0.0 | None | VERY_LOW |

## Walk-forward best (by VAL PF): `MEAN_REVERSION`
- TEST n=158 PF=0.715 net=-2685.2

Near-miss: **MOMENTUM** full-sample PF≈1.03 / net≈+1888 (fails PF≥1.1 promotion; TEST not cleared).

## Recommendation: **B_PROMISING_BUT_MORE_DATA_REQUIRED**

No family cleared cost-aware TEST promotion bar; do not force trades/day target

Next: Extend candle history to 60–90d and re-run families; do not relax M0 thresholds or apply AUTO_ONLY until TEST edge>0

`REAL_POLICY_CHANGED=false`

STOP.