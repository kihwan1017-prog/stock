# STEP 8-9C-3 — Dry-run 시세·Readiness 정합

## Ticker / Orderbook

- 공개 HTTP 동기 조회 (`/v1/ticker`, `/v1/orderbook`)
- DTO: `UpbitTickerSnapshot`, `UpbitOrderbookSnapshot`
- `UpbitPrivateClient.list_tickers` async coroutine 직접 호출 금지 (AttributeError 원인)

## Slippage

Ticker 또는 Orderbook 실패 시 `SLIPPAGE=FAIL` (skipped→PASS 금지).

## Readiness 분리

| 필드 | 의미 |
|------|------|
| `dry_run_ready` | Dry-run 가능 (LIVE/ARM OFF는 EXPECTED_OFF) |
| `live_execution_ready` | 실주문 가능 (LIVE ON + ARM + 기타 게이트) |

## Scheduler

공통 `collect_scheduler_readiness()` — UI/CLI 동일.
설정 PAUSE만으로 PASS 금지. `trading_running` 실제값 사용.

## Tick

`/v1/orderbook/instruments` Broker tick 우선. 실패 시 dry-run만 STATIC fallback.
`requested_limit_price` / `effective_limit_price` / `tick_source` 기록.

## Daily Loss

UBA scope만 (`paper_account_id IS NULL`).
`current` / `limit` / `remaining` / `scope` 명시. 한도 초과 시 Fail Closed.
