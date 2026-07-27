# STEP 11-5 — AI 실행 요청 · 결과 저장 · 비용 추적 기반

## Architecture

```
Admin create_request (DB only)
        │
dry-run / execute (명시)
        │
Prepare (Prompt/Schema/Policy/Input)
        │
commit RUNNING + lease
        │
Provider call (attempt = execution_run)
        │
Validate (STEP 11-4 pipeline)
        │
Safe Result + Cost/Tokens
```

**금지:** 저장=실행, 전략 Task 실행, AI→주문/LIVE/ARM/Scheduler, Telegram 실행.

## State Machine

Request: DRAFT/READY → RUNNING → SUCCEEDED|SUCCEEDED_WITH_WARNINGS|FAILED|BLOCKED|TIMED_OUT|CANCELLED|ABANDONED

Run: CREATED → STARTED → PROVIDER_* → VALIDATION_* → COMPLETED

잘못된 역전이 차단.

## Modes

| Mode | 외부 호출 | 조건 |
|------|-----------|------|
| DRY_RUN | 0 | render/검증/예상비용만 |
| MOCK | Mock만 | 기본 |
| EXTERNAL | 실 Provider | confirm=true + enabled + VERIFIED cred |

## 허용 Task

CHAT, SUMMARIZE만 실행. STRATEGY_DRAFT 등 → `AI_TASK_EXECUTION_NOT_ENABLED`.

## 저장 정책

- Raw Prompt/Response 기본 미저장
- input_hash / rendered_prompt_hash
- Safe Result만 저장 (`raw_response_retained=false`)
- Audit에 원문 제외

## Idempotency / Lease

- `(requested_by, idempotency_key)` UNIQUE
- execute 시 lease; 동시 execute 차단
- Startup: lease 만료 RUNNING/QUEUED → **ABANDONED** (자동 외부 재호출 0)

## Cost

- `ai.provider_pricing` 운영자 입력값만 사용 (SEED_TEST ≠ 실요금 단정)
- Mock = NOT_APPLICABLE / null
- 미설정 = null (0 오인 금지)
- Budget Guard: request budget + optional daily setting

## Admin API

`/api/v1/admin/ai/executions` (+ dry-run/execute/cancel/retry-as-new/runs/result/events)
`/api/v1/admin/ai/costs/*`

## Frontend

`/admin/ai/executions`

## Dashboard / Telegram

집계만. `/ai_executions`, `/ai_costs` 조회. 실행/취소 금지.

## Migration

`w3d4e5f6a7b8` ← `v2c3d4e5f6a7`

## Rollback

1. 실행 중단/Cancel  
2. downgrade `-1`  
3. Mock 기본 유지  

## 향후 STEP 11-6

업무 Task(뉴스/차트/전략 초안) 실행 연결 시에도 주문·배포와 분리 유지.
