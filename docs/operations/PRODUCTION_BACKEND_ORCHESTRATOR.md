# Production Backend + Canonical Autotrading Orchestrator

**Date:** 2026-08-22  
**Target verdict:** `PRODUCTION_BACKEND_AND_CANONICAL_AUTOTRADING_ORCHESTRATOR_COMPLETE`

## Launch modes

| Mode | Script | Reload | Workers |
|------|--------|--------|---------|
| DEV | `ops/dev/start-dev.ps1` / `ops/start_backend_dev.ps1` | `--reload --reload-dir src` | 1 (reload supervisor) |
| PROD | `ops/start_backend_prod.ps1` | **forbidden** | `--workers 1` |
| NSSM | `ops/install_nssm_service.ps1` | none | 1 |

Stop: `ops/stop_backend.ps1`

Env file path only (no secret copy): `E:\StockTrading\secrets\stock-platform.env`

## API

- `GET  /api/v1/admin/autotrading/uba/{id}/status`
- `POST /api/v1/admin/autotrading/uba/{id}/start` `{ reauthorize_unattended?, strategy_id? }`
- `POST /api/v1/admin/autotrading/uba/{id}/stop` `{ mode: ENTRY_ONLY|FULL, strategy_id? }`

Individual Worker/Runtime/Exit endpoints remain for backward compatibility.

## STOP semantics

- **ENTRY_ONLY** (UI primary): Runtime + Execution Runner stop; Exit/Worker/LIVE/ARM/24H **kept**
- **FULL**: blocked if OPEN AUTO slots; else Runtime→Exit→Worker; LIVE/ARM OFF not auto

## Safety

- No AUTO LIVE/ARM toggle (except existing unattended reauthorize)
- No REAL order create
- UBA asyncio single-flight lock
- Idempotent ALREADY_RUNNING
