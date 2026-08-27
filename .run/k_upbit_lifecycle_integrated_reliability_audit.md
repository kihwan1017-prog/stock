# UPBIT Autotrading Lifecycle Integrated Reliability Audit

**FINAL_VERDICT:** `UPBIT_LIFECYCLE_BLIND_SPOTS_FIXED`  
**BASE:** `1771087`  
**CURRENT_KST:** 2026-08-28 (post-audit)

## Supervisor decision

**CURRENT_WATCHDOG_GRAPH_SUFFICIENT = true**  
**UNIFIED_LIFECYCLE_SUPERVISOR_REQUIRED = false**  
**IMPLEMENTED unified supervisor = false**

기존 그래프로 충분:
- ReliabilityWatchdog L0–L2
- ExitOrderSupervisor (L1)
- StartupOpenOrderReconciliation
- PipelineLiveness / DataTrust / WaitingLifecycle

이번 Audit에서 닫은 사용자 선인지 사각:
1. EXIT stuck age를 canonical `upbit_portfolio_entry_pending_timeout_seconds`(120s)에 정렬 (기존 900s)
2. open AUTO SELL 존재 시 ExitOrderSupervisor 호출 (15분 게이트에만 묶이지 않음)
3. EXIT stuck/recovery Telegram edge-trigger
4. ENTRY_PENDING without order → L1 `recover_stale_entry_pending_without_order`

## CURRENT (live backend API)

| 항목 | 값 |
|------|-----|
| LIVE | ON |
| ARM | ON |
| LEASE | ACTIVE #6 |
| STACK | all RUNNING |
| FEED | REAL_FRESH |
| AUTO_TRADING_READY | true |
| HEALTH | READY |
| CLASSIFICATION | NORMAL_POLICY_BLOCK (daily 8/20) |
| EXIT_PENDING_STUCK | 0 |
| USER_STATUS | 🟢 자동매매 정상 |
| DATA_TRUST | VALID / NORMAL_POLICY_BLOCK |
| Watchdog | running |

Slots: OPEN=1 (KRW-ADA), WAITING_SIGNAL=4  
Local AUTO open orders: 0  
Broker wait without local (external/manual SELL): 4 (BTC/SKY/DOGE/ETH) — **자동 cancel 금지 (MANUAL/external 보호)**

## Lifecycle coverage

| Stage | Owner | Watchdog/Self-heal | Blind? |
|-------|-------|--------------------|--------|
| MARKET/FEED | Quote hub | L1 feed | covered |
| SCANNER | Opportunity scanner | L1 scanner | covered |
| CANDIDATE→SELECTION | Scanner/AI | funnel/heartbeat | covered (obs) |
| WAITING | Portfolio waiting | L1 revalidate / starvation | covered |
| ENTRY_EVAL/PASS | Strategy runtime | FIRST_ZERO | covered |
| ADMISSION | Portfolio admit | funnel ADMISSION hardcode 0 | residual obs skew |
| ORDER/OUTBOX/SUBMIT | Outbox worker | stack L2 | covered |
| BUY WAIT | Startup recon + fill-sync | stale SAFE_CANCEL | covered |
| POSITION OPEN | Lifecycle sync | reopen on cancel | covered |
| EXIT MONITOR | Exit monitor | stack L2 | covered |
| SELL WAIT | ExitOrderSupervisor | L1 + startup | covered (post-fix) |
| LEASE/STACK | Unattended restore | L0/L2 | covered |
| DATA TRUST | Window sync | INVALID/DEGRADED/VALID | covered |

## Orphans (DB)

| Type | Count | Auto recovery |
|------|------:|---------------|
| waiting_without_symbol | 0 | — |
| entry_pending_no_buy | 0 | L1 without-order |
| entry_pending_terminal_buy | 0 | L1 lifecycle |
| open_without_binding | 0 | — |
| binding_open_without_slot | 0 | — |
| exit_pending_no_open_sell | 0 | lifecycle reopen |
| exit_pending_terminal_sell | 0 | lifecycle |
| accepted_no_broker_id | 0 | fail-closed |
| broker_open_no_local | 4 | **no auto cancel** (external) |
| local AUTO open | 0 | — |

## Residual gaps (non-unified)

1. Ghost `FILLED_EXIT_WITH_OPEN_BINDING` — detect only (heal 미연결)
2. Funnel `ADMISSION=0` hardcode — PIPELINE_STALL 오인 가능
3. External broker SELLs — observability (LOCAL_REMOTE_DIVERGENCE Trust 미평가)
4. Trailing N10 cohort — validish=13 (<10 ready? N10 needs careful definition; currently not promotion-ready as N10 set)
5. UNKNOWN ownership open — restore fail-closed (의도된 안전)

## Self-heal safety

IDEMPOTENT=true / NO_DUPLICATE_ORDER=true / NO_FORCE_TRADE=true  
Supervisor cancel once / Telegram edge once.

## Shadow

| Dataset | VALID | DEGRADED | INVALID(quarantined) | UNKNOWN |
|---------|------:|--------:|---------------------:|--------:|
| Entry | 40000 | 4950 | 185 (185) | 78060 |
| Trailing | 8 | 3 | 0 | 2 |
| MA Exit | 8 | 3 | 0 | 14 |

TRAILING_N10_READY=false (validish≈13 but promotion gate 별도)

## Tests

focused PASS: exit_pending_stuck, exit_order_supervisor, startup_open_order_reconciliation

## Prod observation

3 watchdog/health ticks: READY / FEED REAL_FRESH / EXIT_STUCK=0  
BACKEND_RESTART_COUNT=1 (blind-spot code load)

## Safety

FORCED_REAL_ORDER=0 NEW_BUY/SELL=0 REAL policy unchanged LIVE/ARM manual=0 DAILY=0 KIWOOM=0 PROCESS_VERSION_CHANGED=false

SYSTEM_BUG_ACTIVE=false (core AUTO path)  
CAN_SAFELY_CONTINUE=true
