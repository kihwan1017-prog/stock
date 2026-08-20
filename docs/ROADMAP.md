# ROADMAP

**역할:** 자동매매·플랫폼 잔여 작업 (P0–P5).  
**최종 갱신:** 2026-08-20  
**Ops note (2026-08-20):** TRACK U `UPBIT_FULL_MARKET_AUTOTRADING_READY_TO_ENABLE`. Next exactly one: **ENABLE UBA1380 FULL MARKET AUTO MODE FROM ADMIN UI**. UBA1380 mode=FIXED_SYMBOL 유지 · FULL_MARKET 자동 Enable 금지 · REAL 테스트 주문 금지. K track 별도.
**Ops note (2026-08-20 SUPERSEDED):** TRACK K `KIWOOM_UBA1381_LIVE_DEPLOYMENT_BLOCKED_LIFECYCLE`. Next exactly one: **KIWOOM UBA1381 STRATEGY PROMOTION DECISION PACKAGE**. STEP12 chain 미완 · LIVE deployment 0. Activation #20 expires 2026-08-20 13:51 KST. UPBIT **UPBIT KRW-SOL LIVE COOLDOWN ALIGNMENT** 별도.
**Ops note (2026-08-20 SUPERSEDED):** TRACK K `KIWOOM_UBA1381_RUNTIME_START_FAILED`. Next exactly one: **KIWOOM UBA1381 LIVE STRATEGY DEPLOYMENT**. ensure-scope: Active strategy deployment not found. Activation #20 expires 2026-08-20 13:51 KST. UPBIT **UPBIT KRW-SOL LIVE COOLDOWN ALIGNMENT** 별도.
**Ops note (2026-08-20 SUPERSEDED):** TRACK K `KIWOOM_UBA1381_REARMED_READY_FOR_RUNTIME_START`. Next exactly one: **KIWOOM UBA1381 RUNTIME START**. ARM TTL expires ~2026-08-20 11:28:01 KST. Activation #20 expires 2026-08-20 13:51 KST. UPBIT **UPBIT KRW-SOL LIVE COOLDOWN ALIGNMENT** 별도.
**Ops note (2026-08-20 SUPERSEDED):** TRACK K `KIWOOM_UBA1381_ACCOUNT_SYNCED_READY_FOR_REARM`. Next exactly one: **KIWOOM UBA1381 RE-ARM**. Runtime/실주문 미실행. Activation #20 expires 2026-08-20 13:51 KST. UPBIT **UPBIT KRW-SOL LIVE COOLDOWN ALIGNMENT** 별도.
**Ops note (2026-08-20 SUPERSEDED):** TRACK K `KIWOOM_UBA1381_LIVE_ON_READY_FOR_ACCOUNT_SYNC`. Next exactly one: **KIWOOM UBA1381 ACCOUNT SYNC / RECONCILIATION**. ARM/Runtime/실주문 미실행. Activation #20 expires 2026-08-20 13:51 KST. UPBIT **UPBIT KRW-SOL LIVE COOLDOWN ALIGNMENT** 별도.
**Ops note (2026-08-20 SUPERSEDED):** TRACK K `KIWOOM_UBA1381_REARM_BLOCKED_LIVE`. Next exactly one: **KIWOOM UBA1381 LIVE ON**. ARM 만료가 LIVE OFF. Activation #20 expires 2026-08-20 13:51 KST. 재-ARM/Runtime 미실행. UPBIT **UPBIT KRW-SOL LIVE COOLDOWN ALIGNMENT** 별도.
**Ops note (2026-08-20 SUPERSEDED):** TRACK K `KIWOOM_UBA1381_ARMED_READY_FOR_RUNTIME_PRECHECK`. Next exactly one: **KIWOOM UBA1381 RUNTIME START READINESS**. Runtime/Runner/실주문 미실행. ARM TTL expires ~2026-08-20 10:31:30 KST. Activation #20 expires 2026-08-20 13:51 KST. UPBIT **UPBIT KRW-SOL LIVE COOLDOWN ALIGNMENT** 별도.
**Ops note (2026-08-20 SUPERSEDED):** TRACK K `KIWOOM_UBA1381_ARM_READY`. Next exactly one: **KIWOOM UBA1381 ARM ON**. Runtime/Runner/실주문은 ARM ON 이후 별도 STEP. Activation #20 expires 2026-08-20 13:51 KST. UPBIT **UPBIT KRW-SOL LIVE COOLDOWN ALIGNMENT** 별도.
**Ops note (2026-08-20 SUPERSEDED):** TRACK K `KIWOOM_UBA1381_LIVE_ON_READY_FOR_ARM`. Next exactly one: **KIWOOM UBA1381 ARM READINESS**. ARM ON/Runtime/Runner/실주문은 이후 STEP. UPBIT 잔여 **UPBIT KRW-SOL LIVE COOLDOWN ALIGNMENT**는 별도 STEP. Activation #20 expires 2026-08-20 13:51 KST.
**Ops note (2026-08-20 SUPERSEDED):** TRACK K `KIWOOM_LIVE_ACTIVATION_READY_REACTIVATION_REQUIRED`. Next exactly one: **KIWOOM UBA1381 LIVE ACTIVATION CREATE**. #13 재사용 금지. LIVE ON/ARM/Runtime/Runner START 금지. UPBIT 잔여 **UPBIT KRW-SOL LIVE COOLDOWN ALIGNMENT**는 별도 STEP.
**Ops note (2026-08-20 SUPERSEDED):** TRACK K `KIWOOM_KRX_REAL_MARKET_DATA_TICK_PROVEN_LIVE_PRECHECK_PENDING`. Next exactly one: **KIWOOM LIVE ACTIVATION READINESS**. KIWOOM LIVE ON/ARM/Runtime/Runner START 금지. UPBIT 잔여 **UPBIT KRW-SOL LIVE COOLDOWN ALIGNMENT**는 별도 STEP.
**Ops note (2026-08-20 SUPERSEDED):** TRACK U `UPBIT_REMOTE_SELL_ORDERS_CANCELLED_COOLDOWN_ALIGNMENT_PENDING`. Next exactly one: **UPBIT KRW-SOL LIVE COOLDOWN ALIGNMENT**. 09:00 이후는 **KIWOOM KRX OPEN REAL MARKET DATA TICK VALIDATION** 우선. Activation/LIVE/ARM/Runtime/Runner START 금지.
**Ops note (2026-08-20 SUPERSEDED):** TRACK U `UPBIT_REMOTE_OPEN_ORDER_SAFETY_ALIGNED_CANCELLATION_APPROVAL_REQUIRED`. Next exactly one: **UPBIT EXTERNAL REMOTE SELL ORDER CANCELLATION APPROVAL**. Activation/LIVE/ARM/Runtime/Runner START 금지. remote CANCEL은 승인 후. KIWOOM는 OPEN tick validation만.
**Ops note (2026-08-20 SUPERSEDED):** TRACK U `UPBIT_KRW_SOL_RUNTIME_APPROVAL_GATE_ALIGNED_REMOTE_ORDERS_PENDING`. Next exactly one: **UPBIT REMOTE PENDING ORDER RECONCILIATION**. Activation/LIVE/ARM/Runtime/Runner START 금지. remote CANCEL은 다음 STEP. KIWOOM는 OPEN tick validation만.
**Ops note (2026-08-20 SUPERSEDED):** TRACK U `UPBIT_KRW_SOL_LIVE_TIMEFRAME_ALIGNED_OTHER_BLOCKERS_REMAIN`. Next exactly one: **UPBIT KRW-SOL STRATEGY LIVE APPROVAL ALIGNMENT**. Activation/LIVE/ARM/Runtime/Runner START 금지. KIWOOM는 OPEN tick validation만.
**Ops note (2026-08-20 SUPERSEDED):** TRACK U `UPBIT_KRW_SOL_LIVE_TIMEFRAME_ALIGNMENT_REQUIRED`. Next exactly one: **UPBIT KRW-SOL LIVE TIMEFRAME ALIGNMENT IMPLEMENTATION**. Activation/LIVE/ARM/Runtime/Runner START 금지. KIWOOM는 OPEN tick validation만.
**Ops note (2026-08-20 SUPERSEDED):** TRACK U `UPBIT_KRW_SOL_STRATEGY_ACTIVATED_AND_LINKED_LIVE_PRECHECK_PENDING`. Next exactly one: **UPBIT NEW-SYMBOL CONTROLLED LIVE ACTIVATION PRECHECK**. 실제 LIVE 시작은 그 다음 승인 STEP. KIWOOM는 OPEN tick validation만.
**Ops note (2026-08-20 SUPERSEDED):** TRACK U `UPBIT_KRW_SOL_STRATEGY_VALIDATED_ACTIVATION_PENDING`. Next exactly one: **UPBIT KRW-SOL STRATEGY ACTIVATION AND UBA1380 LINK READINESS**. 이 STEP에서 Activation/LIVE/Runtime 금지. KIWOOM는 내일 OPEN tick validation만.
**Ops note (2026-08-20 SUPERSEDED):** TRACK U `UPBIT_SELECTED_NEW_SYMBOL_REJECTED_BY_PAPER`. Next exactly one: **STOP**. Paper not PASS. MA/심볼 재시도/Activation/LIVE 금지. KIWOOM는 내일 OPEN tick validation만.
**Ops note (2026-08-19 SUPERSEDED):** TRACK K `KIWOOM_REAL_MARKET_DATA_RUNTIME_READY_NEXT_SESSION_TICK_PROOF_PENDING`. Next exactly one: **KIWOOM KRX OPEN REAL MARKET DATA TICK VALIDATION**. 다음 KRX OPEN만. LIVE/ARM/Runtime START 금지. REAL_ORDER_WITH_MOCK_SIGNAL_ALLOWED=NO.
**Ops note (2026-08-19 SUPERSEDED):** TRACK K `KIWOOM_STRATEGY_17579_ACTIVATED_AND_LINKED_REALTIME_BLOCKED`. Next exactly one: **KIWOOM REAL MARKET DATA RUNTIME IMPLEMENTATION**. LIVE/ARM/Runtime START 금지. REAL_ORDER_WITH_MOCK_SIGNAL_ALLOWED=NO.
**Ops note (2026-08-19 SUPERSEDED):** TRACK K `KIWOOM_DERIVED_STRATEGY_17579_VALIDATED_ACTIVATION_PENDING`. Next exactly one: **KIWOOM STRATEGY 17579 ACTIVATION AND UBA1381 LINK READINESS**. REAL WS blocker 유지. LIVE/ARM/실주문/UPBIT 복구 금지.
**Ops note (2026-08-19 SUPERSEDED):** TRACK K `KIWOOM_SOURCE_STRATEGY_PAPER_VALIDATION_PASSED_DERIVED_REVALIDATION_REQUIRED`. Next exactly one: **KIWOOM DERIVED STRATEGY 17579 BACKTEST AND PAPER REVALIDATION**. 17579 activation/link/LIVE 금지. UPBIT 복구 금지.
**Ops note (2026-08-19 SUPERSEDED):** TRACK K `KIWOOM_STRATEGY_OWNERSHIP_ALIGNED_FOR_UBA1381`. Next exactly one: **KIWOOM PAPER VALIDATION ACCEPTANCE POLICY IMPLEMENTATION**. 17579는 Paper 미상속. LIVE/실주문/UBA1381 link/UPBIT 복구 금지.
**Ops note (2026-08-19 SUPERSEDED):** TRACK K `KIWOOM_KRX_PAPER_REPLAY_EVIDENCE_READY_POLICY_PENDING`. Next exactly one: **KIWOOM STRATEGY OWNERSHIP ALIGNMENT FOR UBA1381**. Paper 1525 ≠ LIVE 승인. LIVE/실주문/UPBIT 복구 금지.
**Ops note (2026-08-19 SUPERSEDED):** TRACK K `KIWOOM_KRX_PAPER_HISTORICAL_REPLAY_NOT_IMPLEMENTED`. Next exactly one: **KIWOOM PAPER HISTORICAL REPLAY IMPLEMENTATION**. Backtest≠Paper. LIVE/실주문/UBA1381 link/owner 변경/UPBIT 복구 금지.
**Ops note (2026-08-19 SUPERSEDED):** TRACK K `KIWOOM_KRX_STRATEGY_BACKTEST_PASSED_PAPER_PENDING`. Next exactly one: **KIWOOM KRX PAPER TRADING VALIDATION (HISTORICAL/REPLAY ONLY)**. REAL KIWOOM 주문·LIVE·UBA1381 link·UPBIT 복구 금지.
**Ops note (2026-08-19 SUPERSEDED):** TRACK K `KIWOOM_KRX_STRATEGY_DRAFT_AWAITING_HUMAN_APPROVAL`. Next exactly one: **KIWOOM KRX STRATEGY DRAFT HUMAN APPROVAL WITH BACKTEST-BEFORE-DEFINITION**. STEP12-3 자동 승인 금지(Definition 선행 가능). LIVE/주문/UPBIT 복구 금지.
**Ops note (2026-08-19 SUPERSEDED):** TRACK K `KIWOOM_KRX_PROMOTION_FULLY_APPROVED_COMMIT_READY`. Next exactly one: **KIWOOM KRX PROMOTION COMMIT AND STRATEGY LIFECYCLE CONTINUATION**. Commit 전 LIVE/주문 금지.
**Ops note (2026-08-19 SUPERSEDED):** TRACK K `KIWOOM_PROMOTION_APPROVERS_PROVISIONED_READY_FOR_HUMAN_APPROVAL`. Next exactly one: **KIWOOM KRX HUMAN FIRST AND FINAL PROMOTION APPROVAL**. FIRST≠FINAL≠admin:7. Commit 별도. 강제 주문/UPBIT 복구 금지.
**Ops note (2026-08-19 SUPERSEDED):** MASTER `KIWOOM_PROMOTION_INSUFFICIENT_APPROVERS` + `UPBIT_NEW_SYMBOL_STRATEGY_REQUIRED`. Next exactly one: **PROVISION TWO ADDITIONAL REAL ADMIN USERS FOR PROMOTION FIRST/FINAL APPROVAL**. 17483 재바인딩·Risk/cap 상향·강제 주문 금지.
**Ops note (2026-08-19 SUPERSEDED):** TRACK K `KIWOOM_KRX_PROMOTION_AWAITING_HUMAN_APPROVAL`. 034310 Promotion Request id=1 DRAFT. Next exactly one: **KIWOOM KRX HUMAN PROMOTION APPROVAL**. APPROVE 외 COMMIT/Strategy Request 금지. UPBIT 자동 복구 금지. LIVE/ARM/실주문 금지.
**Ops note (2026-08-19 SUPERSEDED):** TRACK K `KIWOOM_KRX_PROMOTION_REQUEST_BLOCKED_AFTER_QUEUE_DECIDE`. 034310 Queue 1 decided · Promotion Request 0. Next exactly one: **KIWOOM KRX PROMOTION REQUEST CREATE** (loaded keyword-only `is_expired` 반영 후, approve/commit 금지). UPBIT 자동 복구 금지. LIVE/ARM/실주문 금지.
**Ops note (2026-08-19 SUPERSEDED):** TRACK K `KIWOOM_KRX_CANDIDATES_REJECTED_BY_CANONICAL_ASSESSMENT`. post-close daily coverage **64.79%** · candidate **3** · REAL WS market tick contract NOT FOUND (no guess impl). Next exactly one: **AI STOCK_CANDIDATE_ASSESSMENT prompt/schema 활성 복구 후 KIWOOM KRX 후보 파이프라인 재실행** (human gate 이전 단계 복구). UPBIT 운영 유지. LIVE/ARM/실주문 금지.
**Ops note (2026-08-19 SUPERSEDED):** TRACK K `KIWOOM_KRX_TRADE_VALUE_FIXED_NO_CANDIDATE`. trade_value 단위 수정·backfill 256627행. rescan selected=0. Next exactly one: **KIWOOM KRX DAILY COLLECTION CONTINUATION**. UPBIT 운영 유지. Promotion/LIVE 금지.
**Ops note (2026-08-19 SUPERSEDED):** TRACK K `KIWOOM_KRX_DAILY_COVERAGE_EXPANDED_NO_CANDIDATE`. ge60 80→1012 · coverage 23.85% · selected=0. 원인=`trade_value` 단위 불일치. Next exactly one: **KIWOOM KRX DAILY PIPELINE MAINTENANCE PATCH**. UPBIT 운영 유지. Promotion/LIVE 금지.
**Ops note (2026-08-19 SUPERSEDED):** TRACK K `KIWOOM_KRX_DATA_SYNC_COMPLETED_NO_CANDIDATE` — continuation/rescan 본 STEP에서 수행.
**Ops note (2026-08-19 SUPERSEDED):** TRACK U restore 후 Next=`KIWOOM KRX INSTRUMENT AND DAILY SYNC EXECUTION` — 본 STEP 완료.
**Ops note (2026-08-19 SUPERSEDED):** TRACK K `KIWOOM_KRX_DATA_PIPELINE_READY_FOR_MAINTENANCE_WINDOW` — 유지창·src 패치·UPBIT restore 완료. Next는 더 이상 유지창이 아님.
**Ops note (2026-08-19):** TRACK U `UPBIT_UBA1380_OPERATIONAL_RESTORED`. Next exactly one: **KIWOOM UBA1381 LIVE/MOCK SOURCE-OF-TRUTH ALIGNMENT**. 이번 STEP 미수행. KIWOOM START · ENV · 실주문 금지.
**Ops note (2026-08-19):** TRACK K `KIWOOM_MULTI_UBA_LIVE_EXECUTION_ARCHITECTURE_READY_WITH_LIMITATIONS`. Next exactly one: **APPROVED UPBIT UBA1380 OPERATIONAL RESTORE** (LIVE/ARM/Worker/Runtime 17483/Runner). KIWOOM START · ENV · 실주문 금지.  
**Ops note (2026-08-19):** TRACK K `KIWOOM_REALTIME_AUTOTRADING_BLOCKED`. Next exactly one: **DO_NOT_TOUCH_UPBIT — KIWOOM LIVE Runner architecture without stopping UBA1380**.  
**Ops note (2026-08-19):** TRACK U OBSERVABILITY TIMEOUT FAIL-SAFE + FINAL RESTART `UPBIT_REALTIME_AUTOTRADING_LIVE_EXECUTION_OPERATIONAL`. Next=**NONE** (UPBIT 개발 종료, 운영/모니터링). COMPLETED 유지.  
**Ops note (2026-08-19):** TRACK U FINAL CONTROLLED RESTART `UPBIT_REALTIME_AUTOTRADING_LIVE_EXECUTION_ROLLED_BACK`. Next exactly one: **UPBIT REALTIME AUTOTRADING LIVE EXECUTION FINAL CONTROLLED RESTART** (retry, 별도 승인). COMPLETED 유지.  
**Ops note (2026-08-19):** TRACK U SIGNAL-TO-ORDER SAFETY FIX `READY_WITH_LIMITATIONS`. Next exactly one: **UPBIT REALTIME AUTOTRADING LIVE EXECUTION RESTART PRECHECK**. 재가동/실주문 금지. COMPLETED 유지.  
**Ops note (2026-08-19):** TRACK U LIVE runner — 신호→TradingOrder 연결 확인. dispatch `LIVE_MOCK_CONFLICT` + duplicate SELL enqueue. Runner STOP. 최소 FIX=UPBIT dispatch에서 Kiwoom mock conflict 제외 + pending SELL 중복 차단. COMPLETED 유지.  
**Ops note (2026-08-19):** TRACK U diagnostic — 자연 자동주문 0의 ROOT_CAUSE=`RealtimeExecutionRunner` 미기동 (PAPER/processed=0). 최소 FIX=LIVE scoped Execution Runner START (별도 승인). 구현 COMPLETED 유지.  
**Ops note (2026-08-18):** TRACK U **FREEZE** — UPBIT UBA1380 **COMPLETED** · `GO_LIVE_SUCCESS_WITH_LIMITATIONS` · CONTROLLED 24X7 SESSION · 추가 UPBIT 구현 STEP 없음. Next project action: 다음 KRX OPEN KIWOOM UBA1381 FIRST LIVE ORDER (fresh quote). commit/push NO.  
**Ops note (2026-08-18):** TRACK U go-live 반영 · Activation 15 · live_upbit ON.  
**Ops note (2026-08-18):** TRACK U 24x7 Runtime/Outbox control **READY_WITH_LIMITATIONS** (선행, 운영 반영됨).  
**Ops note (2026-08-18):** TRACK U LIVE position exit monitor **READY_WITH_LIMITATIONS** → go-live 시 `live_upbit` flag **ON**.  
**Ops note (2026-08-16):** U termination selective commit **CLOSE** · K credential **WAITING_FOR_USER_INPUT** (UI `/user/accounts/kiwoom`) · push 금지 · LIVE 금지.  
**Ops note (2026-08-16):** U selective-commit PRECHECK **READY** · K provisioning PRECHECK **READY** (UI/API exist) · next U **SELECTIVE COMMIT** · next K **CREDENTIAL PROVISIONING** · secrets not via chat.  
**Ops note (2026-08-16):** U-TERM-B **PROVEN_WITH_LIMITATIONS** (shadow52 CANCELLED natural) · K-CRED **PROVISIONING_REQUIRED** · next U **SELECTIVE COMMIT PRECHECK** · next K **CREDENTIAL PROVISIONING PRECHECK**.  
**Ops note (2026-08-16):** Parallel **U-TERM-A** `TERMINATION_TARGET_ONLY_READY` · **K-B** `KIWOOM_P0_2_READY_WITH_LIMITATIONS` · SHARED_CHANGED=0 · next U **TERM-B** · next K **CREDENTIAL_UBA_ALIGNMENT** · commit 분리 예정.  
**Ops note (2026-08-16):** Parallel tracks **U/K** — U-TERM-A0 **`TERMINATION_IMPLEMENTATION_READY_TARGET_ONLY`** · next U **TERMINATION IMPLEMENTATION (TARGET_ONLY)**; K-G0 **`KIWOOM_LIVE_BLOCKED`** · next K **`KIWOOM_P0-2_LIVE_POSITION_WRITE`** · `PARALLEL_WRITE_SAFE=YES_WITH_BOUNDARIES`.  
**Ops note (2026-08-16):** Shadow LONG_ACTIVE TERMINATION DESIGN **READY** · OPTION E · CANCELLED reuse · IMPLEMENTATION PRECHECK **done**.  
**Ops note (2026-08-16):** Shadow 52 LONG_ACTIVE PRECHECK — termination fix **RECOMMENDED**.  
**Ops note (2026-08-15):** TP CANDIDATE REANALYSIS — paired n=47 · **KEEP_6_SUPERIOR** · `FROZEN_CANDIDATE_TP=null`.  
**Ops note (2026-08-15):** COV-D CLOSEOUT — **NO historical APPLY** · `COVERAGE_REMEDIATION_CLOSE=YES` · coverage holes=SOURCE_ABSENT · math delta 0.  
**Ops note (2026-08-15):** COV-A/C/B atomic commit · path defer gate LIVE · runtime PASS_COMPLETED proven.  
**Ops note (2026-08-15):** COV-C source reconciliation **READY** · dry defer 72%→0% · path_quality **v2** · **PATH_GATE_EVIDENCE_READY=YES**.
**Ops note (2026-08-15):** TP OOS design → `CANDIDATE_DEFINITION_REQUIRED` (band 2–4% not freezable). Preferred future path Option C (6% policy keep + post-hoc candle recompute on new COMPLETED). Next: **TP CANDIDATE DEFINITION REVIEW**. APPLY=NO.
**Ops note (2026-08-15):** Technical TP CHANGE_CANDIDATE re-review — `CHANGE_CANDIDATE_NEEDS_OOS_VALIDATION` · CURRENT_TP=6% · candidate band 2–4% · **TP_APPLY_READY=NO** · STRICT_VALID=48. Next: OOS validation design (no apply).
**Ops note (2026-08-14):** Technical Shadow Cohort REVIEW_READY v2 완료 — `TECHNICAL_COHORT_REVIEW_COMPLETE_CHANGE_CANDIDATES` (TP only; **미적용**). Next sample gate **n≈50**. 정책/threshold 변경 없음. SHADOW_ONLY 유지.  
**News note (2026-08-14):** STEP N10 `NEWS_AB_SAMPLE_ACCUMULATING` — 자연 MATCHED 1/20 · NO_NEWS 13/20; Top-N Snapshot **OBSERVE_MORE** (구현 금지). Next: 자연 누적 지속 → REVIEW_READY; production Scanner/Gate 적용 금지.  
**P0 ID는 PHASE 2 Canonical 고정** (PHASE 1 remaining-work 파일의 P0 번호와 다를 수 있음 → **본 문서 우선**).

