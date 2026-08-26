# Telegram Market Routing & Analysis Suppression

**Verdict:** `TELEGRAM_ROUTING_READY_DESTINATION_CONFIG_PENDING`

## Summary

- Central `TelegramNotificationPolicy` (`notification/telegram_policy.py`) classifies SYSTEM / TRADING / ANALYSIS / CRITICAL.
- Market destinations: `TELEGRAM_UPBIT_CHAT_ID` / `TELEGRAM_KIWOOM_CHAT_ID` with fallback `TELEGRAM_CHAT_ID`.
- UPBIT ANALYSIS suppressed when daily entry hard-cap reached; SYSTEM / TRADING / CRITICAL continue.
- KIWOOM ANALYSIS allowed only when trading-ready (phase + LIVE + ARM + runtime RUNNING); SYSTEM / CRITICAL continue off-hours.
- Edge SYSTEM alerts for daily-limit and market open/close with process-local dedup.
- Pipeline (scanner / LLM / RAG / shadow / CLEAN) unchanged — Telegram output only.
- Status: `GET /api/v1/telegram/status` (+ ops status embeds `market_routing`).
- Admin Telegram page shows masked UPBIT/KIWOOM destination + analysis ON/OFF + reason.

## Live snapshot (pre-commit probe)

| Market | Analysis | Reason | Notes |
|--------|----------|--------|-------|
| UPBIT | OFF | `DAILY_ENTRY_LIMIT_REACHED` | 12/10 |
| KIWOOM | OFF | `RUNTIME_STOPPED` | phase TRADING, LIVE/ARM on, runtime STOPPED |

Both destinations currently use **FALLBACK** chat (separate chat IDs not configured yet).

## Tests

`pytest tests/test_telegram_market_routing_analysis_suppression.py` — PASS

## Safety

`REAL_ORDER_MUTATION=0` · `DAILY_LIMIT_CHANGE=0` · `DAILY_COUNT_RESET=0` · LLM/trading policy unchanged.

## Next

Configure `TELEGRAM_UPBIT_CHAT_ID` / `TELEGRAM_KIWOOM_CHAT_ID` and observe natural alerts.
