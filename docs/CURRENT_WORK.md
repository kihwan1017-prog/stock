# CURRENT_WORK

**역할:** 현재 진행 중인 작업만 기록한다.  
**최종 갱신:** 2026-08-25 (UPBIT+KIWOOM Dual LLM RAG isolation READY)

---

## Parallel policy

**TRACK U** / **TRACK K** / **SHARED** — U+K commit 혼합 금지

---

## Current Phase

| Track | STEP | Verdict | Next |
|-------|------|---------|------|
| **U** | Prod AI Gate 312s latency | **UPBIT_PROD_AI_GATE_LATENCY_FIXED** | OBSERVE_UPBIT_5MIN_SCANNER_WITH_FAST_PROD_AI_GATE (manual backend restart if ghost PID) |
| **U** | Scanner 5min latency optimization | **UPBIT_SCANNER_5MIN_OPTIMIZED** | superseded by AI Gate model/reuse fix |
| **SHARED** | UPBIT+KIWOOM CLEAN RAG Feedback | **READY_NOT_NATURALLY_OBSERVED** | COLLECT_UPBIT_AND_KIWOOM_RAG_FEEDBACK_CLEAN_SAMPLE |
| **K** | Next Trading Day Auto Start | **ENABLED_READY** | OBSERVE_NEXT_KRX_SESSION_AUTO_START |

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

## Next Gate

**SHARED:** COLLECT_UPBIT_AND_KIWOOM_RAG_FEEDBACK_CLEAN_SAMPLE  
**K:** OBSERVE_NEXT_KRX_SESSION_AUTO_START
