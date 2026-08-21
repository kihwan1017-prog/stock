# STEP_MASTER_STATUS

**역할:** STEP 관리의 **유일한** Source of Truth.  
**규칙:** 같은 숫자라도 네임스페이스가 다르면 **합치지 않는다.** 과거 번호를 삭제·재부여하지 않고 Mapping만 제공한다.  
**최종 갱신:** 2026-08-21 (KIWOOM SETTLEMENT-AWARE DAILY LOSS)  
**Ops note (2026-08-21):** TRACK K `KIWOOM_SETTLEMENT_AWARE_DAILY_LOSS_IMPLEMENTED`. V2 equity generic; today baseline V1 mid-day safe; ENTRY still BLOCKED. Next=`APPLY MIGRATION + RELOAD ON NEXT KRX DAY (V2 BASELINE); DO NOT REWRITE TODAY BASELINE`.
**Ops note (2026-08-21 SUPERSEDED):** SHARED `STRATEGY_CANDIDATE_UX_CONSOLIDATION_COMPLETE` @ `74c78d4`. Admin 전략·후보 leaf 5 Workspace. UBA1380 Runtime READ-ONLY 불변. Destructive cleanup 없음.
**Ops note (2026-08-20 SUPERSEDED):** TRACK U `UPBIT_FULL_MARKET_AUTOTRADING_READY_TO_ENABLE`. Next exactly one: **ENABLE UBA1380 FULL MARKET AUTO MODE FROM ADMIN UI**. FIXED_SYMBOL default · Enable 0 · REAL Δ0 · UBA1381 0.
**Ops note (2026-08-20 SUPERSEDED):** TRACK K `KIWOOM_UBA1381_LIVE_DEPLOYMENT_BLOCKED_LIFECYCLE`. Next exactly one: **KIWOOM UBA1381 STRATEGY PROMOTION DECISION PACKAGE**. STEP12 NOT_PROMOTED · LIVE deployment 0. Activation #20 ACTIVE ~13:51 KST. UPBIT cooldown 별도 STEP.
**Ops note (2026-08-20 SUPERSEDED):** TRACK K `KIWOOM_UBA1381_RUNTIME_START_FAILED`. Next exactly one: **KIWOOM UBA1381 LIVE STRATEGY DEPLOYMENT**. 17579 ACTIVE LIVE deployment 0. Activation #20 ACTIVE ~13:51 KST. UPBIT cooldown 별도 STEP.
**Ops note (2026-08-20 SUPERSEDED):** TRACK K `KIWOOM_UBA1381_REARMED_READY_FOR_RUNTIME_START`. Next exactly one: **KIWOOM UBA1381 RUNTIME START**. ARM TTL ~11:28:01 KST. Activation #20 ACTIVE ~13:51 KST. UPBIT cooldown 별도 STEP.
**Ops note (2026-08-20 SUPERSEDED):** TRACK K `KIWOOM_UBA1381_ACCOUNT_SYNCED_READY_FOR_REARM`. Next exactly one: **KIWOOM UBA1381 RE-ARM**. Runtime START 미실행. Activation #20 ACTIVE ~13:51 KST. UPBIT cooldown 별도 STEP.
**Ops note (2026-08-20 SUPERSEDED):** TRACK K `KIWOOM_UBA1381_LIVE_ON_READY_FOR_ACCOUNT_SYNC`. Next exactly one: **KIWOOM UBA1381 ACCOUNT SYNC / RECONCILIATION**. ARM/Runtime 미실행. Activation #20 ACTIVE ~13:51 KST. UPBIT cooldown 별도 STEP.
**Ops note (2026-08-20 SUPERSEDED):** TRACK K `KIWOOM_UBA1381_REARM_BLOCKED_LIVE`. Next exactly one: **KIWOOM UBA1381 LIVE ON**. 재-ARM/Runtime START 미실행. Activation #20 ACTIVE ~13:51 KST. UPBIT cooldown 별도 STEP.
**Ops note (2026-08-20 SUPERSEDED):** TRACK K `KIWOOM_UBA1381_ARMED_READY_FOR_RUNTIME_PRECHECK`. Next exactly one: **KIWOOM UBA1381 RUNTIME START READINESS**. Runtime START 미실행. ARM TTL ~10:31:30 KST. UPBIT cooldown 별도 STEP.
**Ops note (2026-08-20 SUPERSEDED):** TRACK K `KIWOOM_UBA1381_ARM_READY`. Next exactly one: **KIWOOM UBA1381 ARM ON**. Runtime/Runner/실주문은 이후 STEP. UPBIT cooldown 별도 STEP.
**Ops note (2026-08-20 SUPERSEDED):** TRACK K `KIWOOM_UBA1381_LIVE_ON_READY_FOR_ARM`. Next=`KIWOOM UBA1381 ARM READINESS`. UPBIT cooldown 별도 STEP.
**Ops note (2026-08-20 SUPERSEDED):** TRACK K `KIWOOM_LIVE_ACTIVATION_READY_REACTIVATION_REQUIRED`. #13 재사용 금지. LIVE ON 금지. Next=`KIWOOM UBA1381 LIVE ACTIVATION CREATE`. UPBIT cooldown은 별도 STEP.
**Ops note (2026-08-20 SUPERSEDED):** TRACK K `KIWOOM_KRX_REAL_MARKET_DATA_TICK_PROVEN_LIVE_PRECHECK_PENDING`. 장중 REAL 0B tick proven (034310). LIVE ON 금지. Next=`KIWOOM LIVE ACTIVATION READINESS`. UPBIT cooldown은 별도 STEP.
**Ops note (2026-08-20 SUPERSEDED):** TRACK U `UPBIT_REMOTE_SELL_ORDERS_CANCELLED_COOLDOWN_ALIGNMENT_PENDING`. wait=0. GO_LIVE_READY=NO (cooldown). START 0. Next=`UPBIT KRW-SOL LIVE COOLDOWN ALIGNMENT` (09:00 이후 KIWOOM OPEN tick 우선). KIWOOM FREEZE until KRX OPEN tick validation.
**Ops note (2026-08-20 SUPERSEDED):** TRACK U `UPBIT_REMOTE_OPEN_ORDER_SAFETY_ALIGNED_CANCELLATION_APPROVAL_REQUIRED`. remote wait=3 CANCEL 0. ENTRY open-order SoT에 unmapped remote 포함. START 0. Next=`UPBIT EXTERNAL REMOTE SELL ORDER CANCELLATION APPROVAL`. KIWOOM FREEZE until KRX OPEN tick validation.
**Ops note (2026-08-20 SUPERSEDED):** TRACK U `UPBIT_KRW_SOL_RUNTIME_APPROVAL_GATE_ALIGNED_REMOTE_ORDERS_PENDING`. PRIVATE evidence gate. catalog approve 0. `STRATEGY_NOT_APPROVED` 제거. GO_LIVE_READY=NO. START 0. Next=`UPBIT REMOTE PENDING ORDER RECONCILIATION`. KIWOOM FREEZE until KRX OPEN tick validation.
**Ops note (2026-08-20 SUPERSEDED):** TRACK U `UPBIT_KRW_SOL_LIVE_TIMEFRAME_ALIGNED_OTHER_BLOCKERS_REMAIN`. 1D LIVE MA aligned. GO_LIVE_READY=NO. START 0. Next=`UPBIT KRW-SOL STRATEGY LIVE APPROVAL ALIGNMENT`. KIWOOM FREEZE until KRX OPEN tick validation.
**Ops note (2026-08-20 SUPERSEDED):** TRACK U `UPBIT_KRW_SOL_LIVE_TIMEFRAME_ALIGNMENT_REQUIRED`. 1D Backtest/Paper vs LIVE tick MA. GO_LIVE_READY=NO. START 0. Next=`UPBIT KRW-SOL LIVE TIMEFRAME ALIGNMENT IMPLEMENTATION`. KIWOOM FREEZE until KRX OPEN tick validation.
**Ops note (2026-08-20 SUPERSEDED):** TRACK U `UPBIT_KRW_SOL_STRATEGY_ACTIVATED_AND_LINKED_LIVE_PRECHECK_PENDING`. 17580 active · link 2357 UBA1380. 17483/2354 유지. LIVE/ARM/Runtime 0. Next=`UPBIT NEW-SYMBOL CONTROLLED LIVE ACTIVATION PRECHECK`. KIWOOM FREEZE until next KRX OPEN tick validation.
**Ops note (2026-08-20 SUPERSEDED):** TRACK U `UPBIT_KRW_SOL_STRATEGY_VALIDATED_ACTIVATION_PENDING`. Paper 1528 PASS. 17580 inactive. Activation/link 금지(별도 STEP). Next=`UPBIT KRW-SOL STRATEGY ACTIVATION AND UBA1380 LINK READINESS`. KIWOOM FREEZE until next KRX OPEN tick validation.
**Ops note (2026-08-20 SUPERSEDED):** TRACK U `UPBIT_SELECTED_NEW_SYMBOL_REJECTED_BY_PAPER`. SOL 17580 Paper 1527 not PASS. clone/LIVE 추가 금지. Next=`STOP`. KIWOOM FREEZE until next KRX OPEN tick validation.
**Ops note (2026-08-19 SUPERSEDED):** TRACK K `KIWOOM_REAL_MARKET_DATA_RUNTIME_READY_NEXT_SESSION_TICK_PROOF_PENDING`. 0B LOGIN/REG ACK. tick proof 다음 OPEN. LIVE OFF. KIWOOM REAL Δ0. Next=`KIWOOM KRX OPEN REAL MARKET DATA TICK VALIDATION`.
**Ops note (2026-08-19 SUPERSEDED):** TRACK K `KIWOOM_STRATEGY_17579_ACTIVATED_AND_LINKED_REALTIME_BLOCKED`. 17579 active · link 2356. LIVE OFF. REAL WS blocker. KIWOOM REAL Δ0. Next=`KIWOOM REAL MARKET DATA RUNTIME IMPLEMENTATION`.
**Ops note (2026-08-19 SUPERSEDED):** TRACK K `KIWOOM_DERIVED_STRATEGY_17579_VALIDATED_ACTIVATION_PENDING`. 17579 Backtest 72395 · Paper 1526 PASS. inactive. UBA1381 link 0. KIWOOM REAL Δ0. Next=`KIWOOM STRATEGY 17579 ACTIVATION AND UBA1381 LINK READINESS`.
**Ops note (2026-08-19 SUPERSEDED):** TRACK K `KIWOOM_SOURCE_STRATEGY_PAPER_VALIDATION_PASSED_DERIVED_REVALIDATION_REQUIRED`. 17486 Paper **1525 PASS**. 17579 재검증 필수. UBA1381 link 0. KIWOOM REAL Δ0. Next=`KIWOOM DERIVED STRATEGY 17579 BACKTEST AND PAPER REVALIDATION`.
**Ops note (2026-08-19 SUPERSEDED):** TRACK K `KIWOOM_STRATEGY_OWNERSHIP_ALIGNED_FOR_UBA1381`. derived 17579 owner 61. UBA1381 link 0. KIWOOM REAL Δ0. Next=`KIWOOM PAPER VALIDATION ACCEPTANCE POLICY IMPLEMENTATION`.
**Ops note (2026-08-19 SUPERSEDED):** TRACK K `KIWOOM_KRX_PAPER_REPLAY_EVIDENCE_READY_POLICY_PENDING`. Paper **1525** evidence ready · acceptance policy 없음. KIWOOM REAL Δ0. Next=`KIWOOM STRATEGY OWNERSHIP ALIGNMENT FOR UBA1381`.
**Ops note (2026-08-19 SUPERSEDED):** TRACK K `KIWOOM_KRX_PAPER_HISTORICAL_REPLAY_NOT_IMPLEMENTED`. Paper validation evidence 0. KIWOOM REAL Δ0. Next=`KIWOOM PAPER HISTORICAL REPLAY IMPLEMENTATION`.
**Ops note (2026-08-19 SUPERSEDED):** TRACK K `KIWOOM_KRX_STRATEGY_BACKTEST_PASSED_PAPER_PENDING`. Definition 17486 · Backtest 72376 PASS · Paper 0. 주문 Δ0. Next=`KIWOOM KRX PAPER TRADING VALIDATION (HISTORICAL/REPLAY ONLY)`.
**Ops note (2026-08-19 SUPERSEDED):** TRACK K `KIWOOM_KRX_STRATEGY_DRAFT_AWAITING_HUMAN_APPROVAL`. Promotion #1 COMPLETED · lifecycle PROMOTED · Request 23766 APPROVED · Draft 251 DRAFT. Backtest/Paper/Definition 0. 주문 Δ0. Next=`KIWOOM KRX STRATEGY DRAFT HUMAN APPROVAL WITH BACKTEST-BEFORE-DEFINITION`.
**Ops note (2026-08-19 SUPERSEDED):** TRACK K `KIWOOM_KRX_PROMOTION_FULLY_APPROVED_COMMIT_READY`. Promotion #1 dual-approved COMMIT_PENDING · commit POST 0. 주문 Δ0. Next=`KIWOOM KRX PROMOTION COMMIT AND STRATEGY LIFECYCLE CONTINUATION`.
**Ops note (2026-08-19 SUPERSEDED):** TRACK K `KIWOOM_PROMOTION_APPROVERS_PROVISIONED_READY_FOR_HUMAN_APPROVAL`. admin 564/565 생성 · Promotion #1 DRAFT · FIRST/FINAL POST 0. 주문 Δ0. Next=`KIWOOM KRX HUMAN FIRST AND FINAL PROMOTION APPROVAL`.
**Ops note (2026-08-19 SUPERSEDED):** MASTER `KIWOOM_PROMOTION_INSUFFICIENT_APPROVERS` + `UPBIT_NEW_SYMBOL_STRATEGY_REQUIRED`. Promotion #1 DRAFT · dual admin 부족. UPBIT 신규 symbol 경로 없음(17483 XRP-only · cap 5/5 · max_order 5100). LIVE/ARM/주문 0. Next=`PROVISION TWO ADDITIONAL REAL ADMIN USERS FOR PROMOTION FIRST/FINAL APPROVAL`.
**Ops note (2026-08-19 SUPERSEDED):** TRACK K `KIWOOM_KRX_PROMOTION_AWAITING_HUMAN_APPROVAL`. 034310 queue_id=1 · Promotion Request id=1 DRAFT · Human Approval Gate. uvicorn restart 1 this STEP · order Δ0. UPBIT SAFE OFF 자동 복구 없음. Next=`KIWOOM KRX HUMAN PROMOTION APPROVAL`.
**Ops note (2026-08-19 SUPERSEDED):** TRACK K `KIWOOM_KRX_PROMOTION_REQUEST_BLOCKED_AFTER_QUEUE_DECIDE`. 034310 Queue decided · Promotion Request 0 (loaded `is_expired` positional in promotion eligibility). backend restart 1 · order Δ0. UPBIT SAFE OFF 자동 복구 없음. Next=`KIWOOM KRX PROMOTION REQUEST CREATE`.
**Ops note (2026-08-19 SUPERSEDED):** TRACK K `KIWOOM_KRX_CANDIDATES_REJECTED_BY_CANONICAL_ASSESSMENT`. post-close daily ge60 **64.79%** · rescan selected=**3** · REAL WS market tick contract 미확인. UPBIT #19 EXPIRED · LIVE OFF · ARM EXPIRED · Worker/Exit RUNNING · Strategy Runtime PAUSED · Runner fail-closed BLOCKED · order Δ0 · restart 0. Next=`AI STOCK_CANDIDATE_ASSESSMENT prompt/schema 활성 복구 후 KIWOOM KRX 후보 파이프라인 재실행`.
**Ops note (2026-08-19 SUPERSEDED):** TRACK K `KIWOOM_KRX_TRADE_VALUE_FIXED_NO_CANDIDATE`. parser/backfill 완료 · rescan selected=0. src WIP · reload 1. UPBIT #19 유지. Next=`KIWOOM KRX DAILY COLLECTION CONTINUATION`.
**Ops note (2026-08-19 SUPERSEDED):** TRACK K `KIWOOM_KRX_DAILY_COVERAGE_EXPANDED_NO_CANDIDATE`. ge60 80→1012 · selected=0 · trade_value 단위 이슈. src/reload 0. UPBIT #19 유지. Next=`KIWOOM KRX DAILY PIPELINE MAINTENANCE PATCH`.
**Ops note (2026-08-19 SUPERSEDED):** TRACK K `KIWOOM_KRX_DATA_SYNC_COMPLETED_NO_CANDIDATE` — continuation/rescan 수행 완료.
**Ops note (2026-08-19 SUPERSEDED):** TRACK U restore Next=`KIWOOM KRX INSTRUMENT AND DAILY SYNC EXECUTION` — 수행 완료.
**Ops note (2026-08-19 SUPERSEDED):** TRACK K `KIWOOM_KRX_DATA_PIPELINE_READY_FOR_MAINTENANCE_WINDOW` — collector 없음은 구상태. ka10099 src는 적용됨. 수집은 다음 STEP.
**Ops note (2026-08-19):** TRACK U `UPBIT_UBA1380_OPERATIONAL_RESTORED`. #19 EXPIRED · LIVE OFF · ARM EXPIRED · Worker/Exit RUNNING · Strategy Runtime PAUSED (Runner fail-closed BLOCKED). 주문 Δ0 (dust BLOCK). Next=`KIWOOM UBA1381 LIVE/MOCK SOURCE-OF-TRUTH ALIGNMENT` (미수행).
**Ops note (2026-08-19):** TRACK K `KIWOOM_MULTI_UBA_LIVE_EXECUTION_ARCHITECTURE_READY_WITH_LIMITATIONS`. Next=`APPROVED UPBIT UBA1380 OPERATIONAL RESTORE`. KIWOOM START 금지. 주문 Δ0.  
**Ops note (2026-08-19):** TRACK K `KIWOOM_REALTIME_AUTOTRADING_BLOCKED` (KRX OPEN READ-ONLY). UPBIT isolation MUTATION=0. Next=`DO_NOT_TOUCH_UPBIT`.  
**Ops note (2026-08-19):** TRACK U OBSERVABILITY TIMEOUT FAIL-SAFE + FINAL RESTART `UPBIT_REALTIME_AUTOTRADING_LIVE_EXECUTION_OPERATIONAL`. Activation #19 EXPIRED · LIVE OFF · ARM EXPIRED · Strategy Runtime PAUSED. 주문 Δ0 (dust). Next=**NONE**.
**Ops note (2026-08-19):** TRACK U FINAL CONTROLLED RESTART `UPBIT_REALTIME_AUTOTRADING_LIVE_EXECUTION_ROLLED_BACK`. 주문 Δ0. rollback 완료.  
**Ops note (2026-08-19):** TRACK U SIGNAL-TO-ORDER SAFETY FIX `UPBIT_LIVE_SIGNAL_ORDER_SAFETY_FIX_READY_WITH_LIMITATIONS` — broker-scoped flag + outstanding SELL. 재START 금지. Next=`UPBIT REALTIME AUTOTRADING LIVE EXECUTION RESTART PRECHECK`.  
**Ops note (2026-08-19):** TRACK U LIVE Execution Runner START 후 자연 STOP_LOSS 주문 3건이 Outbox `LIVE_MOCK_CONFLICT`로 FAILED. duplicate SELL로 Runner STOP (`EXECUTION_ROLLED_BACK`).  
**Ops note (2026-08-19):** TRACK U **ACTUAL-RUN DIAGNOSTIC** `UPBIT_REALTIME_AUTOTRADING_ORDER_PATH_BLOCKED` — Runtime/Hub/Worker/Exit 살아 있음. `RealtimeExecutionRunner` **NOT RUNNING** (PAPER). 자연 자동주문 0. mutation=0.  

