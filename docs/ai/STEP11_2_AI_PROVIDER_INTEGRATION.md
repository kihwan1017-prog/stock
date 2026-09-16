# STEP 11-2 — AI Provider Integration (안전한 Health/Test 연결)

## 목표

STEP 11-1 Foundation 위에 **실제 Provider Adapter** 를 연결한다.

허용: Health, 최소 Chat Test, Metrics, Admin 수동 Test  
금지: 전략 생성 업무 연결, 자동주문, LIVE/ARM/Scheduler/Runtime 변경

기본 Provider는 **Mock** 유지. 외부 Provider는 `enabled=true` + Credential 있을 때만 Test 가능.

## Architecture 변경

대형 재설계 없음.

```
Admin Test / Health-check
      │
 AIManager (retry/timeout/circuit/fallback/metrics/health-cache)
      │
 Provider Adapters (httpx, SDK 없음)
      ├── Mock
      ├── OpenAI (/v1/chat/completions, /v1/models)
      ├── Claude (/v1/messages)
      ├── Gemini (:generateContent, /models)
      ├── Ollama (/api/tags, /api/chat)
      └── OpenAI Compatible (/chat/completions)
```

- HTTP 재시도는 **Manager만** 수행 (Adapter 내부 자동 retry 없음)
- Dashboard/Telegram 조회는 **Health Cache / 로컬 스냅샷만** (외부 호출 0)

## Credential

| 방식 | 상태 |
|------|------|
| 환경변수 Settings | **현재 사용** |
| Broker Credential Vault | 스키마 불일치로 미결합 (암호화 유틸 재사용 가능) |
| DB 평문 저장 | **금지** |

API Key는 응답·로그·Audit에 마스킹. Migration 없음.

## HTTP Client

`ai/providers/http_client.py`

- connect/read timeout, User-Agent
- 오류 본문 길이 제한
- Secret Header 마스킹
- Retry-After 헤더 수집 (Manager가 retryable로 처리)
- Adapter 자동 retry **없음**

## 최대 실제 호출 횟수

`max_calls ≈ (retry_max + 1) × fallback_chain_length`

예: retry_max=2, fallback 2개 → 최대 6회.

## Health 상태

`DISABLED`, `NOT_CONFIGURED`, `INITIALIZING`, `HEALTHY`, `DEGRADED`,
`RATE_LIMITED`, `AUTH_FAILED`, `MODEL_NOT_FOUND`, `TIMEOUT`, `OFFLINE`,
`CIRCUIT_OPEN`, `ERROR`, `SAFETY_BLOCKED`, …

순서: 로컬 설정 → 저비용 endpoint → (Admin health-check 시) live probe → 캐시

## Admin API

| Method | Path |
|--------|------|
| GET | `/api/v1/admin/ai/providers` |
| GET | `/api/v1/admin/ai/providers/health` (cache) |
| GET | `/api/v1/admin/ai/providers/{id}` |
| POST | `/api/v1/admin/ai/providers/{id}/initialize` |
| POST | `/api/v1/admin/ai/providers/{id}/health-check` |
| POST | `/api/v1/admin/ai/providers/{id}/test` |
| POST | `/api/v1/admin/ai/providers/test` (legacy) |

Test 제한: prompt ≤2000, max_tokens ≤256, user/provider rate limit 10/min, Audit.

`generate_strategy` 호출 없음. chat만.

## Dashboard / Telegram

- Dashboard: Enabled/Configured/Health/Model/Endpoint/Latency/Circuit/Requests …
- Telegram: `/providers`, `/provider_health` (cache), `/provider <name>`
- Telegram Test 호출 **없음**

## 테스트

기본: Mock HTTP (`httpx.MockTransport`) — 외부 AI 0회

```bash
pytest tests/test_step11_2_ai_provider_integration.py -q
```

선택적 실호출:

```bash
pytest -m live_ai   # Credential·운영자 승인 필요, 기본 addopts에서 제외
```

## 운영 활성화

1. `.env`에 Provider Key/Endpoint 설정
2. `AI_PROVIDER_<NAME>_ENABLED=true`
3. Admin `POST .../health-check` 또는 `.../test` (prompt: `Return exactly: OK`)
4. Mock default 유지 권장

## Rollback

1. 해당 Provider `ENABLED=false`
2. 또는 Mock only로 복귀
3. 코드 revert 시 Manager/Mock 회귀 테스트로 확인

## Safety

- 실주문 / Broker submit / Strategy 배포 / LIVE·ARM 변경: **0**
- STEP 11-3 미진행