상태 값: `OPEN` · `IN_PROGRESS` · `BLOCKED` · `DONE` · `DEFERRED`

**종합 (추정):** 개발 ~78% · Paper ~78% · LIVE ~53% · 운영 **NOT READY** · LIVE **NOT APPROVED** · Paper 무인 **PARTIAL**  
→ [PROJECT_IMPLEMENTATION_STATUS.md](PROJECT_IMPLEMENTATION_STATUS.md)

---

## P0 — 실거래·배포·데이터 정합성 차단

### P0-1 — Realtime `broker_code="KIWOOM"` 하드코딩

| 필드 | 내용 |
|------|------|
| 우선순위 | P0 |
| 시장 | Upbit / Kiwoom |
| 문제 | Realtime 주문 경로가 broker를 KIWOOM으로 고정 → 잘못된 Outbox enqueue |
| 완료 조건 | Scope·UBA의 `broker_code`로 enqueue |
| 상태 | **IN_PROGRESS** (코드: `risk_integrated_order_executor` scope/exchange resolve, 미커밋) |

### P0-2 — Kiwoom Fill → TradingOrder → Position/Balance/P&L 단절

| 필드 | 내용 |
|------|------|
| 우선순위 | P0 |
| 시장 | Kiwoom LIVE |
| 문제 | Fill이 pending 수준에 머물고 TradingOrder/Position 장부와 미연결 |
| 완료 조건 | WS/폴링 event → order state → position/balance 경로 |
| 상태 | **IN_PROGRESS** (WS→ExecutionSync bridge 추가; LIVE Position 원장 WRITE는 OPEN) |

