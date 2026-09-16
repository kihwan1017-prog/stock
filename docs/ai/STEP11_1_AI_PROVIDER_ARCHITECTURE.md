# STEP 11-1 — AI Provider Architecture (Foundation)

## 목표

AI Provider와 무관한 **공통 인터페이스·Manager·Registry** 를 구축한다.

이번 STEP에서는 **전략 생성·뉴스/차트 분석·자동 주문·실 API 자동매매를 구현하지 않는다.**

## Architecture

```
Admin / Dashboard / Telegram
        │
        ▼
    AIManager
        │  select / fallback / retry / timeout / circuit / metrics
        ▼
 AIProviderRegistry
        │
        ├── MockAIProvider      (필수, 실호출 0)
        ├── OpenAIProvider      (skeleton, 기본 disabled)
        ├── ClaudeProvider      (skeleton)
        ├── GeminiProvider      (skeleton)
        ├── OllamaProvider      (skeleton)
        └── OpenAICompatible    (skeleton)
```

패키지: `src/stock_platform/ai/providers/`

## Provider Interface

`AIProvider` (Async 우선):

- `initialize()` / `shutdown()`
- `health()`
- `chat()` / `chat_stream()`
- `analyze_news()` / `analyze_chart()` / `generate_strategy()` / `summarize()`
- `embedding()`
- `capabilities()` / `supports()`

Streaming은 `chat_stream()` → `AsyncIterator[StreamChunk]` 로 설계.

## DTO

공통: `AIChatRequest`, `AIAnalyzeRequest`, `AIResponse`, `TokenUsage`,
`FinishReason`, `ProviderHealth`, `Citation`, `ProviderErrorInfo`, `StreamChunk`

Provider 응답은 반드시 DTO로 변환한다.

## Capability

`CHAT`, `NEWS`, `VISION`, `TOOLS`, `EMBEDDING`, `JSON`, `STREAM`,
`FUNCTION_CALL`, `STRATEGY`, `CHART`, `SUMMARIZE`

Provider마다 frozenset으로 선언.

## AIManager

| 기능 | 설명 |
|------|------|
| Registry | Provider 등록/조회 |
| Select | default / capability / explicit id |
| Fallback | 실패 시 priority 순 다음 Provider |
| Retry | `retry_max` + backoff |
| Timeout | `asyncio.wait_for` |
| Circuit Breaker | failure threshold → OPEN |
| Metrics | calls / latency / errors |
| Dashboard | `dashboard_block()` Summary 섹션 |

## Config

Settings / `.env` (`AI_PROVIDER_*`)

- Enable, Priority, Default, Timeout, Retry, Model, Endpoint, API Key
- Key는 `public_dict()` / 로그에서 **마스킹**

기본: Mock enabled + default.

## Security

- `mask_secret`, `mask_pii`, `sanitize_for_log`
- API Key 로그 출력 금지
- Admin 응답은 `public_dict()` / sanitize

## Mock Provider

- 고정 시그널: `BUY` / `HOLD` / `SELL`
- Latency / Error / Timeout 시뮬레이션
- 실 외부 API 호출 없음 → 전체 회귀 테스트 가능

## API (Admin, Read-only + test)

| Method | Path | 설명 |
|--------|------|------|
| GET | `/api/v1/admin/ai/providers` | 목록 |
| GET | `/api/v1/admin/ai/providers/{id}` | 단건 |
| GET | `/api/v1/admin/ai/providers/health` | Health |
| POST | `/api/v1/admin/ai/providers/test` | Mock/구성 Provider ping |

전략 생성·주문 API 없음.

## Dashboard

Operations Center Summary에 `ai_providers` 섹션 추가.

UI: `/admin/dashboard` → **⑩ AI Providers** 카드
(Provider / Status / Model / Version / Latency / Capabilities)

## Telegram

| Command | 설명 |
|---------|------|
| `/providers` | Provider 목록 (Summary 재사용) |
| `/provider_health` | Health 조회 |

조회만. 자동 주문/LIVE/ARM 변경 없음.

## 확장 방법

1. `AIProvider` 구현 클래스 추가
2. `build_default_registry()` factories에 등록
3. Settings / `.env`에 `AI_PROVIDER_<NAME>_*` 추가
4. 실 HTTP 호출은 Provider `chat()` 내부에만 구현 (Manager는 DTO만 다룸)

## Tests

```bash
pytest tests/test_step11_1_ai_provider_architecture.py -q
```

실제 OpenAI/Claude/Gemini/Ollama 호출 없이 PASS.

## Safety checklist

- [x] Mock Provider 동작
- [x] Registry / Manager / Capability / Health
- [x] Dashboard / Telegram 조회
- [x] 실 AI 호출 0 (기본 경로)
- [x] 전략 생성 연결 0
- [x] 주문 0
