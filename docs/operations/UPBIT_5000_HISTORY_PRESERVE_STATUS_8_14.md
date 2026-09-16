# STEP 8-14 — Recovery Conflict History Preserve 상태 모델

DONE 20건은 Import/Ignore 없이 `HISTORICAL_PRESERVED`로 검토 완료·이력 보존하는 것이 적합하다. 본 STEP은 **상태 모델·API·Dashboard·Scheduler 계약**을 추가한다. DONE 20건에 대한 실제 Preserve 적용은 STEP 8-15에서 운영자 승인 후 수행한다.

## 새 상태

`HISTORICAL_PRESERVED`

| 의미 | 값 |
|------|-----|
| Broker DONE 확인 | 전제 |
| Position/Balance 일치 | 전제 (8-13) |
| Import | 불필요 |
| History | Conflict 행·`remote_snapshot` 보존 |
| Dashboard | Review Complete (미해결 아님) |
| Scheduler upsert | terminal — 동일 UUID 재생성 안 함 |
| Pause | 자동 Resume 없음 |

## 변경 요약

| 영역 | 내용 |
|------|------|
| Enum | `RecoveryConflictReviewStatus.HISTORICAL_PRESERVED`, `PRESERVE_HISTORY` |
| Migration | `r7b8c9d0e1f2` — CHECK `ck_recovery_conflict_review` 확장 (**필요**) |
| API | `POST /api/v1/admin/recovery/conflicts/{id}/preserve-history` |
| Audit | `RECOVERY_CONFLICT_HISTORY_PRESERVED` |
| Dashboard Alert | `PENDING_REVIEW`만 Conflict alert |
| ACTIVE_REVIEW | PENDING/ON_HOLD만 (변경 없음 + PRESERVED는 미포함) |
| UI | History Preserve 버튼·라벨 |

## Backward Compatibility

- 기존 `IGNORED` / `APPROVED_IMPORT` 동작 유지
- `ACTIVE_REVIEW_STATUSES` 집합 불변 (PENDING, ON_HOLD)
- 유니크 인덱스 `WHERE PENDING_REVIEW|ON_HOLD` 변경 없음

## 금지 (본 STEP)

Import / Ignore / Pause Resume / LIVE / ARM / 실주문 / DONE 20건 DB 상태 변경
