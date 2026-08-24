# UPBIT + KIWOOM Dual LLM RAG/Feedback Integration

**Verdict:** `UPBIT_KIWOOM_RAG_FEEDBACK_READY_NOT_NATURALLY_OBSERVED`

## Design

- **COMMON_ENGINE_REUSED** — `operation/dual_llm` (markets, market-aware prompts)
- Similarity / feedback / teacher / dataset / Ollama runtime **재사용**
- KIWOOM thin adapter: `operation/kiwoom_dual_llm/*`
- **DUPLICATE_ENGINE_CREATED = NO**

## Market isolation

- Every RAG case tagged `market`
- UPBIT retrieve rejects non-UPBIT; KIWOOM retrieve rejects non-KIWOOM
- Cross-market examples filtered before Trading prompt
- Sample gates / dataset / export **market-separated** (no UPBIT+KIWOOM sum)

## KIWOOM SHADOW hook

- After REAL `publish_scoped_signal` succeeds
- Background daemon thread + own DB session
- Fail-open — MA evaluator / Risk / Order **never wait on LLM**
- `KIWOOM_TRADING_LLM_MODE = SHADOW`

## Context SoT

- `CandidateContextBuilder` (price_daily, indicators, news, DART)
- MA metadata (short/long) for separation
- No new external scrapers

## UI

- `/admin/ai-analysis?market=KIWOOM` — KiwoomDualLlmPanel
- `/admin/research?market=KIWOOM` — RAG / Feedback tab
- UPBIT panels unchanged (regression pytest PASS)

## Safety

- REAL / LIVE / ARM / Risk / Slot / trading mutations = 0
- LoRA training = NO

## Next

`COLLECT_UPBIT_AND_KIWOOM_RAG_FEEDBACK_CLEAN_SAMPLE`