### P0-3 — STEP12 Lifecycle/Registration/Deployment ↔ Scoped Runtime 불일치

| 필드 | 내용 |
|------|------|
| 우선순위 | P0 |
| 시장 | ALL |
| 문제 | Registry `running=false`, inactive links, READY_TO_START ≠ loader ACTIVE |
| 완료 조건 | 상태 모델 문서화 + 명시적 Promote-to-ACTIVE(기본 OFF) |
| 상태 | **IN_PROGRESS** (`runtime_start_service` + admin `/runtime-start`, Runner auto-start OFF) |

### P0-4 — Git 커밋 Alembic Head ↔ 워킹트리 Head 불일치

| 필드 | 내용 |
|------|------|
| 상태 | **DONE** (Git head `a7f3e91c4d28`, 운영 DB upgrade는 별도 Gate) |

### P0-5 — Paper Outbox ACCEPTED → PaperExecutionService 자동 Fill 부재

| 필드 | 내용 |
|------|------|
| 우선순위 | P0 |
| 시장 | Stock/Crypto Paper |
| 문제 | Outbox ACCEPT ≠ 자동 fill/position |
| 완료 조건 | 플래그 ON 시 fill→position; LIVE 혼입 금지 |
| 상태 | **IN_PROGRESS** (`PaperOutboxFillService` + outbox_worker hook, `paper_outbox_auto_fill`) |

