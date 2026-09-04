# CURRENT_WORK

**역할:** 현재 진행 중인 작업만 기록한다.  
**최종 갱신:** 2026-09-04 (KIWOOM-TOP10-REAL-CONFIG-DRIFT-FEED-READINESS-V1)

---

## K — TOP10 REAL Config Drift + Feed/Readiness (2026-09-04)

- WORK: `WRK-20260904-KIWOOM-TOP10-REAL-CONFIG-DRIFT-FEED-READINESS-V1` · History **#120** · Parent **#79**
- Canonical TOP10 REAL approved (MODE=REAL · Deployment 869 · +034310 → 11)
- Root: `RUNTIME_RESTORE_REGRESSION` — stack feed FIXED-only + event-loop Lock stall blocked refresh after 09:00
- Restored: SUBSCRIBED 1→11 · FEED REAL_FRESH · STACK 4/4 · READY=true
- Readiness: KIWOOM `/status` broker-aware (UPBIT_* contamination fixed) · ops SoT 정렬
- Restart **×1** · Upbit untouched policy · LIVE/ARM ON both markets
- Evidence: `.run/kiwoom_top10_real_config_drift_feed_readiness_20260904.json`
- NEXT: `CONTINUE_NATURAL_FRESH_GC_WAIT`

---

## U — Prod Stable Process + UBA1380 Restore (2026-09-04)

- WORK: `WRK-20260904-UPBIT-PROD-STABLE-PROCESS-AND-RUNTIME-RESTORE-V1` · History **#117** · Parent **#116**
- Launcher: `ops/start_backend_prod.ps1 -Force` → `RUNTIME_MODE=production` · `HOT_RELOAD=false` · `PROCESS_STABLE=true`
- LIVE ON / ARM ON / STACK **4/4** SUCCESS · order **2644** ACCEPTED unchanged · MANUAL unchanged
- Residual: immediate post-restore had `ENTRY_EVALUATOR_STALE`; settled HTTP SoT → `AUTO=RUNNING` · `READY=true` · `PRIMARY_BLOCKER=null`
- Verdict: `PASS_PROD_STABLE_AND_RUNTIME_RESTORED`
- Evidence: `.run/upbit_prod_stable_process_runtime_restore_20260904.json`
- NEXT: `NATURAL_OBSERVATION_LEAVE_2644_UNTIL_FILL`

---

## U — UBA1380 Operator Runtime Restore (2026-09-04)

- WORK: `WRK-20260904-UPBIT-UBA1380-OPERATOR-APPROVED-RUNTIME-RESTORE-V1` · History **#116** · Parent **#115**
- **FAIL_CLOSED**: LIVE ON → `REAL_RUNTIME_REQUIRES_STABLE_PROCESS` (development/hot_reload) — superseded by #117
- Evidence: `.run/upbit_uba1380_operator_runtime_restore_20260904.json`

---

## U+K — Post News V1 Followup (2026-09-04)

- WORK: `WRK-20260904-POST-NEWS-V1-RUNTIME-BINDING-KIWOOM-LLM-FOLLOWUP` · History **#115** · Parent **#114**
- P0: `FILLED_EXIT_WITH_OPEN_BINDING` = false positive (binding 416 / KRW-EGLD / active SELL 2644) → detector fix · reconcile **fail-closed**
- P1: `KIWOOM_LLM_RUNNING=false` = `NO_FRESH_GOLDEN_CROSS` / market-hours expected · observability split · SHADOW_N=1 · LLM_BACKED=0
- P2: NEWS_V1 commit `89b82ad` · FOLLOWUP `f73aa7f` · Telegram hotfix `8883ec2` preserved · migration `nintelv1a2b3c4`
- Restart **×1** → LIVE/ARM OFF by restart_policy (operator restore required) · MANUAL untouched · FILLED_EXIT count=0
- Evidence: `.run/post_news_v1_runtime_binding_kiwoom_llm_followup_20260904.json`
- NEXT: superseded by #116 → blocked on stable production process

---

