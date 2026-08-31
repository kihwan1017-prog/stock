# CURRENT_WORK

**역할:** 현재 진행 중인 작업만 기록한다.  
**최종 갱신:** 2026-08-31 (UPBIT-WAITING-SLOT-STARVATION-UI-ANALYSIS-V1)

---

## Parallel policy

**TRACK U** / **TRACK K** / **SHARED** — U+K commit 혼합 금지

---

## U — Waiting Slot Starvation UI Fix + Lifecycle Analysis (2026-08-31)

- WORK: `WRK-20260831-UPBIT-WAITING-SLOT-STARVATION-UI-ANALYSIS-V1` · Parent History **#73**
- UI: `partial_restore=true`만 PARTIAL_RESTORE; `WAITING_SLOT_STARVATION_BROKEN` → 슬롯 포화 문구
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
