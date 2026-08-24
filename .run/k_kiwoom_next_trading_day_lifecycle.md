# Kiwoom Next Trading Day Lifecycle — Evidence

**Date:** 2026-08-24  
**Scope:** UBA1381 Kiwoom REAL next-day auto-start + EOD lifecycle (fail-closed)  
**Safety:** REAL BUY/SELL force 없음 · UBA1380/Risk/Strategy param 변경 없음 · backend restart 0

---

## FINAL_VERDICT

`KIWOOM_NEXT_TRADING_DAY_LIFECYCLE_IMPLEMENTED_FAIL_CLOSED`

익일 자동 시작은 **opt-in + source Activation successor + 정규장 precheck PASS** 조건에서만 동작한다.  
Activation greenfield(`ENABLE KIWOOM LIVE TRADING`) 우회 금지.

---

## AUTO START

| # | Item | Result |
|---|------|--------|
| 1 | NEXT_DAY_AUTO_START_IMPLEMENTED | **YES** — `KiwoomTradingDayLifecycleService` + expiry scanner hook |
| 2 | TRADING_CALENDAR_USED | **YES** — `TradingCalendarService` via `krx_market_hours_state` |
| 3 | HOLIDAY_SAFE | **YES** — non-trading → `SAFE_IDLE` / `WAIT_TRADING_DAY` |
| 4 | PRECHECK_GATE_COUNT | **13** (named gates in `evaluate_auto_start_precheck`) |
| 5 | FAIL_CLOSED | **YES** — any blocker → `BLOCKED`, LIVE/ARM 강제 진행 없음 |
| 6 | ACTIVATION_HANDLING | **SUCCESSOR_ONLY** — no source → `ACTIVATION_SECURITY_BOUNDARY` |
| 7 | LIVE_AUTO_START | **YES** — via `restore_from_active_lease` after MARKET_HOURS reauth |
| 8 | MARKET_HOURS_AUTH_AUTO_START | **YES** — `reauthorize_market_hours_for_trading_day` |
| 9 | ARM_AUTO_START | **YES** — restore path ARM ON (TTL 3600, ceiling clamp) |
| 10 | ARM_AUTO_RENEW | **YES** — 기존 MARKET_HOURS auto-renew 재사용 |
| 11 | ARM_CLOSE_CEILING | **YES** — 당일 KRX regular close |

## RUNTIME

| # | Item | Result |
|---|------|--------|
| 12 | FEED_AUTO_START | **YES** — `restore_kiwoom_trading_stack` → market realtime (idempotent) |
| 13 | WARMUP_PRELOAD | **PRESERVED** — READY 전 `WARMUP` phase; 기존 1D MA preload 경로 유지 |
| 14 | RUNTIME_AUTO_RESUME | **YES** — ensure-scope → resume (startup_forced_idle 복구) |
| 15 | RUNNER_AUTO_START | **YES** — scoped `_start_live_for_uba` (idempotent) |
| 16 | RESTART_RECOVERY | **YES** — ACTIVE lease + LIVE/ARM OFF → restore; 아니면 fail-closed |
| 17 | UPBIT_CONCURRENT_SAFE | **YES** — KIWOOM UBA scope only · Upbit runner 미터치 |

## EOD

| # | Item | Result |
|---|------|--------|
| 18 | NEW_ENTRY_BLOCK_AFTER_CLOSE | **YES** — 기존 MARKET_HOURS expire / entry 차단 유지 |
| 19 | ARM_RENEW_AFTER_CLOSE | **NO** (금지 유지) — past_close renew 없음 |
| 20 | LIVE_ARM_EOD_STATE | **FAIL_CLOSED** — 기존 expiry scanner SoT 유지 |
| 21 | PROTECTIVE_EXIT_BEHAVIOR | **PRESERVED** — 강제 시장가 청산 신규 없음 · `PROTECTIVE_EXIT_ONLY` |

## PROVENANCE

