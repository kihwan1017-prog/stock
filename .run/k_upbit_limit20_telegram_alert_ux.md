# UPBIT Limit 20 + Telegram Alert UX

**FINAL_VERDICT:** `UPBIT_LIMIT20_TELEGRAM_ALERT_UX_COMPLETE`

## Mandatory 1 — Daily limit 10→20

| Item | Value |
|------|-------|
| SoT | `operation.upbit_portfolio_policy.portfolio_daily_entry_limit` (UBA1380) |
| Default constant | `DEFAULT_PORTFOLIO_DAILY_ENTRY_LIMIT=20` |
| BEFORE / AFTER | 10 → **20** |
| Current count | **12 / 20** |
| Remaining | **8** |
| Blocking | **false** |
| Atomic hard-cap | preserved (`pg_advisory_xact_lock` + RLock + final admit) |
| Concurrent tests | 19+5→20, 18+5→20, 20+5→20, overshoot=0 |
| Count reset | **0** |

## Mandatory 2 — Telegram monitoring UX

**Root cause:** `LiveArmService` emitted English `UBA N disarmed (fail_closed_restart) by STARTUP`; `MONITORING_ALERT` template used `{message}` raw.

**Fix:** `notification/user_facing_alerts.py` presentation layer in `render_notification` (+ inbox + monitoring alerts API `user_title`/`user_message`).

- UBA → 업비트/키움증권 via `broker_code` (no magic 1380/1381)
- reason/actor Korean mapping (`code_dictionary`)
- UTC → `YYYY-MM-DD HH:MM KST`
- Normal startup DISARM/ARM coalesce; abnormal DISARM / CRITICAL preserved
- Destination chat ids **unchanged**

## Safety

`REAL_ORDER_MUTATION=0` · Telegram destination unchanged · Scanner/LLM/RAG unchanged

**NEXT_ACTION:** `OBSERVE_NATURAL_UPBIT_TRADES_WITH_LIMIT20`
