# CURRENT_WORK

**역할:** 현재 진행 중인 작업만 기록한다.  
**최종 갱신:** 2026-08-25 (Dual LLM RAG + Feedback pipeline READY)

---

## Parallel policy

**TRACK U** / **TRACK K** / **SHARED** — U+K commit 혼합 금지

---

## Current Phase

| Track | STEP | Verdict | Next |
|-------|------|---------|------|
| **U** | Dual LLM RAG + Feedback Learning Pipeline | **READY_NOT_NATURALLY_OBSERVED** | COLLECT_RAG_FEEDBACK_CLEAN_SAMPLE |
| **K** | Next Trading Day Auto Start | **ENABLED_READY** | OBSERVE_NEXT_KRX_SESSION_AUTO_START |

---

## U — Dual LLM RAG + Feedback (research only)

- ANALYSIS=qwen3:1.7b · TRADING=qwen3.5:2b SHADOW · TEACHER=qwen3.5:4b selective
- CLEAN hybrid RAG (no Vector DB) · Feedback · GOLD/SILVER export prep
- LoRA training **not** started · REAL gate unchanged
- Evidence: `.run/k_dual_llm_rag_feedback_pipeline.json` / `.md`

---

## K — Next-day auto-start (enabled)

- Opt-in ON (UBA1381, auth#7, source Activation #46)
- EOD: LIVE/ARM OFF · PROTECTIVE_EXIT_ONLY
- Account sync: live Kiwoom account-state sync before LIVE
- Evidence: `.run/k_kiwoom_next_day_auto_start_enable.json` / `.md`

---

## Next Gate

**U:** COLLECT_RAG_FEEDBACK_CLEAN_SAMPLE  
**K:** OBSERVE_NEXT_KRX_SESSION_AUTO_START
