# Single Admin Trading Cockpit — Frontend Operations UX

**Date:** 2026-08-22  
**Verdict target:** `SINGLE_ADMIN_TRADING_COCKPIT_FRONTEND_COMPLETE`  
**Safety:** Backend Python trading/runtime **unchanged**. No LIVE/ARM/Risk/Slot mutation in this STEP.

---

## Canonical WRITE locations

| WRITE | Canonical screen |
|-------|------------------|
| Credential | 계좌·자산 → 계좌 현황 |
| LIVE / ARM | 계좌 현황 (+ Upbit one-click / 24H on Upbit workspace) |
| Risk / Kill | 리스크·안전 → 리스크 |
| Preflight / Live validation | 리스크·안전 → 안전 제어 |
| Autotrading start/stop (FE orchestration) | 업비트 자동매매 Workspace |
| Strategy publish | 전략·분석 → 전략·후보 |
| Notification template | 알림 센터 |
| System config | 시스템 → 환경 설정 |

Other screens: READ summary + link only.

---

## BACKEND_READ_API_GAP (this STEP)

1. AUTO PnL 7/30일 · 누적 · broker 비교 **시계열 API 없음** → chart empty state
2. `GET /orders`에 `strategy_id` / `order_source` 미노출 → AUTO/MANUAL는 strategy_code 휴리스틱 (low confidence 표시)
3. OPEN slot qty/entry/current/SL/TP/Trailing READ 없음
4. Entry block reason **history** 집계 API 없음 → latest slot reason만
5. `GET /risk/daily-loss/strategy-owned`는 조회 시 persist → Cockpit 자동 폴링에서 **호출하지 않음**
6. Order Limit V2 usage 전용 Admin READ 필드 미확인

FE wrappers added (기존 BE만): `listAdminSymbolOwnership`, `getAdminSymbolOwnership`.

---

## Out of scope (NEXT)

`SWITCH_LIVE_BACKEND_TO_PRODUCTION_MODE_AND_ADD_CANONICAL_START_STOP_ORCHESTRATOR`
