# Market Data Menu + User Market Analysis

**FINAL_VERDICT:** `MARKET_DATA_MENU_AND_USER_MARKET_ANALYSIS_COMPLETE`

## Summary

- Left menu **시장 데이터** → `/admin/market-data` (전략·분석, 시장 분석 다음)
- Market-data tabs include **일자별 수집현황** (필터 + 누락 Drawer)
- `/admin/market-analysis` rebuilt as user Summary dashboard (projection only, NOT trading gate)
- Dev links moved under Collapse **상세 분석 / 운영 도구**
- Friendly reason mapping (main UI); raw codes only in detail collapse

## Verify

| Check | Result |
|-------|--------|
| typecheck | PASS |
| focused vitest (menu/analysis/daily) | 18 passed |
| check:antd-compat | PASS |
| pytest friendly_reason | PASS |
| API summary/daily-status/reason | 200 |
| Browser market-analysis | PASS |
| Browser market-data + daily tab | PASS |
| Console errors/warnings | 0 / 0 |
| HTTP 404/500 | 0 / 0 |

## Safety

- REAL_ORDER_MUTATION=0
- REAL_POLICY_MUTATION=0
- LIVE_ARM_MUTATION=0
- PROCESS_VERSION_CHANGED=false
- Backend restart ×1 (route load only)

## Evidence

- `.run/k_market_data_menu_user_market_analysis.json`
- `.run/k_market_data_menu_user_market_analysis_browser.json`
- `.run/_market_analysis_api_smoke.json`
