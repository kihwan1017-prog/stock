# Mobile Read-Only PWA V1

FINAL_VERDICT: **MOBILE_READ_ONLY_PWA_COMPLETE**

## Route / PWA

- ROUTE: `/mobile` (+ `/orders` `/positions` `/alerts`)
- PWA_START_URL: `/mobile`
- MANIFEST: `/manifest.webmanifest`
- SERVICE_WORKER: `/sw-mobile.js` (API = network-first, no stale-as-fresh)

## API

- `GET /api/v1/mobile/overview` (admin, read-only)
- `GET /api/v1/mobile/health`
- MOBILE_WRITE_API_COUNT: **0**
- OVERVIEW P50 ≈ 12ms (warm) · P95 cold can be ~1s (UBA ops aggregate)

## UI

System · UPBIT · KIWOOM · Today PnL · Positions · Orders · Alerts · AI research  
Bottom nav: 홈 / 주문 / 포지션 / 알림  
WRITE controls: none

## Verify

- Auth browser 390×844 / 412×915: PASS, overflow=0
- Console ERROR/WARN/404/500/AntD/hydration: 0
- UBA1380 after backend restart: LIVE/ARM ON · RUNNING · Feed REAL_FRESH

## Safety

REAL_TRADING_MUTATION=0 · LIVE_ARM_MUTATION=0 · RISK/SLOT/POLICY=0

## Limitations

- Tailscale/HTTPS not in this STEP
- Icons: favicon.ico only (brand 192/512 pending)
- KIWOOM market_status may be UNKNOWN without calendar enrichment

NEXT_ACTION: **TEST_MOBILE_PWA_ON_LOCAL_WIFI**
