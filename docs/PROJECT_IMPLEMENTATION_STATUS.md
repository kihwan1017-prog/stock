# PROJECT_IMPLEMENTATION_STATUS

**역할:** 구현 현황의 **유일한** Source of Truth.  
**근거:** PHASE 1 감사(2026-07-31) + 실행 경로 소스. 플랫폼 기타 수치는 추정치다. **UPBIT UBA1380은 COMPLETED**이며 추정치로 되돌리지 않는다.  
**최종 갱신:** 2026-08-21 (STRATEGY_CANDIDATE Admin UX Consolidation)  
**Branch / Commit baseline:** `release/v1.1.0` + residual WIP  
**워킹트리:** Autotrading/UI residual 미커밋 가능 · parallel precheck audit docs 미커밋

**Ops (2026-08-21):** SHARED `STRATEGY_CANDIDATE_UX_CONSOLIDATION` — Admin 전략·후보 사이드바 21→5 Workspace (Tab+matchPaths). API/DB/Runtime Δ0. UBA1380 PORTFOLIO ENTRY_PENDING KRW-NEAR READ-ONLY unchanged. Doc: `docs/frontend/STRATEGY_CANDIDATE_UX_CONSOLIDATION.md`.
**Ops (2026-08-20 SUPERSEDED):** TRACK U `UPBIT_FULL_MARKET_AUTOTRADING_READY_TO_ENABLE`. Scanner SHADOW + LIVE Selection layer · assignment FIXED_SYMBOL default · UBA1380 FIXED KRW-XRP · FULL_MARKET Enable 0 · REAL 주문 Δ0 · UBA1381 untouched. Next=`ENABLE UBA1380 FULL MARKET AUTO MODE FROM ADMIN UI`.
**Ops (2026-08-20 SUPERSEDED):** TRACK K `KIWOOM_UBA1381_LIVE_DEPLOYMENT_BLOCKED_LIFECYCLE`. 17579 STEP12 NOT_PROMOTED · ACTIVE LIVE deployment 0. Deployment/LIVE/ARM/Runtime 0. 주문 Δ0. Next=`KIWOOM UBA1381 STRATEGY PROMOTION DECISION PACKAGE`. UPBIT cooldown 별도 STEP.
**Ops (2026-08-20 SUPERSEDED):** TRACK K `KIWOOM_UBA1381_RUNTIME_START_FAILED`. LIVE ON+RE-ARM 성공. ensure-scope 500=Active strategy deployment not found. Runner/Scheduler RUN 0. 주문 Δ0. Next=`KIWOOM UBA1381 LIVE STRATEGY DEPLOYMENT`. UPBIT cooldown 별도 STEP.
**Ops (2026-08-20 SUPERSEDED):** TRACK K `KIWOOM_UBA1381_REARMED_READY_FOR_RUNTIME_START`. ARM ON POST 1 · TTL 300s (~11:28:01 KST). Runtime/Runner/Scheduler RUN 0. 주문 Δ0. Next=`KIWOOM UBA1381 RUNTIME START`. UPBIT cooldown 별도 STEP.
**Ops (2026-08-20 SUPERSEDED):** TRACK K `KIWOOM_UBA1381_ACCOUNT_SYNCED_READY_FOR_REARM`. REAL account-state sync PASS · SYNC_FRESHNESS PASS · conflict 0. RE-ARM/Runtime 0. 주문 Δ0. Next=`KIWOOM UBA1381 RE-ARM`. UPBIT cooldown 별도 STEP.
**Ops (2026-08-20 SUPERSEDED):** TRACK K `KIWOOM_UBA1381_LIVE_ON_READY_FOR_ACCOUNT_SYNC`. LIVE ON PUT 1 after ARM-expiry LIVE OFF. ARM/Sync/Runtime 0. 주문 Δ0. Next=`KIWOOM UBA1381 ACCOUNT SYNC / RECONCILIATION`. UPBIT cooldown 별도 STEP.
**Ops (2026-08-20 SUPERSEDED):** TRACK K `KIWOOM_UBA1381_REARM_BLOCKED_LIVE`. ARM TTL expire → LIVE OFF+DISARM (event 138 @ 10:31:33). Activation #20 ACTIVE. 재-ARM FAIL=`ARM_LIVE_REQUIRED`. Next=`KIWOOM UBA1381 LIVE ON`. SYNC stale는 LIVE ON 이후. UPBIT cooldown 별도 STEP.
**Ops (2026-08-20 SUPERSEDED):** TRACK K `KIWOOM_UBA1381_ARMED_READY_FOR_RUNTIME_PRECHECK`. ARM ON POST 1 · TTL 300s (~10:31:30 KST). Runtime/Runner/Scheduler RUN 0. 주문 Δ0. Next=`KIWOOM UBA1381 RUNTIME START READINESS`. UPBIT cooldown 별도 STEP.
**Ops (2026-08-20 SUPERSEDED):** TRACK K `KIWOOM_UBA1381_ARM_READY`. ARM ON preflight PASS · execution gate A · REST api.kiwoom.com. ARM ON 미실행. Next=`KIWOOM UBA1381 ARM ON`. UPBIT cooldown 별도 STEP.
**Ops (2026-08-20 SUPERSEDED):** TRACK K `KIWOOM_UBA1381_LIVE_ON_READY_FOR_ARM`. UBA1381 LIVE ON (PUT 1). Activation #20 ACTIVE. ARM/Runtime/Runner/Scheduler RUN 0. 주문 Δ0. Next=`KIWOOM UBA1381 ARM READINESS`. UPBIT cooldown은 별도 STEP.
**Ops (2026-08-20 SUPERSEDED):** TRACK K `KIWOOM_LIVE_ACTIVATION_READY_REACTIVATION_REQUIRED`. UBA1381 precheck PASS. 시세 ENV REAL 로드(restart 1). Activation #13 EXPIRED → 신규 필요. LIVE/ARM/Runtime/Runner 0. 주문 Δ0. Next=`KIWOOM UBA1381 LIVE ACTIVATION CREATE`. UPBIT cooldown은 별도 STEP.
**Ops (2026-08-20 SUPERSEDED):** TRACK K `KIWOOM_KRX_REAL_MARKET_DATA_TICK_PROVEN_LIVE_PRECHECK_PENDING`. 장중 REAL 0B tick 8건 (034310) · Hub/consumer isolation PASS. `KIWOOM_USE_MOCK=true` 유지 · `KIWOOM_MARKET_DATA_USE_MOCK=false`. LIVE/ARM/Runtime/Runner START 0. 주문 Δ0. restart 0. Next=`KIWOOM LIVE ACTIVATION READINESS`. UPBIT cooldown은 별도 STEP.
**Ops (2026-08-20 SUPERSEDED):** TRACK U `UPBIT_REMOTE_SELL_ORDERS_CANCELLED_COOLDOWN_ALIGNMENT_PENDING`. 승인 UUID 3 CANCEL once · wait=0 · locked=0. SOL open-order gate PASS. GO_LIVE_READY=NO (cooldown). START 0. 주문 Δ0. src/restart 0. Next=`UPBIT KRW-SOL LIVE COOLDOWN ALIGNMENT` (09:00 이후 KIWOOM OPEN tick 우선). KIWOOM FREEZE.
**Ops (2026-08-20 SUPERSEDED):** TRACK U `UPBIT_REMOTE_OPEN_ORDER_SAFETY_ALIGNED_CANCELLATION_APPROVAL_REQUIRED`. remote wait=3 (DOGE/SKY/BTC ask, local map 0, CANCEL 0). LIVE ENTRY max_open_orders = local+unmapped remote. SOL BUY dry BLOCK OPEN_ORDER_LIMIT_EXCEEDED. START 0. 주문 Δ0. backend restart 1 no-reload. Next=`UPBIT EXTERNAL REMOTE SELL ORDER CANCELLATION APPROVAL`. KIWOOM FREEZE.
**Ops (2026-08-20 SUPERSEDED):** TRACK U `UPBIT_KRW_SOL_RUNTIME_APPROVAL_GATE_ALIGNED_REMOTE_ORDERS_PENDING`. Runtime gate 분류 C. 17580 `approved_at=null` 유지 · catalog approve 0. `STRATEGY_NOT_APPROVED` 제거(PRIVATE_EVIDENCE 72396/1528). TIMEFRAME_ALIGNMENT_READY=YES. GO_LIVE_READY=NO (remote wait=3 · Activation #19 EXPIRED · LIVE/ARM OFF). START 0. 주문 Δ0. backend restart 1 no-reload. Next=`UPBIT REMOTE PENDING ORDER RECONCILIATION`. KIWOOM FREEZE.
**Ops (2026-08-20 SUPERSEDED):** TRACK U `UPBIT_KRW_SOL_LIVE_TIMEFRAME_ALIGNED_OTHER_BLOCKERS_REMAIN`. 17580 LIVE 1D MA=price_daily+KST rolling close. TIMEFRAME_ALIGNMENT_READY=YES. GO_LIVE_READY=NO (`STRATEGY_NOT_APPROVED` · remote wait=3). Activation/LIVE/ARM/Runtime/Runner 0. 주문 Δ0. backend restart 1 no-reload. Next=`UPBIT KRW-SOL STRATEGY LIVE APPROVAL ALIGNMENT`. KIWOOM FREEZE.
**Ops (2026-08-20 SUPERSEDED):** TRACK U `UPBIT_KRW_SOL_LIVE_TIMEFRAME_ALIGNMENT_REQUIRED`. 17580 1D vs LIVE raw-tick MA mismatch. GO_LIVE_READY=NO. Activation/LIVE/ARM/Runtime/Runner 0. remote wait=3 · STRATEGY_NOT_APPROVED. LIVE 주문 Δ0. Next=`UPBIT KRW-SOL LIVE TIMEFRAME ALIGNMENT IMPLEMENTATION`. KIWOOM FREEZE.
**Ops (2026-08-20 SUPERSEDED):** TRACK U `UPBIT_KRW_SOL_STRATEGY_ACTIVATED_AND_LINKED_LIVE_PRECHECK_PENDING`. 17580 catalog active · UBA1380 link **2357**. 17483/2354 유지. LiveTrading #19 EXPIRED · LIVE OFF · ARM OFF · Runtime/Runner 0. LIVE 주문 Δ0. Next=`UPBIT NEW-SYMBOL CONTROLLED LIVE ACTIVATION PRECHECK`. KIWOOM FREEZE.
**Ops (2026-08-20 SUPERSEDED):** TRACK U `UPBIT_KRW_SOL_STRATEGY_VALIDATED_ACTIVATION_PENDING`. ROOT_CAUSE=`PAPER_REPLAY_BUY_NOTIONAL_IGNORES_RESOLVED_RISK_CAPS`. Paper **1528 PAPER_PASS** (5252). 1527 보존. 17580 inactive. Backtest 72396 유지. LIVE 주문 Δ0. Next=`UPBIT KRW-SOL STRATEGY ACTIVATION AND UBA1380 LINK READINESS`. KIWOOM FREEZE.
**Ops (2026-08-20 SUPERSEDED):** TRACK U `UPBIT_SELECTED_NEW_SYMBOL_REJECTED_BY_PAPER`. SELECTED KRW-SOL. 17580 Backtest 72396 KPI PASS. Paper 1527 INSUFFICIENT (fill 0 / SYMBOL_POSITION_LIMIT). 17483 Δ0. LIVE 주문 Δ0. Next=`STOP`. KIWOOM FREEZE.
**Ops (2026-08-19 SUPERSEDED):** TRACK K `KIWOOM_REAL_MARKET_DATA_RUNTIME_READY_NEXT_SESSION_TICK_PROOF_PENDING`. Official 0B REAL WS client + Hub. 장외 LOGIN/REG ACK YES · tick 0. LIVE OFF · ARM OFF · Runtime 0. 주문 Δ0. Next=`KIWOOM KRX OPEN REAL MARKET DATA TICK VALIDATION`.
**Ops (2026-08-19 SUPERSEDED):** TRACK K `KIWOOM_STRATEGY_17579_ACTIVATED_AND_LINKED_REALTIME_BLOCKED`. 17579 `is_active=true` · link **2356** UBA1381. LIVE OFF · ARM OFF · Runtime 0. REAL WS NOT IMPLEMENTED. KIWOOM_LIVE_READY=NO. 주문 Δ0. Next=`KIWOOM REAL MARKET DATA RUNTIME IMPLEMENTATION`.
**Ops (2026-08-19 SUPERSEDED):** TRACK K `KIWOOM_DERIVED_STRATEGY_17579_VALIDATED_ACTIVATION_PENDING`. Backtest **72395** · Paper **1526 PAPER_PASS**. 17579 inactive. UBA1381 link 0. LIVE OFF. KIWOOM/UPBIT LIVE 주문 Δ0. Next=`KIWOOM STRATEGY 17579 ACTIVATION AND UBA1381 LINK READINESS`.
**Ops (2026-08-19 SUPERSEDED):** TRACK K `KIWOOM_SOURCE_STRATEGY_PAPER_VALIDATION_PASSED_DERIVED_REVALIDATION_REQUIRED`. Paper policy **1.0.0**. run **1525** → **PAPER_PASS** (17486 only). **17579** inherited_as_pass=false. UBA1381 link 0. LIVE OFF. 주문 Δ0. Next=`KIWOOM DERIVED STRATEGY 17579 BACKTEST AND PAPER REVALIDATION`.
**Ops (2026-08-19 SUPERSEDED):** TRACK K `KIWOOM_STRATEGY_OWNERSHIP_ALIGNED_FOR_UBA1381`. 17486 유지(user7 PRIVATE). derived **17579** user61 PRIVATE inactive. UBA1381 link 0. LIVE OFF. 주문 Δ0. Next=`KIWOOM PAPER VALIDATION ACCEPTANCE POLICY IMPLEMENTATION`.
**Ops (2026-08-19 SUPERSEDED):** TRACK K `KIWOOM_KRX_PAPER_REPLAY_EVIDENCE_READY_POLICY_PENDING`. Paper run **1525** (034310, account 5251). Backtest 72376 ≠ Paper. acceptance policy 없음. LIVE OFF. KIWOOM REAL Δ0. Next=`KIWOOM STRATEGY OWNERSHIP ALIGNMENT FOR UBA1381`.
**Ops (2026-08-19 SUPERSEDED):** TRACK K `KIWOOM_KRX_PAPER_HISTORICAL_REPLAY_NOT_IMPLEMENTED`. 17486 Backtest PASS ≠ Paper. historical replay path 없음. LIVE OFF. KIWOOM REAL 주문 Δ0. Next=`KIWOOM PAPER HISTORICAL REPLAY IMPLEMENTATION`.
**Ops (2026-08-19 SUPERSEDED):** TRACK K `KIWOOM_KRX_STRATEGY_BACKTEST_PASSED_PAPER_PENDING`. Draft 315 approved · Definition 17486 · Backtest 72376 PASS. Paper 0. UBA1381 link 0. LIVE OFF. 주문 Δ0. Next=`KIWOOM KRX PAPER TRADING VALIDATION (HISTORICAL/REPLAY ONLY)`.
**Ops (2026-08-19 SUPERSEDED):** TRACK K `KIWOOM_KRX_STRATEGY_DRAFT_AWAITING_HUMAN_APPROVAL`. Promotion #1 COMPLETED · commit actor admin:565 · new result 875 · lifecycle 24142 PROMOTED · Strategy Request 23766 APPROVED · Draft 251 DRAFT. Backtest/Paper/Definition/UBA1381 link 0. LIVE OFF. 주문 Δ0. Next=`KIWOOM KRX STRATEGY DRAFT HUMAN APPROVAL WITH BACKTEST-BEFORE-DEFINITION`.
**Ops (2026-08-19 SUPERSEDED):** TRACK K `KIWOOM_KRX_PROMOTION_FULLY_APPROVED_COMMIT_READY`. Promotion #1 COMMIT_PENDING · FIRST admin:564 · FINAL admin:565 · commit 0 · lifecycle 0. dry-run JSONB Decimal fix + uvicorn restart 1. 주문 Δ0. Next=`KIWOOM KRX PROMOTION COMMIT AND STRATEGY LIFECYCLE CONTINUATION`.
**Ops (2026-08-19 SUPERSEDED):** TRACK K `KIWOOM_PROMOTION_APPROVERS_PROVISIONED_READY_FOR_HUMAN_APPROVAL`. POST `/api/v1/users`로 admin 2명 생성 (`promotion_admin_first` id=564, `promotion_admin_final` id=565). login token_present. Promotion #1 DRAFT · approve/commit 0. 주문 Δ0. Next=`KIWOOM KRX HUMAN FIRST AND FINAL PROMOTION APPROVAL`.
**Ops (2026-08-19 SUPERSEDED):** MASTER `KIWOOM_PROMOTION_INSUFFICIENT_APPROVERS` + `UPBIT_NEW_SYMBOL_STRATEGY_REQUIRED`. Promotion #1 DRAFT · 실 admin 1명(`admin:7`) · approve 0 · COMMIT_READY=NO. UBA1380 LIVE OFF · 17483=KRW-XRP only · scanner SHADOW_ONLY · positions 5/5 · max_order_amount=5100 · Activation/LIVE/ARM/Runner 미기동. XRP 유지. 주문 Δ0. Next=`PROVISION TWO ADDITIONAL REAL ADMIN USERS FOR PROMOTION FIRST/FINAL APPROVAL`.
**Ops (2026-08-19 SUPERSEDED):** TRACK K `KIWOOM_KRX_PROMOTION_AWAITING_HUMAN_APPROVAL` — queue_id=1 / candidate_result_id=872 / 034310 Promotion Request **id=1 DRAFT**. runtime keyword-only `is_expired` 로드 증명 후 POST 1회. approvals 0 · commit_eligible=false · lifecycle/Strategy Request/Draft 0. uvicorn restart 1 this STEP. TradingOrder/Outbox Δ0. UPBIT SAFE OFF 유지. Next=`KIWOOM KRX HUMAN PROMOTION APPROVAL`.
**Ops (2026-08-19 SUPERSEDED):** TRACK K `KIWOOM_KRX_PROMOTION_REQUEST_BLOCKED_AFTER_QUEUE_DECIDE` — schema/prompt ACTIVE 복구 · 034310 Assessment 16/17 VALIDATED · Consensus 1 APPROVED · Queue 1 decided. Promotion Request **0** (loaded promotion `is_expired` positional; disk already keyword-only; no 2nd uvicorn restart). 257720/114820 미진행. TradingOrder/Outbox Δ0. backend restart 1. UPBIT SAFE OFF (자동 복구 없음). Next=`KIWOOM KRX PROMOTION REQUEST CREATE`.
**Ops (2026-08-19 SUPERSEDED):** TRACK K `KIWOOM_KRX_CANDIDATES_REJECTED_BY_CANONICAL_ASSESSMENT` — post-close pipeline PID13604→47.4% then completion→**64.79% ge60** (753312 rows). quality PASS · trade_value unit 0 bad. rescan run_id=4 **selected=3** (034310·257720·114820). REAL WS market tick contract NOT FOUND — no src patch. UPBIT #19 EXPIRED (LIVE OFF · ARM EXPIRED; Worker/Exit RUNNING · Strategy Runtime PAUSED · Runner fail-closed BLOCKED) · order Δ0 · restart 0. Next=`AI STOCK_CANDIDATE_ASSESSMENT prompt/schema 활성 복구 후 KIWOOM KRX 후보 파이프라인 재실행`.
**Ops (2026-08-19 SUPERSEDED):** TRACK K `KIWOOM_KRX_TRADE_VALUE_FIXED_NO_CANDIDATE` — ka10081 `trde_prica` 백만원→parser ×1e6→KRW backfill 256627행. dry liquidity 1012→541 · trade_value 1012→379. rescan run_id=4 selected=0. src WIP · reload 1. UPBIT #19 유지. Next=`KIWOOM KRX DAILY COLLECTION CONTINUATION`.
**Ops (2026-08-19 SUPERSEDED):** TRACK K `KIWOOM_KRX_DAILY_COVERAGE_EXPANDED_NO_CANDIDATE` — daily ≥60 80→1012 · coverage 23.85% · rescan selected=0. trade_value 단위(백만원급 저장 vs 원 규칙) 불일치. src/reload 0. UPBIT #19 유지. Next=`KIWOOM KRX DAILY PIPELINE MAINTENANCE PATCH`.
**Ops (2026-08-19 SUPERSEDED):** TRACK K `KIWOOM_KRX_DATA_SYNC_COMPLETED_NO_CANDIDATE` — continuation STEP에서 coverage 확대·rescan 수행.
**Ops (2026-08-19 SUPERSEDED):** TRACK U `UPBIT_UBA1380_OPERATIONAL_RESTORED` after KIWOOM maintenance — Next=`KIWOOM KRX INSTRUMENT AND DAILY SYNC EXECUTION` 는 본 STEP에서 수행 완료.
**Ops (2026-08-19 SUPERSEDED):** TRACK K `KIWOOM_KRX_DATA_PIPELINE_READY_FOR_MAINTENANCE_WINDOW` — collector 없음은 구상태. ka10099/sync API src 적용·로드됨. production sync는 다음 STEP.
**Ops (2026-08-19):** TRACK U `UPBIT_UBA1380_OPERATIONAL_RESTORED` — fail-closed 이후 UBA1380 스택 복구. #19 EXPIRED · LIVE OFF · ARM EXPIRED · Worker/Exit RUNNING · Strategy Runtime PAUSED (Runner fail-closed BLOCKED). 주문 Δ0 (XRP dust pre-persist BLOCK). src 0 · KIWOOM 0. Next=`KIWOOM UBA1381 LIVE/MOCK SOURCE-OF-TRUTH ALIGNMENT`.
**Ops (2026-08-19):** TRACK K `KIWOOM_MULTI_UBA_LIVE_EXECUTION_ARCHITECTURE_READY_WITH_LIMITATIONS` — Manager `(uba, broker)`. targeted pytest 129 passed. 주문 Δ0. 신규 코드 로드로 startup fail-closed → UBA1380 LIVE/ARM OFF · Worker STOPPED · Runtime 17483 PAUSED. Next=`APPROVED UPBIT UBA1380 OPERATIONAL RESTORE`. KIWOOM START 금지.  
**Ops (2026-08-19):** TRACK K `KIWOOM_REALTIME_AUTOTRADING_BLOCKED` — KRX OPEN READ-ONLY. UPBIT #19 유지 · MUTATION 0. 단일 LIVE Runner는 UBA1380 전용.  
**Ops (2026-08-19):** OBSERVABILITY TIMEOUT FAIL-SAFE + FINAL RESTART `UPBIT_REALTIME_AUTOTRADING_LIVE_EXECUTION_OPERATIONAL` — Activation #19 EXPIRED · LIVE OFF · ARM EXPIRED · Worker/Exit RUNNING · Strategy Runtime PAUSED · Runner fail-closed BLOCKED. 주문 Δ0 (XRP dust). 24x7 timeout 0. NEXT=NONE. COMPLETED 유지.
**Ops (2026-08-19):** FINAL CONTROLLED RESTART `UPBIT_REALTIME_AUTOTRADING_LIVE_EXECUTION_ROLLED_BACK` — observe HTTP timeout 후 rollback. 주문 Δ0, dust blocked=2. COMPLETED 유지.  
**Ops (2026-08-19):** SIGNAL-TO-ORDER SAFETY FIX `UPBIT_LIVE_SIGNAL_ORDER_SAFETY_FIX_READY_WITH_LIMITATIONS` — UPBIT dispatch broker-scoped flag + outstanding SELL 중복 EXIT 차단. Activation #16 DISABLED · LIVE/ARM OFF. 재가동 금지. COMPLETED 유지.  
**Ops (2026-08-19):** LIVE Execution Runner START → 자연 STOP_LOSS TradingOrder 3건 생성 후 Outbox `LIVE_MOCK_CONFLICT`로 FAILED(broker 0). duplicate SELL로 Runner STOP. COMPLETED 유지.  
**Ops (2026-08-19):** ACTUAL-RUN DIAGNOSTIC `UPBIT_REALTIME_AUTOTRADING_ORDER_PATH_BLOCKED` — ExecutionRunner NOT RUNNING. COMPLETED 유지.  
**Ops (2026-08-18):** TRACK U **FREEZE** — `UPBIT_IMPLEMENTATION_STATUS=COMPLETED` · `UPBIT_UBA1380_IMPLEMENTATION_COMPLETED_AND_OPERATIONAL` · UBA1380 controlled 24x7 session (Activation 15, TTL 8h). 추가 UPBIT 개발 STEP 없음.  
**Ops (2026-08-18):** TRACK U go-live `UPBIT_24X7_AUTO_TRADING_GO_LIVE_SUCCESS_WITH_LIMITATIONS` (세션 가동 중). HEARTBEAT_STALE은 maintenance.  
**Ops (2026-08-18):** TRACK U 24x7 Runtime/Outbox control **`UPBIT_24X7_RUNTIME_OUTBOX_CONTROL_READY_WITH_LIMITATIONS`** (선행, 운영 반영).  
**Ops (2026-08-18):** TRACK U LIVE position exit monitor — go-live 시 `POSITION_EXIT_MONITOR_LIVE_UPBIT_ENABLED=true`.  
**Ops (2026-08-16):** Upbit Long-active termination **CLOSED** (selective commit) · Coverage/TP CLOSED_KEEP_6 · K credential **WAITING_FOR_USER_INPUT** · LIVE **NOT APPROVED**.  
**News (2026-08-14):** STEP N10 observation/coverage — natural MATCHED completed 1/20 · NO_NEWS 13/20; funnel drop 주원인 `NO_SYMBOL_OVERLAP`; Top-N Snapshot **OBSERVE_MORE** (미구현); look-ahead/threshold 유지. Baseline note: MATCHED 2/20 · NO_NEWS 22/20+ accumulating.

---

## 1. 종합 판정

| 지표 | 값 |
|------|-----|
| **UPBIT UBA1380 자동매매** | **COMPLETED** (`GO_LIVE_SUCCESS_WITH_LIMITATIONS`, CONTROLLED 24X7 SESSION) |
| 개발 구현률 (플랫폼 기타) | 추정치는 UPBIT 완료를 되돌리지 않음 |
| Paper 자동매매 준비도 | **PARTIAL** (P0-5 등 플랫폼 잔여) |
| KIWOOM LIVE | **NOT APPROVED** (다음 KRX OPEN 별도) |
| 자동매매 운영 가능 | UPBIT UBA1380 구현 **COMPLETED** / 현재 프로세스 **OPERATIONAL (UBA1380 restored)** / 플랫폼 기타 **NOT READY** |
| LIVE 거래 | UBA1380 session **RESTORED** (Activation #19 ACTIVE, LIVE ON, ARM ACTIVE) · 플랫폼 전체(P0·KIWOOM) **NOT APPROVED** |
| Paper 무인 자동매매 | **PARTIAL** (Outbox auto-fill 코드 경로 추가, E2E 미완) |

### 완료 상태 값 (영역 표용)

`COMPLETE` · `COMPLETE_WITH_LIMITATIONS` · `PARTIAL` · `DISCONNECTED` · `MOCK_ONLY` · `PAPER_ONLY` · `LIVE_UNVERIFIED` · `STUB_ONLY` · `LEGACY` · `NOT_IMPLEMENTED` · `UNKNOWN`

### 커밋 상태 값

`COMMITTED_BASELINE` · `WORKTREE_IMPLEMENTED_UNCOMMITTED` · `VERIFIED_BY_TEST` · `PARTIALLY_VERIFIED` · `DOCUMENTED_ONLY` · `NOT_IMPLEMENTED`

### UPBIT 완료 분리

| 층 | 상태 |
|----|------|
| **[A] COMPLETED** | UBA1380 automatic trading · 24x7 runtime · live safety · risk · outbox · exit · controlled go-live |
| **[B] OPERATIONS** | Activation/ARM session renewal · runtime/worker 감시 · 자연 주문 감시 |
| **[C] MAINTENANCE / OPTIONAL** | health/heartbeat/UI/Telegram/AI Gate/Scanner LIVE/AUTO RE-ARM — 완료율을 낮추지 않음 |

---

## 2. P0 Blocking (고정)

| ID | 내용 | 영향 | 상태 (2026-08-01) |
|----|------|------|-------------------|
| **P0-1** | Realtime broker hardcode | 잘못된 Outbox enqueue | **코드 수정(미커밋)** |
| **P0-2** | Kiwoom Fill → TradingOrder | LIVE 장부 불일치 | **WS/Mock/Recovery K_ONLY ensure (WT)**; ledger 시맨틱 SHARED 미변경 · account sync wipe 잔여 |
| **P0-3** | READY_* ↔ Runtime ACTIVE | 승인≠실행 | **명시 Promote(미커밋)**; Runner OFF |
| **P0-4** | Alembic Git/Head | 배포 스키마 | **DONE** `a7f3e91c4d28` |
| **P0-5** | Paper Outbox auto-fill | Paper E2E 단절 | **코드 수정(미커밋)** |

→ [ROADMAP.md](ROADMAP.md)

---

## 3. 환경별

| 환경 | 구현 | 연결 | 준비도 | 비고 |
|------|------|------|--------|------|
| Kiwoom MOCK | `MOCK_ONLY` | PARTIAL | 낮음 | mockapi 경로 |
| Kiwoom LIVE | `LIVE_UNVERIFIED` | `DISCONNECTED` (Fill/RT) | **~낮음** | RT 시세 없음; P0-2 |
| Upbit LIVE | `COMPLETE_WITH_LIMITATIONS` | PARTIAL | 중간 | P0-1; LIVE gate |
| Stock Paper | `PAPER_ONLY` | PARTIAL | ~72%대 | P0-5 |
| Crypto Paper | `PAPER_ONLY` | PARTIAL | ~72%대 | P0-5 |

---

## 4. 영역별 표

| 영역 | 구현 상태 | 커밋 상태 | 연결 상태 | 테스트 | Paper | LIVE | Blocking | 근거 | 다음 작업 |
|------|-----------|-----------|-----------|--------|-------|------|----------|------|-----------|
| 공통 Startup/Auth | COMPLETE_WITH_LIMITATIONS | COMMITTED_BASELINE | CONNECTED | PARTIALLY_VERIFIED | OK | fail-closed | — | `api/lifecycle.py` | — |
| 회원·UBA·Vault | COMPLETE_WITH_LIMITATIONS | WORKTREE (soft-delete/FK) | CONNECTED | PARTIALLY_VERIFIED | OK | OK | P0-4 | trading/account* | migration 커밋 경계 |
| Market Data | PARTIAL | COMMITTED_BASELINE | PARTIAL | PARTIALLY_VERIFIED | 일봉/Upbit | Kiwoom RT 없음 | — | realtime/, collectors | KRX RT 결정 |
| Candidate/AI STEP11 | COMPLETE_WITH_LIMITATIONS | COMMITTED_BASELINE | CONNECTED | VERIFIED_BY_TEST | N/A | N/A | — | ai/candidate_* | — |
| Strategy Lifecycle STEP12 | PARTIAL | WORKTREE_IMPLEMENTED_UNCOMMITTED | GATED (실행 WRITE 0) | VERIFIED_BY_TEST (워킹트리) | N/A gate | N/A | P0-3, P0-4 | ai/strategy_* | Canonical doc + 커밋 |
| Backtest | COMPLETE_WITH_LIMITATIONS | COMMITTED + WIP STEP12 | Runtime 미연동 | PARTIALLY_VERIFIED | N/A | N/A | — | backtest/ | — |
| Risk/Kill | COMPLETE_WITH_LIMITATIONS | Kiwoom settlement-aware equity V2 (WT→commit) | CONNECTED | VERIFIED_BY_TEST | OK | mid-day V1 legacy | cash-flow GAP | risk/ + kiwoom/equity_policy | next-day V2 baseline |
| Scoped Runtime | COMPLETE_WITH_LIMITATIONS (UBA1380 17483 RUNNING) | WORKTREE | STEP12와 분리 | VERIFIED_BY_TEST | 수동 | operator START 완료 | P0-3 (KIWOOM/STEP12) | strategy runtime + upbit_24x7_control | [B] 세션 감시 |
| Order/Outbox | COMPLETE_WITH_LIMITATIONS | WORKTREE | CONNECTED | VERIFIED_BY_TEST | PARTIAL | UBA1380 Worker RUNNING | P0-1 (realtime 기타) | outbox_dispatch_safety, upbit_24x7_control | [B] Worker 감시 |
| Fill/Position | PARTIAL | COMMITTED_BASELINE | Upbit OK / Kiwoom GAP / Paper GAP | PARTIALLY_VERIFIED | P0-5 | P0-2 | P0-2,P0-5 | fill sync, paper | Fill 파이프라인 |
| Settlement/PnL | PARTIAL | WORKTREE FK | PARTIAL | PARTIALLY_VERIFIED | PARTIAL | PARTIAL | P0-4 | settlement/ | FK 커밋 |
| Recovery/Reconcile | COMPLETE_WITH_LIMITATIONS | COMMITTED_BASELINE | Upbit>Kiwoom | PARTIALLY_VERIFIED | OK | PARTIAL | P0-2 | recovery/ | Kiwoom reconcile |
| Frontend | COMPLETE_WITH_LIMITATIONS | **MENU_CONSOLIDATION_CLOSE=YES**; COV coverage remediation CLOSED (FE 미변경); Ambiguous/rowKey WIP residual | PARTIAL stubs | PARTIALLY_VERIFIED | UI | UI | — | frontend/ | SHADOW 52 PRECHECK · News 누적 · WIP 별도 |
| Ops/Telegram | COMPLETE_WITH_LIMITATIONS | COMMITTED_BASELINE | RO 명령 | PARTIALLY_VERIFIED | OK | 제한 | — | telegram/ | — |
| Docs Canonical | COMPLETE (PHASE2) | NEW | — | link check | — | — | — | docs/* | PHASE3 archive |

---

## 5. 자동매매 완성 체크 (요약)

| 조건 | Paper | LIVE |
|------|-------|------|
| 시세 | 부분 | Upbit 가능 / Kiwoom RT 불가 |
| Runtime 자동 연결 | 아니오 (수동) | 아니오 |
| Risk → Order → Outbox | 경로 존재 | 경로 존재 + P0-1 |
| Fill → Position | 부분 (P0-5) | Upbit 양호 / Kiwoom 갭 (P0-2) |
| Full E2E 테스트 | 아니오 | 아니오 |

**결론:** UPBIT UBA1380 자동매매 구현은 **COMPLETED**. 세션 만료·heartbeat observability·UI/Telegram은 [B] OPERATIONS / [C] MAINTENANCE이며 완료 상태를 낮추지 않는다. KIWOOM·P0 잔여는 별 트랙.

---

## 6. 유지관리

STEP/기능 완료 시 본 문서 + [CURRENT_WORK.md](CURRENT_WORK.md) + [STEP_MASTER_STATUS.md](STEP_MASTER_STATUS.md) + [ROADMAP.md](ROADMAP.md)를 함께 갱신한다.
