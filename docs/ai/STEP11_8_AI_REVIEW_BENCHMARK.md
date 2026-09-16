# STEP 11-8 — AI Review / Benchmark / Scorecard

## 원칙

**AI 분석 품질 승인 ≠ 매매 승인.**

Review 상태가 `APPROVED`여도 Trading Signal·후보·전략·Risk Guard·주문·Runtime·Scheduler에 연결되지 않는다.
Scorecard로 Provider/Prompt/Schema/Policy를 자동 변경하지 않는다.
Benchmark 기본 모드는 **Mock**. 외부 Benchmark는 관리자 `confirm=true`만 허용한다.

## Architecture

```
Validated AI Analysis Result
  → Review Eligibility
  → Human Review Assignment
  → Reviewer Evaluation (rubric 0–5)
  → Quality Metric / Findings
  → Approval Decision (품질 전용)
  → Scorecard Update
  → Benchmark / Dataset Feedback (선택)
```

연결 금지: Review ✕ Trading Signal / Candidate / Strategy / Risk / Order / Runtime / Scheduler

## Review 대상

| Task | Source Type |
|------|-------------|
| NEWS_ANALYSIS | NEWS |
| DISCLOSURE_ANALYSIS | DISCLOSURE |
| CHART_ANALYSIS | CHART |
| MARKET_ANALYSIS | MARKET |
| SUMMARIZE (선택) | EXECUTION |

조건: Safe Result 존재, Validation이 VALID/VALID_WITH_WARNINGS (SUPERSEDED는 표시만), Raw Response가 아닌 Safe Result 기준.
BLOCKED/INVALID는 Failure Review 경로. 분석 상태와 Review 상태는 분리된다.

## Assignment / Review / Decision

**Assignment:** UNASSIGNED → ASSIGNED → IN_REVIEW → COMPLETED | CANCELLED | EXPIRED

**Review:** DRAFT → SUBMITTED | AMENDED | WITHDRAWN (SUBMITTED 직접 덮어쓰기 금지, amend는 새 version)

**Decision:** PENDING | APPROVED | APPROVED_WITH_WARNINGS | REVISION_REQUESTED | REJECTED | NOT_REVIEWABLE

UI 라벨: **「AI 분석 품질 승인」**

## Reviewer RBAC

권한 시드: `AI_REVIEW_VIEW`, `AI_REVIEW_ASSIGN`, `AI_REVIEW_SUBMIT`, `AI_REVIEW_DECIDE`, `AI_DATASET_MANAGE`, `AI_BENCHMARK_RUN`, `AI_BENCHMARK_VIEW`  
Admin API는 `require_admin` + DB RBAC. JWT claim만 신뢰하지 않는다.

## Rubric (0–5)

Correctness / Relevance / Completeness / Citation / Safety / Clarity (+ Calibration, Data Quality optional).  
`overall_score`는 서버 가중 계산. 클라이언트 overall 입력 미신뢰.

Critical Safety Finding / SAFETY_VIOLATION / HALLUCINATION → APPROVED 금지 (Manager Override 포함).

## Multi Reviewer / Disagreement

- 동일 Reviewer 중복 Assignment 금지
- CONSENSUS / MINOR_DISAGREEMENT / MAJOR_DISAGREEMENT / MANAGER_REVIEW_REQUIRED
- Major Disagreement → 자동 APPROVED 금지

## Evaluation Dataset

- Reference/hash 우선, 민감 원문 복사 금지
- DRAFT → VALIDATED → ACTIVE → ARCHIVED
- ACTIVE 직접 수정 금지 → 새 Dataset Version
- APPROVED 결과 자동 Dataset 추가 **없음** (관리자 명시 선택)

Expected Result: exact/enum/numeric tolerance/required fact/forbidden claim/citation/safety — 문장 일치도 미사용.

## Benchmark

Execution 재사용. 모드: MOCK | EXTERNAL.

| Mode | Max Items |
|------|-----------|
| MOCK | 500 |
| EXTERNAL | 20 |

외부 조건: 권한, confirm, Provider enabled, Credential VERIFIED, Prompt/Schema/Policy ACTIVE, Dataset ACTIVE, Classification 허용, Budget.
Multi-provider fanout 금지. Scheduler 자동 등록 금지. DRY_RUN은 외부 호출 0.

## Metric / Calibration / Scorecard

Valid Response / Schema Pass / Policy Block / Safety Pass / Correctness / Citation / Latency·p95 / Tokens / Cost / Failure Rate.  
Calibration: confidence bucket vs human score, 표본 부족 시 `INSUFFICIENT_SAMPLE`.  
Scorecard 비교는 **동일 Dataset**만. 서로 다른 Dataset 직접 순위 금지. Provider Default 자동 변경 0.

## Admin API

- `/api/v1/admin/ai/review-assignments`
- `/api/v1/admin/ai/reviews`
- `/api/v1/admin/ai/review-decisions/{source_type}/{source_id}`
- `/api/v1/admin/ai/evaluation-datasets`
- `/api/v1/admin/ai/benchmarks`
- `/api/v1/admin/ai/scorecards`

Raw Prompt/Response 반환 금지. reason·idempotency·optimistic lock·Audit.

## Frontend

Admin → AI → Human Review / Evaluation Dataset / Benchmark·Scorecard.  
문서·시장 분석 상세에 「AI 분석 품질 승인」 상태 표시. 매수/매도/주문/후보/전략 버튼 없음.

## Dashboard / Telegram

Dashboard: `ai_reviews`, `ai_benchmarks` 블록 (외부 호출 0).  
Telegram 조회만: `/ai_reviews`, `/ai_benchmarks` — 제출·승인·반려·실행 금지.

## Migration

- ID: **`z6a7b8c9d0e1`**
- Revises: `y5f6a7b8c9d0`
- Tables: `ai.analysis_review_assignment`, `analysis_review`, `analysis_review_finding`, `analysis_review_decision`, `evaluation_dataset`, `evaluation_dataset_item`, `benchmark_run`, `benchmark_result`

## Rollback

```bash
alembic downgrade -1   # z6a7b8c9d0e1 → y5f6a7b8c9d0
```

## 외부 AI 없이 테스트

```bash
pytest tests/test_step11_8_ai_review_benchmark.py -q
```

기본 스위트는 Mock만. 외부 Benchmark는 `live_ai` marker로 분리(본 STEP 기본 테스트 미포함).

## 외부 Benchmark 절차

1. Dataset ACTIVE + Classification 확인  
2. DRY_RUN → 예상 item/token/비용  
3. `confirm=true` + reason  
4. Item ≤ 20, Provider/Model/Prompt 단일  
5. Scorecard 확인 (자동 Default 변경 없음)

## STEP 11-9 연결 원칙

본 STEP 완료 전 STEP 11-9 미진행.  
품질 Review 결과를 후보 자동 선정·전략 생성에 직접 연결하지 않는다. 11-9는 별도 설계·안전 게이트가 필요하다.

## Package

`src/stock_platform/ai/review/` — service, dataset_service, benchmark_service, scorecard_service, decision, rubric, entities, constants
