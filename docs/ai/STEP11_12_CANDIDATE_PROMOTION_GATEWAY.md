# STEP 11-12 — Candidate Promotion Gateway

## 원칙

**Candidate Promotion은 검토된 AI 결과를 기존 후보 엔진에 수동 등록하는 관리 작업**이며 매수·매도·전략·주문 승인이 아니다.

- Queue `APPROVED_FOR_CONSIDERATION` / `APPROVED_WITH_WARNINGS` ≠ Candidate 등록
- Create / Validate / Dry-run / Approve → **Candidate INSERT 0**
- **Commit(confirm=true)** 완료 시에만 `strategy.candidate_run` + `candidate_result` 생성
- 이중 승인: Requester ≠ First Approver ≠ Final Approver
- Critical Finding → Override 불가
- AI Score/Confidence를 Candidate Score로 직접 복사하지 않음 (`promotion-score-1.0.0`)

## Architecture

```
APPROVED Queue
  → Promotion Request (DRAFT)
  → Validate
  → Dry-run (preview only)
  → First Approval → Final Approval
  → Commit Confirm
  → AI_REVIEW_PROMOTION CandidateRun + Result (원자적)
  → Promotion Link
```

연결 금지: Trading Signal · Strategy · Risk · Order · Broker · LIVE · ARM · Runtime · Scheduler

## Side Effect Guard

- `CandidateRunRepository.get_latest_run(..., run_type="DAILY")` 기본값
- Ops dashboard 오늘 후보 조회도 `run_type=DAILY`만
- `POST /api/v1/candidate-runs` 에서 `AI_REVIEW_PROMOTION` 우회 생성 차단
- Promotion Candidate `score_breakdown`: trading/strategy/order_eligibility = **false**

## Candidate Run Unique

DAILY partial unique index만 유지 → 동일 거래일 다수 `AI_REVIEW_PROMOTION` Run 허용.

## Score Formula (`promotion-score-1.0.0`)

서버 계산. AI confidence 단독 고점수 금지. Critical Risk는 Score로 희석하지 않음.

## API

`/api/v1/admin/ai/candidate-promotions`

Create·Validate·Dry-run·Approve는 Candidate 생성 0. Commit만 생성.

Batch: 명시적 queue_ids, 최대 20, confirm 필수. 일괄 Commit 금지.

## Frontend

Admin → AI → **Candidate Promotion Gateway** (`/admin/ai/candidate-promotions`)

Queue 상세: 「Candidate Promotion 요청」링크 (즉시 등록 아님)

## Dashboard / Telegram

- Dashboard: `ai_candidate_promotions` (`external_calls_on_read=0`)
- Telegram: `/ai_candidate_promotions` 조회만

## Migration

- ID: **`ad4e5f6a7b8c`** (revises `ac3d4e5f6a7b`)
- Tables: `candidate_promotion_request/validation/dry_run/approval/link/history`
- RBAC: `AI_CANDIDATE_PROMOTION_*` 12개

Rollback: `alembic downgrade -1`

## Package

`src/stock_platform/ai/candidate_promotion/`

## STEP 11-13

본 STEP 완료 전 미진행. Promotion Candidate를 Strategy/Trading에 자동 연결하지 않는다.
