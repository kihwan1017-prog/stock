# UPBIT 24H Unattended Authorization

운영자 명시 승인 기반 long-running authorization lease.
ARM TTL 무제한 / Activation expires_at 직접 UPDATE / Kill Switch 우회 금지.

## Modes

| Mode | 용도 | ARM TTL | Renewal |
|------|------|---------|---------|
| MANUAL / SMOKE | 수동 검증 | 기본 300s (정책) | 없음 — 운영자 재 ARM |
| UNATTENDED | 관리자 `24시간 무인운영 시작` | lease TTL(기본 3600s) | safety gate PASS 시만 |

## Approval model (역할 분리)

| 동작 | 승인 모델 | 문구 |
|------|-----------|------|
| LIVE ON / Activation | LIVE broker approval_phrase | `ENABLE UPBIT LIVE TRADING` |
| 24H Unattended Enable | `UNATTENDED_LEASE_ACK` | confirmation `ENABLE 24H UNATTENDED` |

Unattended Enable은 **이미 승인된 LIVE 세션의 제한된 무인 운영 승인**이다.
LIVE ON approval_phrase를 다시 받지 않으며, FE에서 LIVE 문구를 숨겨 자동 전송하지도 않는다.

## Enable gates (전부 PASS 필수 · FAIL CLOSED)

- ADMIN
- UBA broker = UPBIT + REAL (`UPBIT_USE_MOCK` 금지)
- Credential VERIFIED
- Connection CONNECTED
- Recovery SUCCESS/READY
- trading_paused=false
- Active HIGH/CRITICAL Conflict=0
- Kill Switch OFF
- Activation ACTIVE
- LIVE ON
- ARM ON
- Risk / account safety PASS

## Enable API

- Confirmation: `ENABLE 24H UNATTENDED` (exact)
- `source`: `ADMIN_UI` | `ADMIN_API`
- reason + horizon (기본 24h, 최대 168h)
- **approval_phrase 필드 없음**
- API: `POST /api/v1/admin/autotrading/uba/{id}/unattended/enable`

## Audit (enable)

actor · user_broker_account_id · broker · enabled_at · authorization horizon ·
LIVE/ARM state · activation id/expiry · reason · source · approval_model

## Renewal conditions (all required)

Enable과 동일 게이트. 실패 시 renewal 금지.
Activation은 successor approve(audit)로만 갱신.

## Expiry fail-closed

- ENTRY Runtime STOP
- 보유 포지션 있으면 `PROTECTIVE_EXIT_ONLY` (EXIT 유지, ENTRY 차단)
- 플랫이면 DISARM + LIVE OFF + lease EXPIRED

## Admin UI

전체 계좌 `AUTO TRADING` 컬럼 + 운영 상세 Drawer.
Modal: 상태 요약 + `[취소]` / `[24시간 무인운영 시작]` (문구 타이핑 없음).
성공 후 운영 스택 시작 제안 유지.

상태 SoT: `GET …/ops-status` (`auto_trading_state`).

## Related

- Session manual renew: [UPBIT_UBA1380_24X7_SESSION_RENEWAL.md](UPBIT_UBA1380_24X7_SESSION_RENEWAL.md)
- Post-fill sync-pending: fill-sync 직후 POSITION_MISMATCH는 bounded retry 후 Kill
