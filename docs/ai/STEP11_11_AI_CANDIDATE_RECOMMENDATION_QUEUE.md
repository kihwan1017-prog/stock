# STEP 11-11 — AI Candidate Recommendation Queue

## 원칙

**AI 후보 추천 검토 큐는 기존 Candidate 등록 여부를 검토하기 위한 내부 업무 큐**이며, 실제 매수·매도 추천이나 주문 승인이 아니다.

- `APPROVED_FOR_CONSIDERATION` = **기존 후보 등록 검토 가능** (strategy.candidate INSERT 아님)
- create → `DRAFT` only; `queue()` / `decide()` 는 별도 전환
- Self-approval blocked (`creator == decider` unless `manager_override`)
- Critical findings → **override 불가** 승인 차단
- AI Execution task 추가 **0**, 외부 AI 호출 **0**
- Scheduler 자동 큐 등록 **0**

## Architecture

```
Admin Queue Request (Assessment or Consensus source)
  → Eligibility validate (status, review, existing candidate conflict)
  → create DRAFT (idempotency + queue_key dedup)
  → queue() → QUEUED (staleness + expiry re-check)
  → assign / start_review → UNDER_REVIEW
  → submit_review (server rubric overall_score)
  → decide → APPROVED_FOR_CONSIDERATION | REJECTED | ...
  → [STEP 11-12] Promotion Gateway (별도 — candidate INSERT는 11-12)
```

연결 금지: strategy.candidate INSERT · Order · Broker · Runtime · Scheduler · AI Execution

## Source Types

| source_type | 설명 |
|-------------|------|
| `CANDIDATE_ASSESSMENT` | STEP 11-9 평가 초안 |
| `CANDIDATE_CONSENSUS` | STEP 11-10 Multi-AI 합의 초안 |

## Queue Status Flow

```
DRAFT → QUEUED → ASSIGNED → UNDER_REVIEW
  → APPROVED_FOR_CONSIDERATION | APPROVED_WITH_WARNINGS | REJECTED
  → ON_HOLD | MORE_INFORMATION_REQUIRED | EXPIRED | WITHDRAWN
```

Terminal: `APPROVED_FOR_CONSIDERATION`, `APPROVED_WITH_WARNINGS`, `REJECTED`, `WITHDRAWN`, `EXPIRED`, `SUPERSEDED`, `NOT_ELIGIBLE`, `ARCHIVED`

## Review Rubric

서버 `compute_overall_score()` — 클라이언트 overall 미신뢰.

| 축 | 가중치 |
|----|--------|
| eligibility_score | 0.20 |
| analytical_quality_score | 0.15 |
| evidence_quality_score | 0.15 |
| risk_awareness_score | 0.20 |
| consistency_score | 0.10 |
| safety_score | 0.20 |

`MIN_OVERALL_FOR_CONSIDERATION = 3.0`, `MIN_SAFETY_FOR_CONSIDERATION = 3.0` (promotion eligibility snapshot)

## Safety Rules

### Self-approval

- Queue 생성자(`created_by`)가 `decide()` 호출 시 `SELF_APPROVAL_BLOCKED`
- `manager_override=true` + `override_reason` 필요

### Critical override ban

- `severity=CRITICAL` finding 존재 시 `APPROVED_*` 결정 **항상 거부** (override 무효)

### Staleness

- `queue()` / `decide()` 직전 source hash 재검증
- stale 시 `SOURCE_STALE` / `SOURCE_CHANGED`

### No candidate insert

- 이 STEP은 큐·검토·결정만 수행
- `strategy.candidate` INSERT는 **STEP 11-12 Promotion Gateway**에서 별도 게이트

## API

Prefix: `/api/v1/admin/ai/candidate-recommendation-queues`

- CRUD-ish: list, get, create, validate
- Workflow: queue, assign, reassign, start-review, submit/amend/withdraw-review, decide, hold, resume, request-more-information, withdraw, expire, revalidate, requeue
- Sub-resources: reviews, findings, decisions, history, source, promotion-eligibility, compare
- Batch: `POST /batches` (max 100)
- Dashboard: `GET /dashboard`

## Integration

- **Dashboard**: `ai_candidate_recommendation_queues` (`AIRecommendationQueueService.dashboard_summary()`, `external_calls_on_read=0`)
- **Telegram**: `/ai_candidate_queue` READ_ONLY (create/decide 금지)
- **Frontend**: `/admin/ai/candidate-recommendation-queues` — Assessment/Consensus 페이지에서 "검토 큐 등록" 링크

## STEP 11-12 Note

`APPROVED_FOR_CONSIDERATION` 큐 항목은 STEP 11-12 **Candidate Promotion Gateway**의 입력 후보가 될 수 있다. Gateway는 별도 eligibility·audit·manual confirm을 요구하며, 이 STEP에서 후보가 자동 등록되지 않는다.

## Migration

- Head: `ac3d4e5f6a7b_ai_candidate_recommendation_queue`

## Related

- [STEP11_9_AI_CANDIDATE_ASSESSMENT.md](STEP11_9_AI_CANDIDATE_ASSESSMENT.md)
- [STEP11_10_MULTI_AI_CANDIDATE_CONSENSUS.md](STEP11_10_MULTI_AI_CANDIDATE_CONSENSUS.md)
