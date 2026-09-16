# Troubleshooting

운영자가 반복적으로 쓰는 점검만. 일회성 incident 전문은 archive / `.run` evidence.

| 증상 | 확인 |
|------|------|
| Runtime STOPPED false alarm | HTTP **ops-status** SoT (CLI singleton 금지) |
| 거래 없음 | Daily Report why-no-trade · Daily ENTRY used/limit · AUTO slots · feed |
| ENTRY_PENDING stuck | orderless reject rollback · `entry_order_id` · stale recovery |
| Manual vs AUTO | Symbol ownership · MANUAL은 AUTO slot 미소비 |
| Feed stale | quote WS / hub · reconnect · age_seconds |
| Restart 불안 | AUTO open · ENTRY_PENDING · cancel/recovery/exit pending |
| Telegram / Daily Report | allowlist · report-slim · ops projection |
| Migration | `alembic heads` · `database/alembic` only |
| Frontend 기동 | Next listen · antd-compat · TypeScript |

상세: [OPERATIONS.md](OPERATIONS.md) · [operations/](operations/) · [KNOWN_ISSUES archive](archive/2026-08/root-portal/KNOWN_ISSUES.md)
