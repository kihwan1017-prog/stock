# STEP 11-9 — AI Candidate Assessment Draft

## 원칙

**AI 후보 평가는 참고용 초안**이며 실제 매매 후보·매수/매도 신호·주문 지시가 아니다.

- 기존 `strategy.candidate_*` / 레거시 `ai.candidate_analysis_*`와 **완전 분리**
- `REVIEW_APPROVED` = **AI 후보 평가 품질 승인** (후보 등록·매매 승인 아님)
- 기본 Provider = Mock, 외부는 `confirm=true`만
- Scheduler 자동 평가 **0**, 수집 후 자동 평가 **0**

## 기존 Candidate 구조 (요약)

| 축 | 저장소 | 11-9 관계 |
|----|--------|-----------|
| 규칙 스크리닝 | `strategy.candidate_run/result` | 읽기·쓰기 금지 |
| 레거시 Ollama 랭킹 | `ai.candidate_analysis_*` → position_plan | 병행 유지, 미연결 |
| 사용자 추천 | `ai.recommendation_*` | 미연결 |

## Architecture

```
Admin Assessment Request
  → Eligibility (STOCK/KRX, CRYPTO/UPBIT)
  → Evidence Bundle (News/Disclosure/Chart/Market Safe Result + Review)
  → AIExecutionService.create (≠ execute)
  → DRY_RUN / MOCK / EXTERNAL
  → Schema/Policy/Forbidden-field strip
  → ai.candidate_assessment DRAFT/VALIDATED
  → Optional Human Review (source_type=CANDIDATE_ASSESSMENT)
```

연결 금지: Existing Candidate · Score · Strategy · Risk · Order · Broker · Runtime · Scheduler

## Evidence

- VALIDATED_*만, SUPERSEDED 제외
- Review REJECTED / REVISION_REQUESTED 제외
- Temporal: ALIGNED / ACCEPTABLE / STALE / CONFLICTED / UNKNOWN
- Conflict: NO / MINOR / MAJOR / INSUFFICIENT_EVIDENCE
- Raw 본문·전체 Candle 미전송

## Scores

- `analytical_score`, `risk_score` (0–100, 서버 계산)
- Confidence 캡: no-review / metadata-only / major conflict / stale
- 금지 이름: candidate_score, buy_score, ranking_score

## Output Schema

- `STOCK_CANDIDATE_ASSESSMENT_RESULT_V1`
- `CRYPTO_CANDIDATE_ASSESSMENT_RESULT_V1`

금지 필드: buy/sell/hold_signal/order/target_price/position_size/candidate_approved/strategy_id/live/arm 등

## API

`/api/v1/admin/ai/candidate-assessments` — create/dry-run/execute/cancel/reassess/request-review/batches/compare/dashboard

Batch: Mock ≤100, External ≤10, 명시 instrument 목록만

## Frontend

Admin → AI → **후보 평가 초안** (`/admin/ai/candidate-assessments`)  
매수/매도/주문/후보 등록 버튼 없음

## Dashboard / Telegram

- Dashboard: `ai_candidate_assessments` (외부 호출 0)
- Telegram: `/ai_candidate_assessments` 조회만

## Migration

- ID: **`aa1b2c3d4e5f`** (revises `z6a7b8c9d0e1`)
- Tables: `candidate_assessment`, `_evidence`, `_factor`, `_risk`, `_history`
- Review CHECK에 `CANDIDATE_ASSESSMENT` 추가

Rollback: `alembic downgrade -1`

## Package

`src/stock_platform/ai/candidate_assessment/`

## STEP 11-10

본 STEP 완료 전 미진행. Assessment 결과를 전략 초안·Risk에 자동 연결하지 않는다.