**상세 Mapping 원본:** [audit/STEP_NUMBER_MAPPING_20260731.md](audit/STEP_NUMBER_MAPPING_20260731.md)

**Ops note (2026-08-18):** TRACK U **FREEZE** `UPBIT_IMPLEMENTATION_STATUS=COMPLETED` · `UPBIT_UBA1380_IMPLEMENTATION_COMPLETED_AND_OPERATIONAL` · 추가 UPBIT 개발 STEP 없음. 세션 갱신은 [trading/UPBIT_UBA1380_24X7_SESSION_RENEWAL.md](trading/UPBIT_UBA1380_24X7_SESSION_RENEWAL.md).  
**Ops note (2026-08-18):** TRACK U go-live `UPBIT_24X7_AUTO_TRADING_GO_LIVE_SUCCESS_WITH_LIMITATIONS` (Activation 15 ACTIVE_SESSION).  
**Ops note (2026-08-18):** TRACK U **UPBIT 24X7 RUNTIME/OUTBOX CONTROL** `READY_WITH_LIMITATIONS` (선행, 운영 반영).  
**Ops note (2026-08-18):** TRACK U **UPBIT LIVE POSITION EXIT MONITOR** `READY_WITH_LIMITATIONS` → go-live 시 `live_upbit` **ON**.  
**Ops note:** U Long-active termination **CLOSED** (selective commit) · K credential waiting for UI user input · News ACCUMULATING.  
**News note:** `NEWS_AB_SAMPLE_ACCUMULATING` (MATCHED 3, NO_NEWS 30+10).

