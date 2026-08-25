# Ollama Role Model — Prod Reload Verify

FINAL_VERDICT: **OLLAMA_ROLE_MODEL_MANAGEMENT_COMPLETE**

## Restart

- BACKEND_RESTART_COUNT: **1** (`ops/start_backend_prod.ps1 -Force`)
- BACKEND_PID: **25592**
- PORT_8000_LISTENER_COUNT: **1**
- GHOST_PROCESS: **0**

## API

- ROLE_MODELS_API_HTTP: **200**
- INSTALLED_MODEL_COUNT: **3**
- INSTALLED_MODELS: `qwen3:1.7b`, `qwen3.5:2b`, `qwen3.5:4b`
- ANALYSIS = `qwen3:1.7b`
- TRADING = `qwen3.5:2b`
- TEACHER = `qwen3.5:4b`
- FALLBACK = `qwen3.5:4b`
- TRADING_LLM_MODE = **SHADOW**
- TRADING_LLM_REAL_GATE = **false**

## Browser `/admin/ollama`

- ADMIN_OLLAMA_UI / ROLE_MODEL_SELECT / AUTH_BROWSER_VERIFY = **true**
- Select count = 4
- SHADOW 표시 / raw JSON은 Collapse만
- 저장 버튼 미클릭 (`ROLE_SETTING_MUTATION=0`)
- CONSOLE_ERRORS=0 WARNINGS=0 HTTP_404=0 HTTP_500=0 ANTD_DEPRECATIONS=0

## Autotrading after restart

### UPBIT UBA1380
LIVE/ARM ON · Runtime/Runner/Worker/Exit/Scanner RUNNING · Feed REAL_FRESH → **RECOVERED**

### KIWOOM UBA1381
LIVE/ARM OFF · Runtime STOPPED · market-realtime **not** force-started → OK

## Safety

ROLE_SETTING_MUTATION=0 · REAL_TRADING_MUTATION=0 · MODEL_INSTALL=0 · MODEL_DELETE=0

## Git

- Feature: `0d5051b`
- AntD List fix: `ebec7f4`

NEXT_ACTION: **CONTINUE_NORMAL_OPERATION**