| # | Item | Result |
|---|------|--------|
| 22 | 1822_ENTRY_GAP_ROOT_CAUSE | **BROKER_IMPORTED_POSITION** (+ NO_LOCAL_FILLED_BUY, NO_STRATEGY_BINDING). Local FILLED BUY 없음(취소 smoke #1798만). Binding 0. |
| 23 | GENERIC_FIX_IMPLEMENTED | **YES** — Kiwoom fill SELL→`exit_order_id` / BUY→`entry_order_id` (Upbit 정렬). 과거 #1822 데이터 조작 없음. |
| 24 | FUTURE_ROUND_TRIP_PNL_READY | **YES** — 신규 AUTO BUY fill부터 binding entry 연결 → SELL exit 차감 가능 |

## TEST

| # | Item | Result |
|---|------|--------|
| 25 | TEST_COUNT | **11** focused (`test_kiwoom_next_trading_day_lifecycle.py`) + MH renew / binding / unattended regression PASS |
| 26 | TEST_RESULT | **PASS** |
| 27 | GIT_COMMIT | **UNCOMMITTED** (사용자 요청 전 commit 없음) |
| 28 | BACKEND_RESTART_COUNT | **0** |

## SAFETY

| # | Item | Result |
|---|------|--------|
| 29 | REAL_ORDER_FORCE_MUTATION | **0** |
| 30 | CANCEL_AMEND_MUTATION | **0** |
| 31 | POLICY_MUTATION | **0** |
| 32 | RISK_MUTATION | **0** |
| 33 | UBA1380_MUTATION | **0** |
| 34 | SYSTEM_BUG_ACTIVE | **NO** (구현 범위 내) |
| 35 | LIMITATIONS | Opt-in + source Activation 필수. 장전 enable 불가(정규장만). Account sync는 recovery gate 대용(강제 REST sync 없음). Warmup READY 전에도 stack 기동 가능(신호는 기존 evaluator warmup 게이트). |
| 36 | CAN_RUN_NEXT_TRADING_DAY_UNATTENDED | **CONDITIONAL_YES** — `ENABLE KIWOOM NEXT DAY AUTO START` opt-in 후 다음 거래일 정규장 + gates PASS 시 |
| 37 | NEXT_ACTION | Admin에서 UBA1381 next-day opt-in 확인 → 다음 KRX 거래일 무인 관찰 |

---

## State machine

```
WAITING_MARKET → PRECHECK → ACCOUNT_SYNC → ACTIVATION_CHECK
→ LIVE/ARM via restore → MARKET_HOURS_AUTHORIZE → FEED/WARMUP
→ RUNTIME_RESUME → RUNNER_START → TRADING
→ MARKET_CLOSE → PROTECTIVE_EXIT_ONLY → SAFE_IDLE
```

Block → `BLOCKED` (fail-closed).

## Confirm phrases

| Action | Phrase |
|--------|--------|
| MARKET_HOURS ON | `ENABLE MARKET HOURS UNATTENDED` |
| Next-day ON | `ENABLE KIWOOM NEXT DAY AUTO START` |
| Next-day OFF | `DISABLE KIWOOM NEXT DAY AUTO START` |

## Key files

- `src/stock_platform/trading/kiwoom_trading_day_lifecycle.py`
- `src/stock_platform/trading/kiwoom_unattended_stack_restore.py`
- `src/stock_platform/trading/kiwoom_entry_provenance.py`
- `src/stock_platform/trading/live_session_expiry.py` (hook)
- `src/stock_platform/broker/kiwoom/fill_position_write.py` (SELL exit link)
- Admin API: `/kiwoom-lifecycle*`
- UI: `KiwoomMarketHoursArmRenewPanel.tsx`

## Scenario matrix (unit-covered / design)

| Scenario | Behavior |
|----------|----------|
| A/B 08:xx→09:00 | WAITING → PRECHECK → auto-start if opt-in |
| C/D weekend/holiday | SAFE_IDLE |
| E–K gate fails | BLOCKED + Telegram |
| L mid-day restart | ACTIVE lease → restore + stack |
| M Upbit concurrent | untouched |
| N/O EOD / post-close restart | no renew; SAFE_IDLE / PROTECTIVE |

STOP.
