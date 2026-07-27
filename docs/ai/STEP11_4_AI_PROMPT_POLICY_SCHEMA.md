# STEP 11-4 — AI Prompt · Policy · Output Schema 관리 기반

## Architecture

```
Admin Preview / Dry-run
        │
PromptPolicyResolver 개념 → PreviewService
        │
Variable Validator → Safe Renderer → Security Inspect
        │
(Mock) Raw Response → Parser → Schema Validator → Policy/Core Safety
        │
Safe AI Result (주문/LIVE/ARM/Scheduler 연결 없음)
```

**이번 STEP:** 실제 AIManager 호출·전략 생성·자동매매 **미구현**. Preview는 외부 AI 호출 0.

## Source of Truth / 설계 결정

| 결정 | 내용 |
|------|------|
| 테이블 | `ai` 스키마 전용 (Provider Vault와 분리) |
| Renderer | Jinja2 미도입 — `{{ var }}` 전용 Safe Renderer (표현식/import/파일 접근 금지) |
| Core Safety | **코드 강제** — DB Policy 비활성으로 해제 불가 |
| Seed Prompt | **DRAFT** (자동 ACTIVE/호출 없음) |
| Seed Policy/Schema | Core Policy·Schema는 ACTIVE 가능 |

## DB Schema (Migration `v2c3d4e5f6a7`)

- `ai.output_schema`
- `ai.policy_definition` (+ partial unique: code당 ACTIVE 1)
- `ai.prompt_template`
- `ai.prompt_template_version` (immutable, FK → schema/policy RESTRICT)
- `ai.prompt_change_history`

## Task Types

CHAT, SUMMARIZE, NEWS_ANALYSIS, DISCLOSURE_ANALYSIS, CHART_ANALYSIS, MARKET_ANALYSIS,
STOCK/CRYPTO_CANDIDATE_ANALYSIS, STRATEGY_DRAFT, STRATEGY_REVIEW, RISK_REVIEW, PORTFOLIO_REVIEW

## Prompt Version

- Version 증가만 / ACTIVE 본문 직접 수정 금지
- 새 Version 생성 후 명시적 activate (`confirm=true`)
- Rollback = 기존 Version 재활성화
- checksum / 동일 내용 중복 거부
- Archive: active 사용 중이면 금지

## Rendering / Injection

- 미정의 변수 Fail Closed
- 외부 Context delimiter (`<<<EXTERNAL_DATA>>>`)
- Core pattern: ignore previous / system reveal / LIVE/ARM / order / credential / shell / SQL

## Output Validation Pipeline

존재 → 크기 → JSON parse → schema version → JSON Schema → task type → Core Safety →
Policy → Secret/PII → confidence → Safe Result

상태: VALID / VALID_WITH_WARNINGS / BLOCKED / INVALID

## Strategy Draft Schema

초안 필드만. `execute`/`submit_order`/`live`/`arm`/`api_key` 등 금지.
Schema 통과 ≠ 저장·승인·배포.

## Admin API

Prefix: `/api/v1/admin/ai/`

- `prompt-templates`, `prompt-versions` (+ activate/archive)
- `output-schemas` (+ validate)
- `policies` (+ activate)
- `prompt-preview/*` (render / validate-input / parse-response / validate-response)

모두 `require_admin`, reason, rate limit, Audit. Preview **외부 호출 0**.

## Frontend

`/admin/ai/prompts` · `/admin/ai/schemas` · `/admin/ai/policies`

## Dashboard / Telegram

- `ai_prompt_meta` 집계만
- `/ai_prompts`, `/ai_policies`, `/ai_schemas` 조회만 (본문·수정·Preview 금지)

## Rollback

1. Prompt/Policy 비활성(또는 DRAFT)
2. `alembic downgrade -1` (`v2c3d4e5f6a7` → `u1b2c3d4e5f6`)

## 향후 STEP 11-5

Preview 파이프라인을 AIManager Mock/실호출과 연결하되, 결과는 여전히 주문/Runtime과 분리.

## 테스트

```bash
pytest tests/test_step11_4_ai_prompt_policy_schema.py -q
alembic upgrade head && alembic downgrade -1 && alembic upgrade head
```