## U+K — News Intelligence Pipeline V1 (2026-09-04)

- WORK: `WRK-20260903-UPBIT-KIWOOM-NEWS-INTELLIGENCE-PIPELINE-V1` · History **#114** · Parent audit + preserve **#113** / `8883ec2`
- SHADOW ONLY · REAL AI Gate/candidate/entry/exit/risk **UNCHANGED**
- Migration `nintelv1a2b3c4` · Restart **×2** · production reload=false
- UPBIT collector freshness LAST_CHECK/SUCCESS/NEW · dynamic targets · mapping 0.76→0.82 · shadow N=5 + Telegram
- KIWOOM TOP10 news/DART collector · DART map 0.9 · shadow N=1 · Admin observability
- Commit **`89b82ad`** (followup provenance `f73aa7f`)
- Evidence: `.run/upbit_kiwoom_news_intelligence_pipeline_v1.json`
- NEXT: superseded by #115 → `OPERATOR_LIVE_ARM_RESTORE_UBA1380`

---

## U — Profitability Lab V1 Safe Prod Activation (2026-09-03)

- WORK: `WRK-20260903-UPBIT-PROFITABILITY-LAB-V1-SAFE-PROD-ACTIVATION` · History **#111** · Parent **#110**
- TARGET **`3943566`** · Restart **×1** · unattended restore OK · `PRODUCTION_LOADED=true`
- MANUAL open=4 / AUTO=0 → **not** restart blocker · isolation proven (orders preserved)
- `SHADOW_EFFECTIVE_START_AT=2026-09-02T21:43:01Z` (feature ACTIVATED_AT ≠ sample start)
- Labs ACTIVE (A/B/C) · sample N=0 · Exit V3 pairing `EXPECTED_PENDING`
- Evidence: `.run/k_upbit_profitability_lab_v1_safe_prod_activation.json`
- NEXT: `NATURAL_SAMPLE_COLLECTION`

---

## U — Profitability Improvement Shadow Lab V1 (2026-09-03)

- WORK: `WRK-20260903-UPBIT-PROFITABILITY-IMPROVEMENT-SHADOW-LAB-V1` · History **#110** · Parent **#102**
- Labs: Candidate Selection V2 (A0–A3) · Exit Optimization V4 (B0–B3) · Reentry Anti-Churn (C0–C3)
- `SHADOW_ONLY` / `FORWARD_ONLY` · REAL candidate/entry/exit/reentry **UNCHANGED** · auto promotion 금지
- Migration `pislabv1a2b3` · Admin research panel + `/profitability-lab/*`
- Commit **`3943566`** · DB migration applied · **activated under History #111**
- Evidence: `.run/k_upbit_profitability_improvement_shadow_lab_v1.json`
- NEXT: superseded by #111 → `NATURAL_SAMPLE_COLLECTION`

---

## U — REAL Runtime Hot-Reload Isolation (2026-09-01)

