# Dual LLM RAG + Feedback Learning Pipeline

**Verdict:** `DUAL_LLM_RAG_FEEDBACK_PIPELINE_READY_NOT_NATURALLY_OBSERVED`

## Models (unchanged SoT)

| Role | Model | Mode |
|------|-------|------|
| ANALYSIS | qwen3:1.7b | research |
| TRADING | qwen3.5:2b | **SHADOW** |
| TEACHER | qwen3.5:4b | selective audit |

## Implemented

1. **CLEAN-only hybrid RAG** — structured feature similarity + TTL cache (no Vector DB)
2. **No-lookahead** — `outcome_completed_at < candidate.detected_at`
3. **Trading SHADOW input** — candidate / technical / analysis / rag_examples (TOP_K=5)
4. **Feedback scoring** on shadow COMPLETE — ALLOW/HOLD/REDUCE diagnostic verdicts
5. **Selective Teacher** — low priority, max rate 15%, not ground truth
6. **Learning examples** — GOLD/SILVER/EXCLUDED + time-ordered split metadata
7. **JSONL export prep** — `/dual-llm/export/{analysis|trading}` (`RESEARCH_EXPORT_ONLY` if N&lt;1000)
8. **UI** — AI Analysis Dual LLM KPIs + Research **RAG / Feedback** tab/drawer

## Storage

- Reuses `operation.upbit_llm_context_analysis.output_json` (`upbit_dual_llm_rag_v1`)
- No new CLEAN/outcome tables; no REAL business data mutation

## Safety

- `TRADING_LLM_MODE=SHADOW`
- REAL / LIVE / ARM / Risk / Slot / Kiwoom / Trading real-gate mutations = 0
- Protective exits remain LLM-independent
- LoRA training **not** started

## Tests / Frontend

- pytest: 15 passed (RAG + wiring)
- `npm run check:frontend` PASS (antd / lint / typecheck / focused UI 34)

## Natural observation

- Forced candidate **not** created
- DB dual-schema rows at probe time: **0**
- → `CODE_READY_NOT_NATURALLY_OBSERVED`

## Next

`COLLECT_RAG_FEEDBACK_CLEAN_SAMPLE`
