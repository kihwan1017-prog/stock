# UPBIT 24H Unattended Authorization

운영자 명시 승인 기반 long-running authorization lease.
ARM TTL 무제한 / Activation expires_at 직접 UPDATE / Kill Switch 우회 금지.

## Modes

| Mode | 용도 | ARM TTL | Renewal |
|------|------|---------|---------|
| MANUAL / SMOKE | 수동 검증 | 기본 300s (정책) | 없음 — 운영자 재 ARM |
| UNATTENDED | 관리자 `Enable 24H Unattended` | lease TTL(기본 3600s) | safety gate PASS 시만 |

## Enable

- Confirmation: `ENABLE 24H UNATTENDED`
- Approval phrase + reason + horizon (기본 24h, 최대 168h)
- 기존 LIVE 계좌 자동 전환 금지
- API: `POST /api/v1/admin/autotrading/uba/{id}/unattended/enable`

## Renewal conditions (all required)

UBA active · credential/connection/recovery · trading_paused=false · HIGH conflict=0 ·
Kill OFF · account not paused · Activation valid · LIVE ON · ARM ON ·
within `authorized_until` horizon.

실패 시 renewal 금지. Activation은 successor approve(audit)로만 갱신.

## Expiry fail-closed

- ENTRY Runtime STOP
- 보유 포지션 있으면 `PROTECTIVE_EXIT_ONLY` (EXIT 유지, ENTRY 차단)
- 플랫이면 DISARM + LIVE OFF + lease EXPIRED

## Admin UI

전체 계좌 `AUTO TRADING` 컬럼 + 운영 상세 Drawer.
상태 SoT: `GET …/ops-status` (`auto_trading_state`).

## Related

- Session manual renew: [UPBIT_UBA1380_24X7_SESSION_RENEWAL.md](UPBIT_UBA1380_24X7_SESSION_RENEWAL.md)
- Post-fill sync-pending: fill-sync 직후 POSITION_MISMATCH는 bounded retry 후 Kill
