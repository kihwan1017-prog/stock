# Autotrading Daily Report UI + Route Fix

**Verdict:** UI/OBSERVABILITY ONLY — REAL trading logic unchanged  
**Base:** 9fcf6da

## Route fix

| Item | Value |
|------|-------|
| ROOT_CAUSE | `/admin/autotrading/upbit` was redirect-only; canonical workspace not rendered at menu URL |
| Fix | Render `UpbitAutotradingSettingsWorkspace` at `/admin/autotrading/upbit`; legacy `/admin/upbit/autotrading` redirects |
| KIWOOM | `/admin/autotrading/kiwoom` unchanged (already implemented) |
| REPORT | NEW `/admin/autotrading/report` |

## Daily report

- **API:** `GET /api/v1/admin/autotrading/daily-report`
- **UI:** Admin → 자동매매 → 일일 운영보고
- **Telegram:** 23:30 KST, dedupe `DAILY_TRADING_REPORT:{date}`, fail-open
- **Content:** UPBIT/KIWOOM summary, why-no-trade, incidents, pipeline, shadow research

## Change History

- `ADMIN_AUTOTRADING_ROUTE_FIX`
- `AUTOTRADING_DAILY_OPERATION_REPORT_UI`

## Safety

REAL logic / strategy / MA / portfolio / risk / LIVE-ARM **unchanged**.
