# CURRENT_WORK

**역할:** 현재 진행 중인 작업만 기록한다.  
**최종 갱신:** 2026-08-30 (UPBIT-LIMITED-BUY-CONCURRENCY-V1)

---

## Parallel policy

**TRACK U** / **TRACK K** / **SHARED** — U+K commit 혼합 금지

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
