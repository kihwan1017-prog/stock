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
| **SHARED** | UPBIT+KIWOOM CLEAN RAG Feedback | **READY_NOT_NATURALLY_OBSERVED** | COLLECT_UPBIT_AND_KIWOOM_RAG_FEEDBACK_CLEAN_SAMPLE |
| **K** | Next Trading Day Auto Start | **ENABLED_READY** | OBSERVE_NEXT_KRX_SESSION_AUTO_START |

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
