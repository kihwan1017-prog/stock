# Ollama Role Model Management UI

FINAL_VERDICT: **OLLAMA_ROLE_MODEL_UI_IMPLEMENTED_PENDING_BACKEND_RELOAD**

## 1. Current Config Audit

| SETTING | DB_VALUE | ENV_VALUE / defaults | RUNTIME_RESOLVED_VALUE | FALLBACK_RULE |
|---------|----------|----------------------|------------------------|---------------|
| ollama_model | qwen3.5:4b | qwen3.5:4b | qwen3.5:4b | reference / Teacher empty fallback |
| analysis_llm_model | (seeded on first settings list) | qwen3:1.7b | qwen3:1.7b | empty → hardcoded `qwen3:1.7b` (**not** ollama_model) |
| trading_llm_model | (seeded on first settings list) | qwen3.5:2b | qwen3.5:2b | empty → hardcoded `qwen3.5:2b` (**not** ollama_model) |
| teacher_llm_model | (empty default) | "" | qwen3.5:4b | empty → **ollama_model** |
| ollama_base_url | http://127.0.0.1:11434 | same | same | — |
| ollama_timeout_seconds | 120.0 | 120.0 | 120.0 | — |
| ollama_temperature | 0.25 (DB) / 0.2 (ENV) | 0.2 | get_settings=0.2; Ollama status uses DB | DB overlay for /ollama/* only until save sync |
| ollama_keep_alive | 10m | 10m | 10m | — |

ROLE_SETTINGS_SOT: **ENV `get_settings()` for Dual LLM runtime**; DB catalog + **env sync on save** for role keys.

TRADING_LLM_MODE: **SHADOW** (hardcoded in dual-llm status; no REAL gate UI).

## 2–10. Implementation

- `/admin/ollama` — 역할별 모델 Select(설치 목록만) + SHADOW 배지 + 친화적 설치 목록 + 개발자 Collapse
- `GET/PUT /api/v1/ollama/role-models` — 설치 모델 검증 후 저장, page-load mutation 없음(시드만)
- MODEL_INSTALL/DELETE/LORA/REAL gate mutation = 0

## Verification

- GET /ollama/models → 3 models (live)
- Runtime resolve (venv import): ANALYSIS=qwen3:1.7b TRADING=qwen3.5:2b TEACHER=qwen3.5:4b FALLBACK=qwen3.5:4b
- Frontend: lint / typecheck / check:antd-compat / focused tests PASS
- Auth browser: page reachable; role-models API **404 until backend reload** (prod uvicorn no --reload)
- BACKEND_RESTART_COUNT: **0** (강제 재시작 미실시)

## Safety

MODEL_INSTALL=0 MODEL_DELETE=0 LORA_TRAINING=0  
REAL_ORDER_MUTATION=0 LIVE_ARM_MUTATION=0 RISK_MUTATION=0 SLOT_MUTATION=0  
TRADING_LLM_REAL_GATE_MUTATION=0

NEXT_ACTION: CONTINUE_NORMAL_OPERATION  
(운영 반영 시: backend 1회 reload 후 `GET /ollama/role-models` 재확인)
