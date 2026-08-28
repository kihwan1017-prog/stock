# WRK-012 — Upbit post-restart restore “failure”

## Verdict

`FALSE_ALARM_INPROCESS_PROBE_RESTORE_ALREADY_SUCCEEDED`

서버 unattended restore는 **실패하지 않았다**.  
보고된 STOPPED 상태는 **별도 Python 프로세스의 in-process singleton 측정 오류**였다.

## Evidence

### Startup log (UTF-16 `logs/dev/backend.log`)

`2026-08-28T17:46:32Z` Application startup begin  
→ `unattended upbit lease/stack restore`  
→ `upbit_unattended_stack_restored` **`stack_ok=true`**  
  - runtime `RESUMED`  
  - execution runner `STARTED`  
  - verify `restore_succeeded=true`, `missing_components=[]`  
→ Application startup complete `17:46:34Z`

Lease renewal actor: `SYSTEM_UNATTENDED_STARTUP_RESTORE` (LIVE/ARM restored).

### HTTP ops-status (server process) — now

LIVE ON · ARM ON · LEASE ACTIVE  
runtime/runner/worker/exit_monitor **RUNNING** (4/4)  
scanner true · Feed **REAL_FRESH** · `AUTO_TRADING_READY=true` · reliability READY

### Why probes said STOPPED

`build_uba_operational_summary()` / worker status in a **CLI process** reads that process’s empty runtimes → always STOPPED/DISCONNECTED.  
Does **not** reflect uvicorn PID 22080.

## Restore sequence

`FIRST_FAILED_STAGE=null` — all expected stages PASS on server.

## WRK-010 regression

**false.** Diff `0e7cf9c..41ea0c5` is report/research slim only; no lifecycle/restore changes.

## Fix / deploy

- Code fix: **none** (no restore bug)  
- Restart: **0** (already healthy)  
- LIVE/ARM mutation: **none**

## Follow-up practice

Restore/health polls must use **HTTP** `/api/v1/admin/autotrading/uba/{id}/ops-status`, not in-process ops summary for stack components.

## WRK-011 continuation

- ADA no-sell: still #1926 unfilled cancel path — **not** exit_monitor downtime after 02:46 server restore.  
- DOS no-buy: still `MAX_OPEN_POSITIONS_REACHED` (5 broker snapshots) during RUNNING executor path.
