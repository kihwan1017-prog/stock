# WRK-018 Positive Outcome Feature Discovery

**Classification:** `B_PROMISING_FEATURES_NEED_MORE_DATA`
**Rows:** 90932 · Discovery/Val/Test = 54559/18186/18187

## Winner characteristics
- dist_ma20_pct: winners mean -0.0367 vs losers 0.08 (d=-0.172)
- ret_1m: winners mean -0.025 vs losers 0.0339 (d=-0.154)
- ret_5m: winners mean -0.0281 vs losers 0.0679 (d=-0.149)
- dist_low_20_pct: winners mean 0.7618 vs losers 0.8984 (d=-0.14)
- ret_15m: winners mean -0.0415 vs losers 0.1063 (d=-0.138)

## Loser characteristics
- dist_ma20_pct: losers elevated mean 0.08 vs winners -0.0367 (d=-0.172)
- ret_1m: losers elevated mean 0.0339 vs winners -0.025 (d=-0.154)
- ret_5m: losers elevated mean 0.0679 vs winners -0.0281 (d=-0.149)
- dist_low_20_pct: losers elevated mean 0.8984 vs winners 0.7618 (d=-0.14)
- ret_15m: losers elevated mean 0.1063 vs winners -0.0415 (d=-0.138)

## Feature edge map (top)

| Feature | Bin | N | Net30 | Net60 | Net120 | Win% | PF | Stability |
|---|---|---:|---:|---:|---:|---:|---:|---|
| dist_ma20_pct | Q1 | 10913 | -55700.3 | -33951.2 | -35226.5 | 46.1 | 0.944 | STABLE |
| dist_ma20_pct | Q2 | 10912 | -140823.1 | -139084.2 | -146113.0 | 38.5 | 0.655 | STABLE |
| dist_ma20_pct | Q3 | 10911 | -159971.7 | -166904.2 | -184330.8 | 34.2 | 0.546 | STABLE |
| dist_ma20_pct | Q4 | 10912 | -192925.9 | -199287.7 | -222115.3 | 34.2 | 0.548 | STABLE |
| dist_ma20_pct | Q5 | 10911 | -269731.6 | -306430.4 | -309751.8 | 34.8 | 0.608 | STABLE |
| ret_1m | Q1 | 10925 | -73651.7 | -65350.7 | -79194.7 | 44.5 | 0.889 | STABLE |
| ret_1m | Q2 | 27001 | -423120.7 | -436181.5 | -454829.6 | 36.2 | 0.615 | STABLE |
| ret_1m | Q4 | 5725 | -90270.2 | -97074.0 | -114267.1 | 32.1 | 0.435 | STABLE |
| ret_1m | Q5 | 10908 | -232110.0 | -247051.5 | -249246.0 | 37.1 | 0.648 | STABLE |
| ret_5m | Q1 | 10914 | -90357.0 | -69480.6 | -83536.4 | 44.9 | 0.885 | STABLE |
| ret_5m | Q2 | 22467 | -314032.0 | -309479.2 | -333235.7 | 36.8 | 0.649 | STABLE |
| ret_5m | Q4 | 10266 | -163590.6 | -186778.7 | -198411.2 | 33.4 | 0.479 | STABLE |
| ret_5m | Q5 | 10912 | -251173.1 | -279919.2 | -282354.1 | 35.7 | 0.627 | STABLE |
| dist_low_20_pct | Q1 | 10914 | -65967.3 | -55715.6 | -38416.5 | 41.1 | 0.855 | STABLE |
| dist_low_20_pct | Q2 | 10910 | -153165.4 | -151761.0 | -175546.7 | 35.3 | 0.535 | STABLE |
| dist_low_20_pct | Q3 | 10917 | -167519.2 | -177689.7 | -200302.3 | 36.5 | 0.594 | STABLE |
| dist_low_20_pct | Q4 | 10906 | -185715.9 | -202008.9 | -245414.2 | 37.3 | 0.643 | STABLE |
| dist_low_20_pct | Q5 | 10912 | -246784.8 | -258482.5 | -237857.7 | 37.8 | 0.707 | STABLE |
| ret_15m | Q1 | 10914 | -60594.0 | -41090.3 | -21963.9 | 45.4 | 0.932 | STABLE |
| ret_15m | Q2 | 10910 | -160990.7 | -164486.2 | -206836.9 | 37.6 | 0.585 | STABLE |
| ret_15m | Q3 | 10912 | -160445.0 | -156510.8 | -159256.1 | 35.5 | 0.633 | STABLE |
| ret_15m | Q4 | 10928 | -175372.0 | -190174.4 | -202023.7 | 34.1 | 0.528 | STABLE |
| ret_15m | Q5 | 10895 | -261751.0 | -293396.0 | -307456.8 | 35.4 | 0.617 | STABLE |
| ret_30m | Q1 | 10928 | -89986.0 | -73782.3 | -59419.6 | 44.6 | 0.884 | STABLE |
| ret_30m | Q2 | 10896 | -149590.7 | -152276.5 | -175786.2 | 37.9 | 0.618 | STABLE |

## Hypotheses
### IX_dist_ma20_pct_2_dist_low_20_pct_5
- Rule features: ['dist_ma20_pct', 'dist_low_20_pct']
- Why: Discovery interaction avg60=1.39 n=509
- VAL: n=177 pf=1.026 net=392.9
- TEST: n=236 pf=0.853 net=-2989.7 promo=False
### IX_dist_ma20_pct_1_ret_1m_1
- Rule features: ['dist_ma20_pct', 'ret_1m']
- Why: Discovery interaction avg60=1.31 n=5024
- VAL: n=1592 pf=1.2 net=17740.2
- TEST: n=2018 pf=1.001 net=199.8 promo=False
### IX_ret_1m_1_dist_low_20_pct_1
- Rule features: ['ret_1m', 'dist_low_20_pct']
- Why: Discovery interaction avg60=1.05 n=4126
- VAL: n=1489 pf=1.11 net=6281.1
- TEST: n=1284 pf=1.025 net=1568.9 promo=False
### CALM_BREADTH_LIQUID
- Rule features: ['breadth', 'rv_15m', 'dist_high_20_pct', 'log_tv']
- Why: High breadth + low short vol + not extended to highs + liquidity
- VAL: n=135 pf=0.404 net=-2491.8
- TEST: not promoted from validation
### BTC_UP_LOCAL_LOW_VOLUME_WAKE
- Rule features: ['dist_low_20_pct', 'btc_ret_60m', 'vol_accel', 'ret_5m']
- Why: BTC up + price near 20m low + volume waking + 5m green (not frozen momentum)
- VAL: n=293 pf=0.266 net=-4353.2
- TEST: not promoted from validation

## BEST: `None`

**B_PROMISING_FEATURES_NEED_MORE_DATA**

Collect more OOS days; do not retune thresholds on TEST.

`REAL_POLICY_CHANGED=false`

STOP.