---

## P1 — Runtime → Signal → Risk → Order → Broker 연결

| ID | 제목 | 시장 | 선행 | 완료 조건 | 테스트 | 안전 | 상태 |
|----|------|------|------|-----------|--------|------|------|
| P1-1 | Deployment READY_TO_START ↔ loader ACTIVE 정합 | ALL | P0-3,P0-4 | 명시 게이트 | step12-19 | 기본 OFF | OPEN |
| P1-2 | Runtime Registration → active AccountStrategyLink | ALL | P1-1 | 이중승인 후 is_active | step12-18 | 기본 OFF | OPEN |
| P1-3 | Session OPEN ↔ Runner start 정책화 | ALL | P1-2 | 플래그로만 자동 start | session scheduler | 기본 OFF | OPEN |
| P1-4 | Signal → Order E2E (Paper) | Paper | P0-1,P0-5,P1-2 | Hub→outbox→fill→position | Paper E2E | Paper only | OPEN |
| P1-5 | Kiwoom realtime MD 또는 배치 신호 경로 제품 결정 | KRX | — | 결정+문서 | — | — | OPEN |

---

## P2 — Fill → Position → Balance → P&L → Recovery

| ID | 제목 | 선행 | 완료 조건 | 상태 |
|----|------|------|-----------|------|
| P2-1 | Kiwoom pending ↔ TradingOrder reconcile | P0-2 | conflict UI+서비스 | OPEN |
| P2-2 | Settlement/Ledger UBA·Paper FK 완성 | P0-4 | migration+tests | OPEN |
| P2-3 | Intraday PnL snapshot | P2-2 | API+dashboard | OPEN |

