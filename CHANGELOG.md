# Changelog

## 1.0.0 — 2026-07-18

### Added
- STEP35~39 운영 통합: API lifecycle, market/indicator, screener/AI, order pipeline, risk, ops health/dashboard/audit
- `OrderExecutionService` 단일 주문 진입점 + Outbox
- AI analysis 재현/metrics API
- System health, operations dashboard, admin API key, Discord notifications
- Operations runbooks and live trading checklist

### Security
- Live trading blocked by default (`KIWOOM_LIVE_ORDER_ENABLED=false`)
- LIVE adapter requires DB transition approval
- Admin-protected sensitive endpoints

### Notes
- PostgreSQL Windows service only (no Docker)
- Alembic head: `a2b3c4d5e6f7`
