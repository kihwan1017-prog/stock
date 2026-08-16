# UPBIT TERMINATION RUNTIME LOAD + NATURAL OBSERVATION

**STEP:** U-TERM-B · **Date:** 2026-08-16  
**Verdict:** **`UPBIT_TERMINATION_RUNTIME_PROVEN_WITH_LIMITATIONS`**  
**JSON:** [TECHNICAL_SHADOW_TERMINATION_RUNTIME_OBSERVATION.json](TECHNICAL_SHADOW_TERMINATION_RUNTIME_OBSERVATION.json)

---

## Safety / load

| Check | Result |
|-------|--------|
| Pre-restart LIVE/ARM/exec/outbox | false / OFF / false / false |
| TradingOrder / Outbox | 241 / 52 |
| stop-dev + start-dev | OK · listen PID **20884** · health **UP** |
| U_TERMINATION_CODE_LOADED | **YES** (`TARGET_PERMANENTLY_UNRESOLVABLE` in evaluator) |

## Shadow 52

| Phase | status | termination |
|-------|--------|-------------|
| Before | ACTIVE · updated `03:48:35Z` | null |
| After natural tick | **CANCELLED** · updated `03:56:08Z` | `TARGET_PERMANENTLY_UNRESOLVABLE` |

Provenance present: version, reason, terminated_at, target_window, target_at, first_blocked_at (bootstrap `22:20:00Z`), last_checked_at, fallback_limit=180.  
`evaluated_60m_at` / `return_60m` / `completed_at` = **null**.  
Forced evaluate **NO** · direct UPDATE **NO**.

## Idempotency

Next natural window observed: `updated_at` / `terminated_at` **unchanged** (`03:56:08Z`) · still CANCELLED.

## Isolation

COMPLETED count excludes CANCELLED · shadow 52 not in COMPLETED. Coverage reopen **NO** · TP **CLOSED_KEEP_6**.

## Limitations

1. `nearest_prior_at` / `prior_lag_seconds` null in termination detail (window lag null; candidate still valid)  
2. Pre-ACTIVE-era `mfe_pct`/`mae_pct`/`tp_hit`/`sl_hit` columns remain (terminate path did not write them)  
3. Shadow **70** also CANCELLED same tick (same predicate · expected collateral)

## Next U

**UPBIT TERMINATION SELECTIVE COMMIT PRECHECK**