---

## P3 — Backtest / Paper / Performance / Risk 검증

| ID | 제목 | 완료 조건 | 상태 |
|----|------|-----------|------|
| P3-1 | Paper validation gate before LIVE promotion | 정책+테스트 | OPEN |
| P3-2 | Walk-forward/QG → Deployment 게이트 강제 | 코드 연결 | OPEN |
| P3-3 | Performance/Risk 리포트 운영 대시보드 | FE+API | OPEN |

---

## P4 — Monitoring / Notification / Backup / Runbook

| ID | 제목 | 완료 조건 | 상태 |
|----|------|-----------|------|
| P4-1 | Backup restore API (FE TODO) | POST ops restore | OPEN |
| P4-2 | Full autotrading runbook (Paper vs LIVE) | `docs/operations/` | OPEN |
| P4-3 | Outbox/fill/runner metrics | dashboard | OPEN |
| P4-4 | Kill Switch / Recovery conflict 알림 확장 | telegram events | OPEN |

**UPBIT [C] MAINTENANCE / OPTIONAL** (완료 blocker 아님, 완료율을 낮추지 않음): Runtime heartbeat observability · `/health/ops` 표현 · Worker START API polish · Telegram/UI/audit · AI Gate LIVE · Scanner LIVE 연결 · AUTO RE-ARM. 세션 갱신은 운영 runbook만: [trading/UPBIT_UBA1380_24X7_SESSION_RENEWAL.md](trading/UPBIT_UBA1380_24X7_SESSION_RENEWAL.md).

