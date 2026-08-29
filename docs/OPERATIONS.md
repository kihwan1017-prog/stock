# Operations

운영자가 실제로 쓰는 점검·기동 요약. 세부 runbook은 [operations/](operations/), [trading/](trading/).

## Runtime SoT

**HTTP** `GET /api/v1/admin/autotrading/uba/{uba_id}/ops-status`

확인 필드: LIVE · ARM · Lease · STACK · FEED · AUTO_TRADING_READY · open_orders · full_market

CLI / in-process singleton으로 RUNNING·STOPPED를 운영 SoT로 쓰지 않는다.

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
