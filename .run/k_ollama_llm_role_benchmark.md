# Ollama LLM Role Benchmark

FINAL_VERDICT: **OLLAMA_LLM_ROLE_BENCHMARK_COMPLETE**

ANALYSIS_LLM_RECOMMENDED = `qwen3:1.7b`
TRADING_LLM_RECOMMENDED = `qwen3:1.7b`

## BEFORE (production untouched)
```json
{
  "ollama_base_url": "http://127.0.0.1:11434",
  "ollama_model": "qwen3.5:4b",
  "ollama_timeout_seconds": 120.0,
  "ollama_temperature": 0.2,
  "ollama_keep_alive": "10m",
  "num_predict_in_chat_structured": 1024,
  "think": false,
  "autotrading_ai_analysis_model": "qwen3.5:4b",
  "autotrading_ai_analysis_enabled": false,
  "autotrading_ai_signal_gate_live_enabled": false,
  "upbit_market_context_candidate_llm_enabled": true,
  "candidate_llm_path": "heuristic_llm_analyze (research fail-open; not Ollama by default)",
  "ollama_client": "src/stock_platform/ai/ollama_client.py",
  "llm_to_real_order_path": "NONE for market-context candidate LLM (research_only, may_create_orders=false)",
  "fail_open_research": "HOLD + CONTEXT_UNAVAILABLE on LLM/context failure",
  "fail_closed_live_ai_gate": "autotrading_ai_live_fail_closed=True when gate enabled"
}
```

## Per model
### qwen3:1.7b
- median latency: 8413.371200000001
- tokens/sec: 17.490028460801824
- quality score: 0.725
- stability: 1.0
- RAM/CPU (client process proxy): 42.1 / 62.9
- errors/timeouts: 0/0
- strengths: 최저 latency, 최고 tokens/sec, timeout 0, 동시 호출에도 Trading 완료
- weaknesses: 숫자/뉴스 보존·ANALYSIS 품질이 2b/4b 대비 소폭 낮음

### qwen3.5:2b
- median latency: 19376.96055
- tokens/sec: 10.918836674752574
- quality score: 0.775
- stability: 1.0
- RAM/CPU (client process proxy): 46.7 / 61.5
- errors/timeouts: 0/0
- strengths: ANALYSIS 품질 median 최고권, timeout 0, 1.7b 대비 해석 보존 우수
- weaknesses: latency ~2.3× of 1.7b, Mini-PC에서 동시 부하 시 Trading 지연 가능

### qwen3.5:4b
- median latency: 27911.6783
- tokens/sec: 8.0342646349286
- quality score: 0.775
- stability: 1.0
- RAM/CPU (client process proxy): 48.9 / 56.45
- errors/timeouts: 1/1
- strengths: 현 production 기본 모델, ANALYSIS 품질 상위권
- weaknesses: 가장 느림, 1회 TIMEOUT(120s), Ollama residency ~3.1GB CPU 100% 관측

## ANALYSIS_LLM_SCORE_TABLE
```json
{
  "qwen3:1.7b": {
    "speed": 57.53,
    "quality": 72.5,
    "stability": 100.0,
    "load": 85.98,
    "total": 71.98,
    "latency_ms": 8413.371200000001,
    "tps": 17.490028460801824,
    "mem_proxy_mb": 42.1
  },
  "qwen3.5:2b": {
    "speed": 39.62,
    "quality": 77.5,
    "stability": 100.0,
    "load": 67.71,
    "total": 64.74,
    "latency_ms": 19376.96055,
    "tps": 10.918836674752574,
    "mem_proxy_mb": 46.7
  },
  "qwen3.5:4b": {
    "speed": 26.8,
    "quality": 77.5,
    "stability": 100.0,
    "load": 53.48,
    "total": 58.19,
    "latency_ms": 27911.6783,
    "tps": 8.0342646349286,
    "mem_proxy_mb": 48.9
  }
}
```

## TRADING_LLM_SCORE_TABLE
```json
{
  "qwen3:1.7b": {
    "speed": 57.53,
    "quality": 72.5,
    "stability": 100.0,
    "load": 85.98,
    "total": 77.73,
    "latency_ms": 8413.371200000001,
    "tps": 17.490028460801824,
    "mem_proxy_mb": 42.1
  },
  "qwen3.5:2b": {
    "speed": 39.62,
    "quality": 77.5,
    "stability": 100.0,
    "load": 67.71,
    "total": 74.57,
    "latency_ms": 19376.96055,
    "tps": 10.918836674752574,
    "mem_proxy_mb": 46.7
  },
  "qwen3.5:4b": {
    "speed": 26.8,
    "quality": 77.5,
    "stability": 100.0,
    "load": 53.48,
    "total": 70.58,
    "latency_ms": 27911.6783,
    "tps": 8.0342646349286,
    "mem_proxy_mb": 48.9
  }
}
```

## Selection reasons
ANALYSIS weights speed40/quality35/stability15/load10 → qwen3:1.7b score=71.98

TRADING weights quality45/stability25/speed20/load10 → qwen3:1.7b score=77.73

## Concurrent
- ANALYSIS_AND_TRADING_CONCURRENT_SAFE = True
- TRADING_REQUEST_STARVATION = False
- MEMORY_PRESSURE = False

## Architecture prep (not wired)
{
  "proposed_settings": [
    "analysis_llm_model (fallback ollama_model)",
    "trading_llm_model (fallback ollama_model)",
    "independent timeout/temperature/max_tokens/keep_alive per role",
    "queue priority: TRADING > ANALYSIS (design only)"
  ],
  "reuse_client": "stock_platform.ai.ollama_client.OllamaClient",
  "wired_into_production": false
}

PRODUCTION_MODEL_CHANGED = NO
REAL_POLICY_CHANGED = NO
NEXT_ACTION = REVIEW_OLLAMA_LLM_BENCHMARK_WITH_CHATGPT