---

## 1. 네임스페이스

| Namespace | ID 접두 | 의미 | 위치 |
|-----------|---------|------|------|
| MAIN-STEP | `HIST-*` / archive STEP16–75 | 제품 연대기 | `docs/archive/steps/` |
| AUDIT-STEP | `AUDIT21-*` | 21단계 코드 감사 | `docs/audit/STEP01–21` |
| STRATEGY-STEP | `STRAT-12.*` | Strategy Lifecycle (현재) | 코드/tests + [architecture/STRATEGY_LIFECYCLE_STEP12.md](architecture/STRATEGY_LIFECYCLE_STEP12.md) |
| NEWS-STEP | `NEWS-N*` | UPBIT News/Notice 병렬 트랙 | `src/stock_platform/news/` |
| MENU-STEP | `MENU-M*` | Admin/User 메뉴 IA | `frontend/src/config/menu.tsx` + `docs/audit/MENU_*` |
| LEGACY-STEP / SUBSTEP | `DEV-8.*`, `AI-11.*`, `OPS-10.*` | 활성 서브시리즈 | development/ai/operations |
| REL | `REL-*` | 루트 릴리스 서술 | 루트 README_STEP* |

### 충돌 경고 (동일 숫자 ≠ 동일 기능)

| Label | AUDIT21 | MAIN/Archive | Canonical SUB |
|-------|---------|--------------|---------------|
| STEP8 | Risk/Kill 감사 | — | **DEV-8.*** 브로커/계좌/LIVE |
| STEP10 | Kiwoom 감사 | — | **OPS-10.*** Runtime/Ops |
| STEP11 | Upbit 감사 | — | **AI-11.*** Provider→Lifecycle (**커밋됨**) |
| **STEP12** | **Paper Trading 감사** (`AUDIT21-12`) | — | **STRAT-12.*** Strategy Request→Readiness (**워킹트리**) |

