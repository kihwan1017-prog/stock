# STEP 11-10 — Multi-AI Candidate Consensus

## 원칙

**Multi-AI Consensus는 여러 AI 후보 평가를 비교한 참고용 품질 합의 초안**이며 실제 후보 등록·매수/매도 신호·주문 지시가 아니다.

- STEP 11-9 `candidate_assessment` 결과만 멤버로 사용 (2–5개)
- `REVIEW_APPROVED` = **AI Consensus 품질 승인** (후보 등록·매매 승인 아님)
- create ≠ calculate ≠ synthesize (3단계 분리)
- Scheduler 자동 합의 **0**, Assessment 완료 후 자동 합의 **0**

## Architecture

```
Admin Consensus Request (assessment_ids[])
  → Eligibility (동일 instrument, VALIDATED/REVIEW_APPROVED 등)
  → Independence classify (INDEPENDENT / DUPLICATE / SAME_PROVIDER_FAMILY)
  → Weight compute (review, quality, diversity 보정)
  → [optional] Meta-Synthesis via AIExecutionService (EXTERNAL + confirm)
  → Deterministic calculate (scores, agreement, conflicts)
  → ai.candidate_consensus DRAFT → CALCULATED → VALIDATED
  → Optional Human Review (source_type=CANDIDATE_CONSENSUS)
```

연결 금지: Existing Candidate · Strategy · Risk · Order · Broker · Runtime · Scheduler

## Deterministic vs Meta-Synthesis

| 단계 | 설명 | 외부 AI |
|------|------|---------|
| **Calculate** | 가중 평균·합의 수준·충돌 탐지 (서버 결정론) | **0** |
| **Synthesize** | Meta-Synthesis 프롬프트로 narrative 요약 (선택) | MOCK/DRY_RUN/EXTERNAL |

- `DETERMINISTIC_ONLY`: calculate만, synthesize 없음
- `DETERMINISTIC_PLUS_SYNTHESIS`: calculate 후 synthesize 가능
- EXTERNAL synthesize는 Admin UI `confirm=true` 및 Audit 필수

## Independence

- Provider family map으로 동일 계열 탐지 (`openai` / `openai_compatible` 등)
- DUPLICATE: 동일 provider+model → 멤버 제외 또는 경고
- `minimum_provider_families` 미달 시 `PROVIDER_DIVERSITY` 거부
- Provider diversity: HIGH / MODERATE / LOW / LIMITED

## Weights

`WEIGHT_VERSION = weight-1.0.0`

```
final_weight = base(1.0)
  × review × scorecard × calibration × citation
  × data_quality × independence × conflict_penalty
```

- 각 factor 0..1.5 clamp, final ≥ 0
- 합계 0이면 equal fallback (`ZERO_WEIGHT_FALLBACK_EQUAL`)
- Review APPROVED 가산, 미검토·REJECTED 감산/제외
- Data quality, conflict status, independence status 반영
- Mock-only 멤버 다수 시 confidence 상한 (`MAX_CONF_MOCK_ONLY = 0.60`)
- Meta-Synthesis는 Deterministic score/weight/member/conflict severity를 변경하지 못함

## Confidence caps

| 조건 | 상한 |
|------|------|
| Provider family 1개 | 0.65 |
| Review 미다수 | 0.70 |
| Major disagreement | 0.55 |
| Critical conflict | 0.50 |
| Mock-only | 0.60 |

금지 이름: `consensus_buy_score`, `ranking_score`, `candidate_approved` 등

## Output Schema

- `STOCK_CANDIDATE_CONSENSUS_RESULT_V1`
- `CRYPTO_CANDIDATE_CONSENSUS_RESULT_V1`

금지 필드: buy/sell/hold/recommendation/order/target_price/position_size/candidate_approved/strategy_id/live/arm 등

## API

`/api/v1/admin/ai/candidate-consensuses`

| Method | Path | 설명 |
|--------|------|------|
| GET | `/` | 목록 |
| GET | `/dashboard` | 집계 |
| POST | `/` | create (미계산) |
| POST | `/batches` | 배치 create |
| POST | `/compare` | 두 합의 비교 |
| GET | `/{id}` | 상세 |
| GET | `/{id}/members` | 멤버 |
| GET | `/{id}/weights` | 가중치 미리보기 |
| GET | `/{id}/conflicts` | 충돌 |
| GET | `/{id}/history` | 이력 |
| POST | `/{id}/dry-run` | eligibility+weight preview (외부 0) |
| POST | `/{id}/calculate` | deterministic 계산 (외부 0) |
| POST | `/{id}/synthesize` | meta-synthesis (EXTERNAL + confirm) |
| POST | `/{id}/cancel` | 취소 |
| POST | `/{id}/recalculate` | 새 버전 |
| POST | `/{id}/resynthesize` | 재합성 |
| POST | `/{id}/request-review` | Human Review 요청 |

Batch: Deterministic ≤100, External synthesis ≤10

## Frontend

Admin → AI → **Multi-AI 합의 초안** (`/admin/ai/candidate-consensuses`)

- Alert `title=REFERENCE_DISCLAIMER`
- List / create (assessment_ids) / dry-run / calculate / synthesize(EXTERNAL confirm)
- Detail: agreement, disagreement, scores, members, conflicts
- 매수/매도/주문/후보 등록 버튼 **없음**

## Dashboard / Telegram

- Dashboard: `ai_candidate_consensuses` (`AIConsensusService.dashboard_summary()`, `external_calls_on_read=0`)
- Telegram: `/ai_consensus` 조회만 (calculate/synthesize 금지)

## Safety (not trading approval)

- Consensus VALIDATED ≠ 매매 허가
- Human Review APPROVED = 품질 승인만
- Telegram·Scheduler에서 합의 실행 불가
- Audit: `AI_CONSENSUS_CREATED`, `AI_CONSENSUS_CALCULATED`, `AI_CONSENSUS_SYNTHESIS_COMPLETED` 등

## Migration

- ID: **`ab2c3d4e5f6a`** (revises `aa1b2c3d4e5f`)
- Tables: `candidate_consensus`, `_member`, `_factor`, `_conflict`, `_history`
- Review CHECK에 `CANDIDATE_CONSENSUS` 추가

Rollback: `alembic downgrade -1`

## Package

`src/stock_platform/ai/candidate_consensus/`

## STEP 11-11

본 STEP 완료 전 미진행. Consensus 결과를 전략·Risk·Candidate Run에 자동 연결하지 않는다.
