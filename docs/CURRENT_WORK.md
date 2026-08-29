# CURRENT_WORK

**역할:** 현재 진행 중인 작업만 기록한다.  
**최종 갱신:** 2026-08-29 (SOURCE-DOC-CLEANUP-V1)

---

## Parallel policy

**TRACK U** / **TRACK K** / **SHARED** — U+K commit 혼합 금지

---

## Current Phase

| Track | STEP | Verdict | Next |
|-------|------|---------|------|
| **U** | Historical Exit Recovery + Long Hold Watch V1 | **PASS_LONG_HOLD_MONITORING_ADA_RECOVERY_NOT_ELIGIBLE** | Restart load long-hold · re-check dry-run when MA bearish · no force SELL |
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