---

## P5 — 문서 · Legacy · 중복 정리

| ID | 제목 | 완료 조건 | 상태 |
|----|------|-----------|------|
| P5-1 | PHASE 2 Canonical 문서 표준화 | 본 PHASE 완료보고 | **DONE** (승인 대기) |
| P5-2 | PHASE 3 Archive 이동 계획 실행 | 사용자 승인 후 이동 | OPEN |
| P5-3 | Deprecated `alembic/versions` 정리 | ARCHIVE 표기 | OPEN |
| P5-4 | Dual dashboard router 문서화/통합 | KEEP or CONSOLIDATE | OPEN |
| P5-5 | Admin/User 메뉴 IA (M3-A→M8) | **MENU_CONSOLIDATION_CLOSE=YES** (M3–M8 CLOSED · Admin 11/55 · User 12/29) | **DONE** |

---

## 권장 실행 순서

1. P0-4 (커밋/head) → P0-1 (broker hardcode) → P0-5 (Paper fill)  
2. P0-3 / P1-1 / P1-2 (STEP12↔Runtime, 기본 OFF)  
3. P1-4 Paper E2E  
4. P0-2 / P1-5 Kiwoom — **다음 프로젝트 액션:** 다음 KRX OPEN UBA1381 FIRST LIVE ORDER (fresh quote, 오늘 가격 재사용 금지)  
5. P5 Archive (승인 후)

관련: [PROJECT_IMPLEMENTATION_STATUS.md](PROJECT_IMPLEMENTATION_STATUS.md) · [audit/PROJECT_REMAINING_WORK_20260731.md](audit/PROJECT_REMAINING_WORK_20260731.md) (Historical 초안)