⚠️ **과거 Paper Audit STEP12** 와 **현재 Strategy Lifecycle STEP12** 를 절대 혼동하지 말 것.

---

## 2. 활성 시리즈 요약

| Canonical ID | Historical | 제목 | 상태 | 커밋 | Migration | Tests | 다음 Gate | 관련 문서 |
|--------------|------------|------|------|------|-----------|-------|-----------|-----------|
| AI-11.13 | STEP11-13 | Candidate Lifecycle | COMPLETE_WITH_LIMITATIONS | YES (`3554ef8`) | ae5f6a7b8c9d 계열 | test_step11_13 | 유지보수 | `docs/ai/` |
| STRAT-12.1 … 12.20 | STEP12-1…20 | Strategy Lifecycle | PARTIAL / GATED | **NO** (워킹트리) | 다수 → head `a7f3e91c4d28` (WT) | test_step12_* | 커밋 경계 + P0-3 | [STRATEGY_LIFECYCLE_STEP12.md](architecture/STRATEGY_LIFECYCLE_STEP12.md) |
| DEV-8.* | STEP8-5-* | 계좌·LIVE 안전 | COMPLETE_WITH_LIMITATIONS | YES | 포함 | 다수 | P0 보강 | `docs/development/` |
| AUDIT21-* | STEP01–21 | 코드 감사 | HISTORICAL | N/A | N/A | baseline | 수정 최소화 | `docs/audit/` |
| HIST-74/75 | STEP74/75 | v1.1 감사·패키징 | HISTORICAL | YES | N/A | — | CONDITIONAL | archive/steps |
| NEWS-N2 | STEP N2 | UPBIT News/Notice Collector | COMPLETE_WITH_LIMITATIONS | YES | none (reuse news.news_article) | test_step_n2_* | N3 Symbol Mapping | `src/stock_platform/news/` |
| NEWS-N3 | STEP N3 | News Symbol Mapping | READY_WITH_LIMITATIONS | YES | none (reuse news_article_symbol) | test_step_n3_* | N3.1 Quality | `symbol_resolver/mapper` |
| NEWS-N3.1 | STEP N3.1 | Mapping Quality Guard | NEWS_SYMBOL_MAPPING_QUALITY_READY | YES | none | test_step_n3_1_* | N4 AI News | `symbol_mapping_quality*` |
| NEWS-N4 | STEP N4 | AI News Analysis | READY_WITH_LIMITATIONS | YES (`e76ab57`) | m4n5o6p7q8r9 | test_step_n4_* | N5 Signal | `news_ai_analysis*` |
| NEWS-N5 | STEP N5 | News Signal Standardization | UPBIT_NEWS_SIGNAL_READY | YES (`f4d9549`) | n5o6p7q8r9s0 | test_step_n5_* | N6 Combined | `news_signal*` |
| NEWS-N6 | STEP N6 | News Combined Shadow A/B | READY_WITH_LIMITATIONS | YES (`eac2b66`) | o6p7q8r9s0t1 | test_step_n6_* | N7 누적 | `upbit_news_combined_shadow*` |
| NEWS-N7 | STEP N7 | News A/B Sample Accumulation | NEWS_AB_SAMPLE_ACCUMULATING | YES (`60a9969`) | none (reuse N6 table) | test_step_n7_* | N8 observation | diagnostics/scheduler/UI |
| NEWS-N8 | STEP N8 | News Pipeline Continuous Observation | NEWS_PIPELINE_OBSERVATION_RUNNING | YES (`74102ad`) | none | test_step_n8_* | N9 latency | pipeline_observation* |
| NEWS-N9 | STEP N9 | News Pipeline Latency Alignment | NEWS_PIPELINE_LATENCY_ALIGNED | YES (`622eb8d`) | none | test_step_n9_* | N10 | N4→N5 event trigger |
| NEWS-N10 | STEP N10 | News A/B Coverage Decision | NEWS_AB_SAMPLE_ACCUMULATING | YES | none | test_step_n10_* | 자연 누적 / REVIEW_READY | coverage_funnel + TopN rec |
| MENU-M1 | STEP M1 | Menu inventory | MENU_INVENTORY_READY | NO (docs WT) | none | — | M2 | `docs/audit/MENU_INVENTORY_*` |
| MENU-M2 | STEP M2 | Menu IA design | MENU_IA_DESIGN_READY | NO (docs WT) | none | — | M3-A | `docs/audit/MENU_IA_*` |
| MENU-M2.1 | STEP M2.1 | Menu IA delta | MENU_IA_DELTA_CLEAR | NO | none | — | M3-A | — |
| MENU-M3-A | STEP M3-A | LOW-RISK menu cleanup | MENU_LOW_RISK_CLEANUP_READY_WITH_LIMITATIONS | **YES** (`bab25d3`) | none | menu.test.ts | M3-B | `docs/audit/MENU_LOW_RISK_CLEANUP_M3A.md` |
| MENU-M3-B | STEP M3-B | Hidden strategy workflow 메뉴 승격 | MENU_M3B_READY_WITH_LIMITATIONS | **YES** (`90bbaef`) | none | menu.test.ts | M4-0 | `docs/audit/MENU_M3B_HIDDEN_WORKFLOW_PROMOTION.md` |
| MENU-M4-0 | STEP M4-0 | Admin operations consolidation precheck | OPERATIONS_CONSOLIDATION_DESIGN_READY | **YES** (with M4-A `62bd783`) | none | — | M4-A | `docs/audit/MENU_M4_OPERATIONS_PRECHECK.md` |
| MENU-M4-A | STEP M4-A | READ-only ops labels/cross-links | MENU_M4A_READY_WITH_LIMITATIONS | **YES** (`62bd783`; risk page WIP 제외) | none | menu/ops tests | M4-B | `docs/audit/MENU_M4A_OPERATIONS_READONLY_CONSOLIDATION.md` |
| MENU-M4-B | STEP M4-B | Admin ops menu regroup | MENU_M4B_READY_WITH_LIMITATIONS | **YES** (`e045c63`) | none | menu.test.ts | M4-C0 | `docs/audit/MENU_M4B_OPERATIONS_MENU_REGROUP.md` |
| MENU-M4-C0 | STEP M4-C0 | LIVE/ARM canonical precheck | LIVE_CONTROL_CANONICAL_DESIGN_READY | **YES** (with M4-C 본 커밋) | none | — | M4-C | `docs/audit/MENU_M4C_LIVE_CONTROL_CANONICAL_PRECHECK.md` |
| MENU-M4-C | STEP M4-C | LIVE/ARM panel single-mount | LIVE_CONTROL_SINGLE_MOUNT_READY_WITH_LIMITATIONS | **YES** (`85c3552`) | none | upbitLiveControlSingleMount.test.ts | M4-C2 | `docs/audit/MENU_M4C_LIVE_CONTROL_SINGLE_MOUNT.md` |
| MENU-M4-C2 | STEP M4-C2 | Risk LIVE duplicate precheck | RISK_LIVE_DUPLICATE_CONFIRMED | **YES** (with APPLY 본 커밋) | none | — | M4-C2-APPLY | `docs/audit/MENU_M4C2_RISK_LIVE_DUPLICATE_PRECHECK.md` |
| MENU-M4-C2-APPLY | STEP M4-C2-APPLY | Risk LIVE/ARM mutation 제거 | RISK_LIVE_CONTROL_SINGLE_SURFACE_READY_WITH_LIMITATIONS | **YES** (본 커밋 · title/ops-link WIP 잔여 WT) | none | riskLiveControlSingleSurface.test.ts | WIP residual OK | `docs/audit/MENU_M4C2_RISK_LIVE_CONTROL_CLEANUP.md` |
| MENU-M5-0 | STEP M5-0 | Upbit Hub consolidation precheck | UPBIT_HUB_DESIGN_READY_WITH_LIMITATIONS | **YES** (with M5-A 본 커밋) | none | — | M5-A | `docs/audit/MENU_M5_UPBIT_HUB_PRECHECK.md` |
| MENU-M5-A | STEP M5-A | Upbit Hub Tab shell + reorder | UPBIT_HUB_TAB_SHELL_READY_WITH_LIMITATIONS | **YES** (`285b521` · pushed) | none | upbitHubTabs.test.ts | M5-B0 | `docs/audit/MENU_M5A_UPBIT_HUB_TAB_SHELL.md` |
| MENU-M5-B0 | STEP M5-B0 | Technical tab structure precheck | TECHNICAL_TAB_SECTION_REORGANIZE | **YES** (with M5-B 본 커밋) | none | — | M5-B | `docs/audit/MENU_M5B_TECHNICAL_TAB_PRECHECK.md` |
| MENU-M5-B | STEP M5-B | Technical section reorder | TECHNICAL_SECTION_REORGANIZE_READY_WITH_LIMITATIONS | **YES** (`c1af96e`) | none | upbitTechnicalSectionOrder.test.ts | M5-C0 | `docs/audit/MENU_M5B_TECHNICAL_SECTION_REORGANIZE.md` |
| MENU-M5-C0 | STEP M5-C0 | News pipeline tab precheck | NEWS_PIPELINE_SECTION_REORGANIZE | **YES** (with M5-C 본 커밋) | none | — | M5-C | `docs/audit/MENU_M5C_NEWS_PIPELINE_PRECHECK.md` |
| MENU-M5-C | STEP M5-C | News pipeline section reorder | NEWS_PIPELINE_SECTION_REORGANIZE_READY_WITH_LIMITATIONS | **YES** (`ffaa247` · rowKey WIP는 WT residual) | none | upbitNewsPipelineSectionOrder.test.ts | M5-D0 | `docs/audit/MENU_M5C_NEWS_PIPELINE_SECTION_REORGANIZE.md` |
| MENU-M5-D0 | STEP M5-D0 | A/B experiment tab precheck | AB_EXPERIMENT_TAB_KEEP_AS_IS | **NO** (docs only · commit 없음) | none | — | M5-E0 | `docs/audit/MENU_M5D_AB_EXPERIMENT_TAB_PRECHECK.md` |
| MENU-M5-E0 | STEP M5-E0 | Ops/reconciliation tab precheck | OPS_RECONCILIATION_SECTION_REORGANIZE | **NO** (docs only · commit 없음) | none | — | M5-E | `docs/audit/MENU_M5E_OPS_RECONCILIATION_PRECHECK.md` |
| MENU-M5-E | STEP M5-E | Ops section reorder | OPS_RECONCILIATION_SECTION_REORGANIZE_READY_WITH_LIMITATIONS | **YES** (`21632e6` · Ambiguous WIP는 WT residual) | none | upbitOpsReconciliationSectionOrder.test.ts | M5-F | `docs/audit/MENU_M5E_OPS_RECONCILIATION_SECTION_REORGANIZE.md` |
| MENU-M5-F | STEP M5-F | Upbit Hub final regression audit | UPBIT_HUB_CONSOLIDATION_COMPLETE_WITH_LIMITATIONS · M5_CLOSE=YES | **YES** (`a738d91`) | none | focused M5 suite | M6-0 | `docs/audit/MENU_M5F_UPBIT_HUB_FINAL_REGRESSION_AUDIT.md` |
| MENU-M6-0 | STEP M6-0 | Admin/User shared component precheck | SHARED_COMPONENT_CONSOLIDATION_DESIGN_READY | **NO** (docs only · commit 없음) | none | — | M6-A | `docs/audit/MENU_M6_SHARED_COMPONENT_PRECHECK.md` |
| MENU-M6-A | STEP M6-A | Shared formatters/utils extraction | SHARED_FORMATTERS_UTILS_READY_WITH_LIMITATIONS | **YES** (`239550d` · admin shim 유지) | none | sharedUtils + m6aImportDirection | M6-B0 | `docs/audit/MENU_M6A_SHARED_FORMATTERS_UTILS.md` |
| MENU-M6-B0 | STEP M6-B0 | Order RO columns precheck | ORDER_READ_COLUMNS_SHARE_RECOMMENDED | **YES** (with M6-B 본 커밋) | none | — | M6-B | `docs/audit/MENU_M6B_ORDER_COLUMNS_PRECHECK.md` |
| MENU-M6-B | STEP M6-B | COMMON_READ order columns shared | ORDER_READ_COLUMNS_SHARED_READY_WITH_LIMITATIONS | **YES** (`87d0229` · actions/query 분리) | none | orderReadColumns.test.ts | M6-C0 | `docs/audit/MENU_M6B_ORDER_READ_COLUMNS_SHARED.md` |
| MENU-M6-C0 | STEP M6-C0 | Strategy Request RO presentation precheck | STRATEGY_REQUEST_READ_SHARE_RECOMMENDED | **YES** (with M6-C 본 커밋) | none | — | M6-C | `docs/audit/MENU_M6C_STRATEGY_REQUEST_PRECHECK.md` |
| MENU-M6-C | STEP M6-C | Strategy Request COMMON_READ list columns | STRATEGY_REQUEST_COLUMNS_SHARED_READY_WITH_LIMITATIONS | **YES** (`a3612c0` · actions/history/detail 분리) | none | strategyRequestReadColumns.test.ts | M6-D0 | `docs/audit/MENU_M6C_STRATEGY_REQUEST_READ_COLUMNS_SHARED.md` |
| MENU-M6-D0 | STEP M6-D0 | Strategy Draft RO presentation precheck | STRATEGY_DRAFT_FORMATTER_ALREADY_SHARED_SUFFICIENT · **M6-D SKIP** | **YES** (with M6-F docs 본 커밋) | none | — | M6-E0 | `docs/audit/MENU_M6D_STRATEGY_DRAFT_PRECHECK.md` |
| MENU-M6-E0 | STEP M6-E0 | Optional shared presentation final precheck | SHARED_COMPONENT_CONSOLIDATION_COMPLETE_WITH_LIMITATIONS · **M6-E SKIP** | **YES** (with M6-F docs 본 커밋) | none | — | M6-F | `docs/audit/MENU_M6E_SHARED_PRESENTATION_FINAL_PRECHECK.md` |
| MENU-M6-F | STEP M6-F | Shared consolidation final regression / CLOSE | SHARED_COMPONENT_CONSOLIDATION_COMPLETE_WITH_LIMITATIONS · **M6_CLOSE=YES** | **YES** (`de16a45` · docs only) | none | M6 focused suite 31 PASS | M7-0 | `docs/audit/MENU_M6F_SHARED_COMPONENT_FINAL_REGRESSION.md` |
| MENU-M7-0 | STEP M7-0 | Legacy/redirect route cleanup precheck | LEGACY_REDIRECT_CLEANUP_DESIGN_READY · REMOVE=0 | **NO** (docs only · commit 없음) | none | — | M7-A | `docs/audit/MENU_M7_LEGACY_REDIRECT_PRECHECK.md` |
| MENU-M7-A | STEP M7-A | User LLM menu → `/user/ai` canonical | LLM_MENU_CANONICAL_ROUTE_READY_FOR_COMMIT · llm redirect 유지 | **YES** (`d1d0634` · selective) | none | menu.test 11 PASS | M7-B | `docs/audit/MENU_M7A_LLM_CANONICAL_ROUTE_NORMALIZE.md` |
| MENU-M7-B | STEP M7-B | Document DEPRECATE_REDIRECT (9) | LEGACY_REDIRECT_DEPRECATION_DOCUMENTED · REMOVE=0 | **YES** (본 커밋 · docs) | none | — | M7-F | `docs/audit/MENU_M7B_DEPRECATED_REDIRECT_DOCUMENTATION.md` |
| MENU-M7-F | STEP M7-F | Legacy/redirect final regression / CLOSE | LEGACY_REDIRECT_CLEANUP_COMPLETE_WITH_LIMITATIONS · **M7_CLOSE=YES** | **YES** (`f18d02f` · docs) | none | menu.test 11 PASS | M8-0 | `docs/audit/MENU_M7F_LEGACY_REDIRECT_FINAL_REGRESSION.md` |
| MENU-M8-0 | STEP M8-0 | Final menu/route/permission regression precheck | FINAL_IA_REGRESSION_AUDIT_READY_WITH_LIMITATIONS | **YES** (본 커밋 · docs) | none | focused 66 PASS / 1 WIP FAIL | M8-F | `docs/audit/MENU_M8_FINAL_REGRESSION_PRECHECK.md` |
| MENU-M8-F | STEP M8-F | Final menu consolidation CLOSE | MENU_CONSOLIDATION_COMPLETE_WITH_LIMITATIONS · **MENU_CONSOLIDATION_CLOSE=YES** · M3–M8 CLOSED | **YES** (본 커밋 · docs) | none | 66 PASS / 1 WIP FAIL | trading roadmap monitoring | `docs/audit/MENU_M8F_FINAL_MENU_ROUTE_PERMISSION_CLOSE.md` |

