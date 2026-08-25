# UPBIT Portfolio Daily Entry Limit — KST Semantics Fix

## FINAL_VERDICT
**UPBIT_DAILY_ENTRY_LIMIT_KST_SEMANTICS_FIXED**

## ROOT_CAUSE
- Semantics: D_REAL_BUY_ORDER — was wrongly B_live_candidate_selection
- BEFORE count: `upbit_live_candidate_selection PORTFOLIO_SLOT_% (UTC day, includes SUPERSEDED)`
- AFTER count: `trading_order REAL AUTO BUY distinct (KST day)`
- TIMEZONE: UTC calendar day → Asia/Seoul calendar day

## 2026-08-24 replay
| Metric | Value |
|--------|------:|
| ACTUAL_REAL_BUY_COUNT | 5 |
| OLD_DAILY_COUNT (selection UTC) | 10 |
| NEW_CANONICAL_COUNT (AUTO BUY KST) | 5 |
| SUPERSEDED_COUNTED_BEFORE | 3 |
| SUPERSEDED_COUNTED_AFTER | 0 |

## CURRENT_KST_DAY
```json
{
  "user_broker_account_id": 1380,
  "timezone": "Asia/Seoul",
  "day_start_utc": "2026-08-24T15:00:00+00:00",
  "entry_count": 0,
  "entry_limit": 10,
  "remaining": 10,
  "blocking": false,
  "count_source": "REAL_AUTO_BUY_ORDER_DISTINCT",
  "excludes": [
    "SUPERSEDED_SELECTION",
    "SELECTED_WITHOUT_BUY",
    "SLOT_REPLACEMENT",
    "SELL",
    "SHADOW",
    "PAPER",
    "MANUAL",
    "RETIRED_UNSUBMITTED"
  ],
  "label_ko": "실제 자동매매 신규 진입 기준. 후보 교체/Shadow는 포함하지 않습니다."
}
```

DAILY_LIMIT_NOW_BLOCKING = **False**

## ENTRY_LIMIT_VALUE_CHANGED
NO (still 10)
