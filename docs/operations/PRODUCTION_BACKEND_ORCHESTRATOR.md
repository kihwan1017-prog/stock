# Production Backend + Canonical Autotrading Orchestrator

**Date:** 2026-08-22 (updated 2026-09-01 — hot-reload isolation History #92)  
**Target verdict:** `PRODUCTION_BACKEND_AND_CANONICAL_AUTOTRADING_ORCHESTRATOR_COMPLETE`

## Launch modes

| Mode | Script | Env | Reload | REAL LIVE/ARM |
|------|--------|-----|--------|---------------|
| DEV | `ops/dev/start-dev.ps1` / `ops/start_backend_dev.ps1` | `APP_RUNTIME_MODE=development` `HOT_RELOAD_ENABLED=true` | `--reload --reload-dir src` | **blocked** (fail-closed) |
| PROD | `ops/start_backend_prod.ps1` | `APP_RUNTIME_MODE=production` `HOT_RELOAD_ENABLED=false` | **forbidden** | allowed (gates 통과 시) |
| NSSM | `ops/install_nssm_service.ps1` | same as PROD | none | allowed |

Stop: `ops/stop_backend.ps1`

Env file path only (no secret copy): `E:\StockTrading\secrets\stock-platform.env`

### Invariant (History #92)

`REAL_TRADING_ACTIVE` (LIVE ON / ARM ON / active unattended lease) 이면  
filesystem source change만으로 backend process가 자동 restart되면 안 된다.

- DEV: frontend 변경은 backend watcher 대상 아님 (`--reload-dir src`만).
- DEV: REAL LIVE enable / initial ARM / unattended restore → `REAL_RUNTIME_REQUIRES_STABLE_PROCESS`.
- PROD: reload 없음. controlled restart만.

ops-status fields: `RUNTIME_MODE`, `HOT_RELOAD_ENABLED`, `STABLE_RUNTIME_REQUIRED`, `REAL_RUNTIME_STABLE`.

## Safe deployment workflow (REAL runtime)

코드 변경을 REAL runtime에 반영할 때:

1. DEVELOP (dev/reload 허용 — PAPER only)
2. focused tests
3. selective commit
4. deployment precheck
5. open order / ambiguous / recovery gate 확인
6. safe maintenance window
7. **controlled restart** via `ops/stop_backend.ps1` → `ops/start_backend_prod.ps1`  
   (dev hot-reload / `start-dev` 금지)
8. unattended/canonical restore
9. authenticated ops-status verify

Open broker orders가 있으면 restart를 연기한다 (restore `db_open` strict gate 유지).

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
- restore `db_open` / ARM renew hardening **unchanged**
