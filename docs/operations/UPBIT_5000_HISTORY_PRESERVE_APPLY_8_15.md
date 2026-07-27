# STEP 8-15 — DONE 20건 HISTORICAL_PRESERVED 적용

## 1. 목적

UBA 58 DONE Conflict `#5–#24`에 `preserve-history`를 적용해 History를 보존한 채 Dashboard 미해결에서 제외한다. Account Pause Resume는 수행하지 않는다(종료 시 Pause ON 유지).

## 2. 승인 대상 ID

`5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24`

## 3. 사전 조건

- allowlist 포함
- `PENDING_REVIEW`
- remote `done`
- Broker/DB Open 아님
- classification `POSITION_RECONCILABLE`
- Position/Balance 영향 없음
- IMPORT_REQUIRED / UNSAFE 아님

## 4. API

```http
POST /api/v1/admin/recovery/conflicts/{id}/preserve-history
Content-Type: application/json
X-Admin-API-Key: <admin>

{"note":"HISTORICAL_REMOTE_DONE_POSITION_RECONCILED_NO_IMPORT_REQUIRED"}
```

스크립트: `scripts/step8_15_preserve_history_apply.py`  
검증: `scripts/step8_15_post_verify.py`

## 5. Ignore와 차이

| | Ignore | History Preserve |
|--|--------|------------------|
| status | IGNORED | HISTORICAL_PRESERVED |
| 의미 | 외부 주문 무시 | 검토 완료·이력 보존 |
| Audit | RECOVERY_CONFLICT_IGNORE | RECOVERY_CONFLICT_HISTORY_PRESERVED |

## 6. Import와 차이

Import는 내부 주문/체결을 생성한다. Preserve는 Conflict·`remote_snapshot`만 유지하며 Import하지 않는다.

## 7. Audit 정책

이벤트 `RECOVERY_CONFLICT_HISTORY_PRESERVED` — actor, conflict_id, broker_uuid_masked, reason, correlation_id, occurred_at, before/after status, resolution. 전체 UUID·Secret 금지.

## 8. Scheduler 재생성 방지

`HISTORICAL_PRESERVED` ∈ `TERMINAL_REVIEW_STATUSES` → 동일 UUID Conflict 재생성 안 함.

## 9. Dashboard

- Review Required = ACTIVE_REVIEW(PENDING/ON_HOLD)만
- Historical Preserved = Review Complete

## 10. Pause 유지 원칙

Preserve 후에도 Pause Resume 금지. Recovery cycle이 SUCCESS면 runtime이 Pause를 풀 수 있으므로 **검증 후 Pause ON을 재확인·필요 시 복구**한다. Resume API는 호출하지 않는다.

## 11. 상태 정정

잘못 Preserve한 경우: 운영 승인 후 ON_HOLD로 되돌리거나 신규 검토(직접 DB UPDATE 금지 권장, Admin 절차 사용).

## 12. 민감정보

Access/Secret Key·전체 Broker UUID·Credential 원문 로그/Audit 금지.

## 13. STEP 8-16 인계

- ACTIVE_REVIEW=0
- DONE 20건 HISTORICAL_PRESERVED
- Pause ON 유지 확인 후, 별도 승인으로 Pause Resume·LIVE 게이트 검토

## Migration 메모

- `r7b8c9d0e1f2` HISTORICAL_PRESERVED CHECK
- `s8c9d0e1f2a3` 중복 구 CHECK 제거
