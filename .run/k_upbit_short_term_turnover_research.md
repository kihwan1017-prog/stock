# WRK-015 Upbit Short-Term Turnover Research

**Verdict:** `UPBIT_SHORT_TERM_TURNOVER_RESEARCH_COMPLETE`
**Window:** 30d · fills=64 · quality=ADEQUATE_FILLS_LIMITED_TRACE_SPAN

## Bottlenecks
1. `SHORT_MA_NOT_ABOVE_LONG_MA`
2. `MA_SEPARATION_TOO_SMALL`
3. `NO_CANDIDATE_SNAPSHOT`
4. `VOLUME_SURGE_TOO_LOW`
5. `SIGNAL_EMIT_SUPPRESSED`

## Comparison

| Profile | Trades/day | Zero% | Med hold(m) | Win% | PF | Gross | Fees | Slip | Net | MDD |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BASELINE | 2.13 | 73.3 | 31.5 | 25.0 | 0.2 | -2653.5 | 618.7 | 256.0 | -3528.2 | 3745.0 |
| CONSERVATIVE_TURNOVER | 2.77 | 73.3 | 14.0 | 29.7 | 0.31 | -1672.5 | 805.2 | 332.8 | -2810.4 | 3038.1 |
| BALANCED_TURNOVER | 2.77 | 73.3 | 12.0 | 26.6 | 0.31 | -1634.6 | 805.2 | 332.8 | -2772.6 | 2954.8 |
| AGGRESSIVE_TURNOVER | 2.77 | 73.3 | 6.3 | 31.2 | 0.28 | -1060.4 | 805.5 | 332.8 | -2198.7 | 2320.8 |

## Recommended: **BALANCED_TURNOVER**

- TP=1.2 SL=0.8 Trail=0.6 Time≤120m + MA fallback
- Slot proposal: AUTO_ONLY (not applied)
- Expected trades/day≈2.77 net≈-2772.6 MDD≈2954.8
- Confidence: LOW_MEDIUM_SAMPLE_UNPROFITABLE

`REAL_POLICY_CHANGED=false`

STOP.