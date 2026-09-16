# STEP 11-13 — AI Candidate Lifecycle & Provenance

## 원칙

**Candidate Lifecycle은 Promotion Gateway로 등록된 CandidateResult(result_id)에 대한 참조·검증·만료·철회 관리**이며 매수·매도·전략·주문 승인이 아니다.

- `candidate_id` = `strategy.candidate_result.result_id`
- Promotion link(`candidate_promotion_link`)가 있는 후보만 lifecycle row 보유
- **Expire/Revoke = soft status 전이만** — hard delete 없음
- Revalidation = fingerprint compare only (AI 호출 없음)

## Architecture

```
Promotion Commit (11-12)
  → ensure_lifecycle (PROMOTED)
  → provenance snapshot
  → ACTIVE_REVIEW / validate / revalidate
  → expire | archive | supersede | revoke (soft)
```

연결 금지: Trading Signal · Strategy · Risk · Order · Broker · LIVE · ARM · Runtime · Scheduler WRITE

## API

Admin list/dashboard: `/api/v1/admin/ai/candidate-lifecycle`

Candidate-scoped: `/api/v1/admin/ai/candidates/{candidate_id}/...`

User read-only: `/api/v1/user/ai-candidates/{candidate_id}/lifecycle|provenance|history`

Dashboard summary: `/api/v1/admin/dashboard/ai-candidate-lifecycle-summary`

Mutations require `expected_version` + `reason` (optimistic concurrency).

## Frontend

Admin → AI → **Candidate Lifecycle** (`/admin/ai/candidate-lifecycle`)

## Dashboard / Telegram

- Operations dashboard: `ai_candidate_lifecycle` (`external_calls_on_read=0`)
- Telegram: `/ai_candidate_lifecycle` 조회만

## Migration

- ID: **`ae5f6a7b8c9d`** (revises `ad4e5f6a7b8c`)
- Tables: `candidate_lifecycle`, `candidate_provenance_snapshot`, `candidate_revalidation`, `candidate_revocation`, `candidate_supersession`, `candidate_lifecycle_history`
- RBAC: `AI_CANDIDATE_LIFECYCLE_*` 9개

Rollback: `alembic downgrade -1`

## Package

`src/stock_platform/ai/candidate_lifecycle/`

## STEP 12-1

본 STEP 완료 전 미진행. Lifecycle Candidate를 Strategy/Trading에 자동 연결하지 않는다.