- WORK: `WRK-20260901-UPBIT-REAL-RUNTIME-HOTRELOAD-ISOLATION-V1` · Parent History **#92** · History **#93**
- Commit **`265e072`** · DEV `APP_RUNTIME_MODE=development` + REAL activation fail-closed · PROD reload=false
- ops-status: `RUNTIME_MODE` / `HOT_RELOAD_ENABLED` / `REAL_RUNTIME_STABLE`
- **RESTART_COUNT=0** · deploy deferred (#2293 open) · restore/ARM gates unchanged
- Evidence: `.run/k_upbit_real_runtime_hotreload_isolation_20260901.json`
- NEXT: `WAIT_OPEN_ORDERS_TERMINAL_THEN_SAFE_DEPLOY`

---

## Parallel policy

**TRACK U** / **TRACK K** / **SHARED** — U+K commit 혼합 금지

---

## K — TOP10 REAL Frontend + Mobile/PWA V1 (2026-09-01)

- WORK: `WRK-20260901-KIWOOM-TOP10-REAL-FRONTEND-MOBILE-V1` · Parent History **#79/#80** · History **#81**
- Commit **`de777ac`** · PC: `/admin/autotrading/kiwoom` — AUTO/LIVE/ARM/LEASE/STACK/FEED/READY + TOP10 REAL 패널
- Mobile: `/mobile/autotrading` — chip 상태 + 종목 카드(펼치기)
- API 재사용: `kiwoom-multi-symbol/status` · NEW API 없음 · trading logic 미변경
- Evidence: `.run/k_kiwoom_top10_real_frontend_mobile_v1.json`
- NEXT: `NORMAL_REAL_OPERATION`

---

## K — TOP10 REAL Multi-Symbol Activation (2026-09-01)

- WORK: `WRK-20260901-KIWOOM-TOP10-REAL-MULTI-SYMBOL-ACTIVATION` · Parent History **#69** · History **#79**
- HEAD includes **`838f588`** (refresh bugfix #80) · MODE **REAL** · shadow obs 유지
- LIVE/ARM/LEASE ON · STACK **4/4** · FEED **REAL_FRESH** · READY · SUBS **11** (TOP10+034310) · socket **1**
- REAL_ORDER_COUNT=0 (자연 Fresh Cross 대기) · Evidence: `.run/k_kiwoom_top10_real_multi_symbol_activation_20260901.json`
- NEXT: `NORMAL_REAL_OPERATION`

---

## U — SYSTEM_FAILURE Root Cause + Safe Recovery (2026-09-01)

- WORK: `WRK-20260901-UPBIT-SYSTEM-FAILURE-SAFE-RECOVERY` · Parent History **#76** · History **#78**
- SoT: AUTO=STOPPED · LIVE=OFF · ARM=OFF/EXPIRED · STACK **2/4** · FEED REAL_FRESH · SYSTEM_FAILURE
- ROOT: ARM TTL expiry @ `2026-08-31T22:31:16Z` → renew fail `db_open remain` → LIVE fail-closed
- Pending AUTO BUY **#2226** KRW-DOS ACCEPTED / Upbit `wait` (**REAL_OPEN_ORDER**) — cancel 금지로 restore 보류
- Shadow Lab **not** cause · CODE_CHANGED=false · Evidence: `.run/k_upbit_system_failure_safe_recovery_20260901.json`
- NEXT: `WAIT_ORDER_2226_FILL_OR_OPERATOR_CANCEL_THEN_UNATTENDED_RESTORE`

---

## U — Waiting Lifecycle Shadow Lab V1 Activation (2026-08-31)

- WORK: `WRK-20260831-UPBIT-WAITING-LIFECYCLE-SHADOW-LAB-V1-ACTIVATION` · Parent History **#75** · History **#76**
- HEAD **`62094ad`** · Migration **`wlshlabv1a2b3`** · Restart **×1** · unattended restore OK
- LIVE/ARM/LEASE ON · STACK **4/4** · FEED **REAL_FRESH** · `partial_restore=false`
- Policy health may show `WAITING_SLOT_STARVATION_BROKEN` — **not** process PARTIAL_RESTORE
- R0–R3 runtime loaded · PRIMARY_FORWARD start recorded · forward N=0 · preexisting excluded
- REAL waiting/entry/exit/AI/risk **UNCHANGED** · no forced order/release/LIVE-ARM
- Evidence: `.run/k_upbit_waiting_lifecycle_shadow_lab_v1_activation.json`
- NEXT: `COLLECT_NATURAL_FORWARD_SAMPLES`

---

## U — Waiting Lifecycle Forward Shadow Lab V1 (2026-08-31)

- WORK: `WRK-20260831-UPBIT-WAITING-LIFECYCLE-FORWARD-SHADOW-LAB-V1` · Parent History **#74** · History **#75**
- Commit **`62094ad`** · Migration **`wlshlabv1a2b3`** applied · Variants R0/R1/R2/R3 research-only
- REAL waiting release/expiry/replacement **UNCHANGED**
- Preexisting cohort enrolled=7×4 (primary forward N=0)
- Activation completed under History **#76** (restart ×1)

---

## U — Waiting Slot Starvation UI Fix + Lifecycle Analysis (2026-08-31)

- WORK: `WRK-20260831-UPBIT-WAITING-SLOT-STARVATION-UI-ANALYSIS-V1` · Parent History **#73** · History **#74**
- Commit **`bfbda95`** · UI: `partial_restore=true`만 PARTIAL_RESTORE; `WAITING_SLOT_STARVATION_BROKEN` → 슬롯 포화 문구
- READ-ONLY package: `.run/k_upbit_waiting_slot_starvation_ui_analysis_v1.json`
- Release/Entry/LIVE 정책 **미변경** · REAL 주문/restart **없음**
- NEXT: `GPT_REVIEW_WAITING_LIFECYCLE`

---

## U — Exit Optimization Shadow Lab V2 Activation (2026-08-31)

- WORK: `WRK-20260831-UPBIT-EXIT-OPTIMIZATION-SHADOW-LAB-V2-ACTIVATION` · History **#72**
- Parent **#71** · HEAD **`43f3d4d`** · migration **`eoslabv2a1b2c3`**
- Restart **×1** · unattended restore OK · LIVE/ARM/LEASE/4/4/REAL_FRESH/READY
- T5–T8 + R1–R3 runtime loaded · REAL trailing unchanged (+1.0% / -0.8%)
- `NATURAL_SAMPLE_PENDING=true` (no forced BUY) · Evidence: `.run/k_upbit_exit_lab_v2_activation.json`

---

## U — Exit Optimization Shadow Lab V2 (2026-08-31)

- WORK: `WRK-20260831-UPBIT-EXIT-OPTIMIZATION-SHADOW-LAB-V2`
- Parent: Daily Perf Review #70 / T5 (#59)
- T5 pairing root cause: finalize without ledger PnL → `BASELINE_NET_NULL`
- Fix: entry_order_id → `binding_closed_trade_metrics` reconcile (`RECONCILED_EXISTING_FORWARD`)
- Variants: T5/T6/T7/T8 forward-only + Re-entry R1/R2/R3 shadow
- Migration: `eoslabv2a1b2c3` applied · REAL trailing **unchanged**
- After reconcile: **T5_VALID_PAIRED_N=31** (EARLY_REVIEW)
- T6/T7/T8 N=0 until natural enroll after process reload
- Restart: **DEFERRED** (research-only; no manual LIVE/ARM)
- Evidence: `.run/k_upbit_exit_optimization_shadow_lab_v2.json`

---

## K — Kiwoom Multi-Symbol SHADOW Closeout V1 (2026-08-31)

- Parent **#66** · refresh **300s→0.6s** (bulk) · STACK **4/4** · ETF-free TOP10
- `MULTI_SYMBOL_SHADOW_READY=false` — NATURAL_REFRESH=1 (misfire grace **00eef65** needs restart)
- Evidence: `.run/k_kiwoom_multi_symbol_shadow_closeout_v1.json`

---

## K — Kiwoom Multi-Symbol SHADOW Activation V1 (2026-08-31)

- Parent **#65** · migration **`kms1a2b3c4d5e` applied** · shadow **ENABLED** · restart **×1**
- TOP10 monitored · feed union **11 symbols** (034310 preserved) · **SHADOW_ONLY**
- `MULTI_SYMBOL_SHADOW_READY=false` — refresh<2 · stack 1/4 · ETF filter fix **cb30074** (next restart)
- Evidence: `.run/k_kiwoom_multi_symbol_shadow_activation_v1.json`

---

## K — Kiwoom Multi-Symbol Autotrading Universe V1 (2026-08-31)

- Parent **#64** · commit **`8a44d86`** · SHADOW/OBSERVE only (`kiwoom_multi_symbol_shadow_enabled` default OFF)
- TOP10 KRX ranking + Golden Cross shadow + feed union (1 physical WS)
- REAL Strategy 17579 / 034310 executor path **unchanged**
- API: `/kiwoom-multi-symbol/status|funnel|refresh`
- Migration: `kms1a2b3c4d5e`

---

## K — Kiwoom REAL Autotrading Readiness V1 (2026-08-31)

- History **#64** · Parent **#63** · Verdict: **KIWOOM_REAL_AUTOTRADING_READY_WAITING_FRESH_GOLDEN_CROSS**
- UBA **1381** / Strategy **17579** / Deployment **#869** / symbol **034310**
- Fix: feed ensure 예외여도 health `REAL_FRESH`면 stack restore 계속 → commit **`8a44d86`**
- Post-tick: stack **4/4** · READY · no-trade = fresh Golden Cross 대기 (신호 없음)
- REAL 주문/수동 LIVE·ARM **없음** · Evidence: `.run/k_kiwoom_real_autotrading_readiness_v1.json`

---

## U — ARM Lease Pre-expiry Renew Reliability V1 (2026-08-31)

- History **#63** · Parent **#62** · Verdict: **ARM_PREEXPIRY_RENEW_RELIABILITY_FIXED**
- Root: renew gate `trading_scheduler_not_paused` while scheduler RUNNING → silent renew miss → TTL expiry
- Fix commit: **`f4e1ab8`** (`force_renew` skips PAUSED requirement; attempt audit; `session_expiry` on ops-status)
- Restart ×1 → unattended restore OK · Next renew due ~**10:25 KST**
- Evidence: `.run/k_upbit_arm_lease_preexpiry_renew_reliability_v1.json`

---

## U — Unexpected Runtime OFF Recovery V1 (2026-08-31)

- History **#62** · Parents **#60/#61** · Verdict: **ROOT_CAUSE_CONFIRMED_ALREADY_RESTORED**
- Root: ARM TTL 3600s 만료 → SYSTEM `LIVE_ARM_EXPIRED` fail-closed (LIVE OFF / ARM OFF / stack pause)
- Outage ~08:17–08:58 KST; watchdog unattended restore at 08:58; this WRK **no** manual LIVE/ARM, **no** restart
- Evidence: `.run/k_upbit_unexpected_runtime_off_recovery_v1.json`

---

## U — BUY Concurrency 2/3/4 Benchmark V1 (2026-08-30)

- Fixture-only C2/C3/C4 compare (fake broker); **operating stays 2/2/2**
- Verdict: **PASS_BUY_CONCURRENCY_2_3_4_BENCHMARK_V1**
- Rec: **RECOMMEND_CONCURRENCY_3_FOR_FUTURE** (rate-limited C3→C4 ~0.7%)
- History **#55** · Parent **#54** · Evidence: `.run/k_upbit_buy_concurrency_2_3_4_benchmark_v1.json`

---

## U — Limited Buy Concurrency V1 (2026-08-30)

- Max concurrent AUTO BUY entries/executor/submit = **2** (invalid → 1)
- SoT: `portfolio_max_pending_entries` + `UPBIT_BUY_*_CONCURRENCY`
- Admission: UBA advisory lock + pending/position atomic checks
- Parent History **#53** · History **#54**
- Evidence: `.run/k_upbit_limited_buy_concurrency_v1.json`

---

## SHARED — Dashboard Today Trading Status V1 (2026-08-30)

- Admin 요약 탭에 **오늘 거래현황** 패널 추가 (업비트/키움/주문/보유 카드 위)
- API 재사용: `/admin/dashboard/autotrading-performance?period=TODAY` (+ summary 확장)
- 중복 상단 KPI 카드 제거 · Trading 로직 불변
- History **#52** · Verdict target: `PASS_DASHBOARD_TODAY_TRADING_STATUS_V1`

---

## SHARED — Google OAuth Login V1 (2026-08-30)

- Google = Authentication · Stock DB = Authorization (자동 가입 금지)
- Endpoints: `/api/v1/auth/google/login|callback|complete|status`
- Migration: `ggl1oauth2v1a2b3` (`user_external_identity`, oauth state/handoff)
- Password fallback 유지 (admin lock-out 방지)
- Related: History **#50** Tailscale production hardening
- Verdict target: **GOOGLE_OAUTH_CODE_READY_CREDENTIALS_REQUIRED** until Google Cloud secrets
- Evidence: `.run/k_google_oauth_login_v1.json`

---

## SHARED — Final Production Hardening V1 (2026-08-30)

- Scope: tmp artifact cleanup · UX 계좌 label · Tailscale `stock` MagicDNS 준비 · FE/BE/DB 감사 · trading 정책 불변
- Tailscale: `svc:stock` = **노드 태그 + Admin Service 승인 필요** (`HUMAN_ACTION_REQUIRED`)
- LottoLab 보존: `https://lottolab.tail3bf7b2.ts.net` 200 · Interim: `http://100.79.126.15:3000`
- Doc: `docs/deployment/TAILSCALE_STOCK_SERVICE.md`
- Evidence: `.run/k_stock_platform_final_production_hardening_v1.json`
- Verdict: **PASS_PLATFORM_READY_TAILSCALE_APPROVAL_REQUIRED**

---

## SHARED — Alert preference Telegram delivery bypass (2026-08-30)

- Symptom: preference OFF인데 Telegram 계속 수신 (후보/슬롯/Shadow/AI)
- Root: `evaluate_telegram_policy` allowlist만 보고 preference 미적용 (**G. ALLOWLIST_OVERRIDES_PREFERENCE**)
- Fix: allowlist 통과 후 `should_deliver_trading_alert` — OFF면 Telegram suppress (거래/분석 로직 유지)
- Commit: **`d31a656`** · Evidence: `.run/k_alert_preference_delivery_bypass_closeout.json`
- Verdict: **PASS_ALERT_PREFERENCE_ENFORCED_END_TO_END**

---

## Current Phase

| Track | STEP | Verdict | Next |
|-------|------|---------|------|
| **U** | Historical Exit Recovery + Long Hold Watch V1 | **PASS_LONG_HOLD_MONITORING_ADA_RECOVERY_NOT_ELIGIBLE** | Restart load long-hold · re-check dry-run when MA bearish · no force SELL |
| **SHARED** | Alert Preference Delivery Bypass Closeout | **PASS_ALERT_PREFERENCE_ENFORCED_END_TO_END** | Natural OBSERVE — OFF keys must not Telegram |
| **SHARED** | Trading Alert V2 Activation Closeout | **PASS_ALERT_V2_ACTIVE_NATURAL_SAMPLE_PENDING** | Observe natural BUY/SELL alerts |
| **U** | Short-Term Operation V1 | **PASS** | OBSERVE entry quota 6 / AUTO slots |
| **U** | Exit Strategy Shadow V1 | **PASS** | OBSERVE shadow rows · no REAL promote |
| **U** | WRK-019 H2/H3 frozen forward-shadow | **H2_H3_FORWARD_SHADOW_INFRA_READY** | OBSERVE forward N · no retune · no REAL promo |
| **U** | 20:39+ no-trade + Data Trust | **UPBIT_RECURRING_FAILURE_ROOT_FIXED_DATA_TRUST_ENABLED** | OBSERVE_VALID_WINDOW · Trailing N10 VALID_ONLY |
| **U** | STALE_PRE_RESTORE equal-epoch | **UPBIT_WAITING_RESTORE_ENTRY_RELIABILITY_FIX** | NATURAL: BEGIN_ENTRY without false STALE |
| **SHARED** | AutoTrading Process Version / Trace / Map | **AUTOTRADING_PROCESS_VERSION_TRACE_VISUAL_MAP_COMPLETE** | Separate: KIWOOM feed + health/ops perf |
| **U** | Entry Shadow research | **ENTRY_THRESHOLD_RELAXATION_NOT_PROMISING** | REAL entry 변경 금지 · 관측 유지 |
| **U** | Prod AI Gate 312s latency | **UPBIT_PROD_AI_GATE_LATENCY_FIXED** | OBSERVE_UPBIT_5MIN_SCANNER_WITH_FAST_PROD_AI_GATE |
| **SHARED** | UPBIT+KIWOOM CLEAN RAG Feedback | **READY_NOT_NATURALLY_OBSERVED** | COLLECT_UPBIT_AND_KIWOOM_RAG_FEEDBACK_CLEAN_SAMPLE |
| **K** | Next Trading Day Auto Start | **ENABLED_READY** | OBSERVE_NEXT_KRX_SESSION_AUTO_START · FEED_DOWN pending |

---

## U — STALE_PRE_RESTORE equal-epoch (2026-08-28)

- Root: restore nudge `updated_at == restored_at` + gate `waiting <= cutoff` → false STALE
- Fix: `waiting < cutoff` · nudge forces `updated_at > restored_at`
- Change History: **UPBIT_WAITING_RESTORE_ENTRY_RELIABILITY_FIX**
- Evidence: `.run/k_upbit_stale_pre_restore_waiting_audit.*`
- TTL/MA/portfolio/daily 변경 없음 · Process Version bump=false

---

## U — 20:39+ no-trade root + Data Trust (2026-08-27 night)

- Root: `STALE_PRE_RESTORE_WAITING` false-positive after `begin_entry` (waiting_at=None)
- Fix: NOT_WAITING_SLOT skip · restore-epoch None only if outage_active · waiting nudge · funnel E0-only
- Data Trust: quality window + incident ledger + shadow quarantine (`dq1a2b3c4d5e`)
- Natural proof: orders **1905/1906** FILLED (not forced)
- Evidence: `.run/k_upbit_2039_no_trade_root_data_trust.*`
- REAL entry/exit/trailing/daily policy 변경 없음

---

## U — Prod AI Gate fix (2026-08-25 evening)

- Root: Scanner chart job used **qwen3.5:4b** + reuse 180s &lt; interval 300s
- Fix: Analysis **1.7b** + scanner reuse 600s + shadow dual LLM background queue
- Prod-path bench: AI_GATE median **19ms**, scanner median **4.5s**
- Evidence: `.run/k_upbit_prod_ai_gate_latency_audit.*`
- Live uvicorn restart may need manual OS kill if port ghost PID persists

---

## U — Scanner interval

- Commit `717944b` — candle concurrency 8, AI concurrency 2, warmup debounce, single-flight telemetry
- Env `UPBIT_OPPORTUNITY_SCANNER_INTERVAL_SECONDS=300` after median/p95 gate
- Evidence: `.run/k_upbit_scanner_latency_optimization.*`

---

## SHARED — Dual LLM RAG (market isolated)

- Common engine: `operation/dual_llm` (markets, prompt versions)
- UPBIT + KIWOOM SHADOW; cross-market RAG = 0
- KIWOOM hook: `publish_scoped_signal` 이후 fail-open thread (MA REAL 미차단)
- LoRA training **NO**
- Evidence: `.run/k_upbit_kiwoom_rag_feedback_integration.*`

---

## SHARED — Process Version + Decision Trace + Visual Map (2026-08-27)

- OBSERVABILITY ONLY — REAL entry/exit/policy/LIVE/ARM 변경 없음
- Tables: `operation.autotrading_process_*` + `execution_trace` / `trace_event`
- Admin UI: `/admin/autotrading/process`
- Baseline: `UPBIT_AUTO_V1` / `KIWOOM_AUTO_V1` · today PARTIAL traces (5 RT + blocked + Kiwoom FEED_DOWN)
- Evidence: `.run/k_autotrading_process_version_trace_visual_map.{json,md}`
- Pending separate: `KIWOOM_MARKET_DATA_FAILURE`, `HEALTH_OPS_PERFORMANCE_ISSUE`
- Note: PROD restart 후 in-memory STOPPED 가능 — LIVE/ARM 복구는 Admin 기존 제어로

---

## Next Gate

**SHARED:** Restore UPBIT stack via Admin if needed · COLLECT_UPBIT_AND_KIWOOM_RAG_FEEDBACK_CLEAN_SAMPLE  
**K:** KIWOOM_MARKET_DATA_FAILURE (별도) · OBSERVE_NEXT_KRX_SESSION_AUTO_START
