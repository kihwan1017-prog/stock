# STEP 8-12A-2 — UBA 58 Recovery Conflict 정리 (CANCEL Ignore + DONE 대사)

Decimal JSON 직렬화 수정, #3/#4·CANCEL 22건 Ignore, DONE 20건 조회 전용 대사.

## 범위

승인: Decimal 수정, #3/#4 Refresh→Ignore, CANCEL allowlist 22 Ignore, DONE 분류만.

미승인: DONE Ignore/Import, Pause Resume, LIVE/ARM, 실주문, Trading Resume, 일괄 Ignore, DB UPDATE.

## 결과 요약

| 항목 | 값 |
|------|-----|
| 변경 전 unresolved | 44 |
| 변경 후 unresolved | 20 (DONE #5–#24만) |
| Ignore | #3,#4 + CANCEL 22 = 24건 |
| DONE 상태 변경 | 0 |
| Account Pause | ON 유지 (`manual_review_required`) |
| Decimal 오류 재발 | 없음 (run 1022 `deposit_amount` str 저장) |

상세 JSON: `E:\StockTrading\reports\step8_12a2_cleanup.json`

## Decimal Root Cause

`UpbitRecoveryAdapter`가 `result.detail["account_sync"]["deposit_amount"]`에 `Decimal`을 넣고, `AdapterRecoveryResult.to_dict()` → JSONB(`result_payload`/`detail_payload`) 저장 시 `json.dumps`가 실패.

## 수정

- `stock_platform.common.json_safe.to_jsonable` — Decimal→`format(d,"f")` (float 금지)
- `AdapterRecoveryResult.to_dict`, `sanitize_upbit_order_snapshot`, Audit, recovery_repository 적용

## DONE 20 권고

전건 `BROKER_FILL_MISSING_INTERNAL_ORDER` → `IMPORT_AS_HISTORICAL_ORDER_REQUIRES_APPROVAL` (이번 STEP에서 Import 금지).

## 다음

STEP 8-12A-3에서 DONE Import/보정 설계·승인 후에만 Pause 해제 검토. 본 STEP에서 Pause Resume·LIVE·ARM·실주문 금지.
