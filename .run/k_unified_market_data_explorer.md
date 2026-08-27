# Unified Market Data Explorer

**FINAL_VERDICT:** UNIFIED_MARKET_DATA_EXPLORER_COMPLETE

## Root Cause
- UPBIT: upbit_krw_daily_sync는 JobRegistry에만 등록되어 있고 AutomaticScheduler cron에 없음. 2026-08-01 이후 batch 실행 없음. 자동매매 관심 ~11종목만 per-symbol resume 동기화(2026-08-18), 나머지 ~269종목은 2026-07-31에서 정지.
- KIWOOM: KiwoomDailyBatchSyncService가 수동 API만 있었고 scheduler 미등록이었음. 이번 STEP에서 JobRegistry + AutomaticScheduler cron 등록. 2026-08-18 이후 자동 batch 없어 STALE.

## Scheduler
- UPBIT registered: True
- KIWOOM registered: True

## Explorer
- Route: `/admin/market-data`