---

## 3. STRATEGY-STEP (STRAT-12) 상세

| Canonical | Historical | 제목 | 상태 | 커밋 | Notes |
|-----------|------------|------|------|------|-------|
| STRAT-12.1 | STEP12-1 | Strategy Request | WORKTREE | NO | 실행 WRITE 금지 |
| STRAT-12.1a | STEP12-1a | Request review gate | WORKTREE | NO | |
| STRAT-12.2.1 | STEP12-2-1 | Draft domain | WORKTREE | NO | |
| STRAT-12.2.2 | STEP12-2-2 | Draft generation | WORKTREE | NO | |
| STRAT-12.2.3 | STEP12-2-3 | Draft review | WORKTREE | NO | |
| STRAT-12.3 | STEP12-3 | Draft approval | WORKTREE | NO | |
| STRAT-12.4…12.15 | … | Snapshot…Decision package | WORKTREE | NO | QG/MC/Explain 등 |
| STRAT-12.16 / 12.16r | … | Promotion commit/state | WORKTREE | NO | |
| STRAT-12.17 | STEP12-17 | Activation | WORKTREE | NO | Runtime 자동 start 없음 |
| STRAT-12.18 | STEP12-18 | Runtime registration | WORKTREE | NO | `running=false`, inactive links |
| STRAT-12.19 | STEP12-19 | Deployment readiness | WORKTREE | NO | READY_TO_START ≠ loader ACTIVE |
| STRAT-12.20 | STEP12-20 | Operation readiness | WORKTREE | NO | WT alembic head |

**대체 관계:** Audit `AUDIT21-12`(Paper) ≠ `STRAT-12.*`. 서로 대체하지 않음.

**Blocking:** P0-3 (Registry↔Runtime), P0-4 (Migration head).

---

## 4. 번호 배정 규칙

1. 신규는 활성 시리즈에만 붙인다 (`DEV-8` / `AI-11` / `STRAT-12` 또는 **새 시리즈 이름**).
2. 시리즈 종료 후 숫자만 재사용하지 않는다.
3. `AUDIT21-*` 번호는 신규 개발에 재사용 금지.
4. 이슈·커밋·폴더에 Canonical ID 병기.

---

## 5. STEP 완료 시

본 문서 + IMPLEMENTATION_STATUS + ROADMAP + CURRENT_WORK 갱신.  
완료보고는 SoT가 아니다 → 향후 `docs/archive/completion-reports/`.
