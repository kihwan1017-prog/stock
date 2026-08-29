# Operations

운영자가 실제로 쓰는 점검·기동 요약. 세부 runbook은 [operations/](operations/), [trading/](trading/).

## Runtime SoT

**HTTP** `GET /api/v1/admin/autotrading/uba/{uba_id}/ops-status`

확인 필드: LIVE · ARM · Lease · STACK · FEED · AUTO_TRADING_READY · open_orders · full_market

CLI / in-process singleton으로 RUNNING·STOPPED를 운영 SoT로 쓰지 않는다.

## 알림 (Trading Alert V2)

사용자 대분류: **[업비트] / [키움] / [시스템]**

- Admin: `/admin/notifications` → 알림 수신 설정 (delivery only — LIVE/ARM/전략 미변경)
- API: `GET/PATCH /api/v1/admin/trading-alert-preferences` (`require_admin`)
- AUTO BUY/SELL 체결은 FILLED 중심, MANUAL/TEST 제외
- Upbit fill + Kiwoom fill → Alert V2 emit (NOTIFICATION_FAIL_OPEN)
- Telegram 실패는 주문 경로에 영향 없음
- Daily Report는 개별 BUY/SELL과 별도 유지
- ops-status는 Admin API Key/`require_admin` 인증 필요 (비인증은 401 — hang이 아님)

## 기본 점검 순서

1. Backend health (live/ready)
2. ops-status (위 SoT)
3. Feed freshness / quote WS
4. AUTO open order · ENTRY_PENDING · cancel/recovery/exit pending
5. Daily Report / why-no-trade
6. 로그: 프로세스 stdout + 필요 시 DB work history

## Restart

- 코드 load가 필요할 때만 controlled restart (가능하면 1회)
- 사전: AUTO open · ENTRY_PENDING · submission/executor inflight · cancel · recovery · exit pending
- 불안전하면 restart 연기 — blocker 강제 해소 금지

## 관련 포털

- [AUTO_TRADING.md](AUTO_TRADING.md)
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
- [deployment/](deployment/) · [operations/](operations/)
- 과거 root RUNBOOK/RECOVERY/INSTALL: [archive/2026-08/root-portal/](archive/2026-08/root-portal/)
