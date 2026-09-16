# STEP 8-5-4 — Upbit Remote-only 주문 수동 검토·승인

## 1. 기존 Remote-only 처리

Recovery 중 업비트 외부 주문 UUID가 내부 `trading_order.broker_order_id`에
없으면 remote-only로 분류한다. 이전에는 카운트·경고만 남기고 Conflict 테이블이
없었으며, 자동 내부 주문 생성은 금지(`allow_auto_create_external_orders=false`)였다.

## 2. 자동 Import를 금지한 이유

외부에만 있는 주문을 자동으로 내부 DB에 넣으면 소유권·수량·계좌 오판 시
정합성이 깨진다. ADMIN이 외부 상태를 확인한 뒤 명시적으로 내부 기록만
가져오도록 한다. **Upbit 신규 주문 API는 호출하지 않는다.**

## 3. Conflict 모델

테이블: `operation.broker_recovery_conflict`

주요 컬럼: run/user/uba, `conflict_type`, `external_order_id`(마스킹 별도),
수량·가격·상태 스냅샷(`remote_snapshot`은 허용 필드만), `review_status`,
`resolution_*`, `linked_internal_order_id`, `pause_reason`.

## 4. Conflict 상태

- 유형: `REMOTE_ORDER_NOT_FOUND_LOCALLY` (+ 확장용 mismatch 유형 상수)
- 검토: `PENDING_REVIEW`, `ON_HOLD`, `APPROVED_IMPORT`, `IGNORED`,
  `REJECTED`, `RESOLVED`, `REMOTE_DISAPPEARED`
- 해결: `IMPORT_INTERNAL_ORDER`, `IGNORE_EXTERNAL_ORDER`, `KEEP_PAUSED`,
  `REMOTE_ORDER_CANCELLED`, `DUPLICATE_INTERNAL_ORDER_FOUND`

상수: `stock_platform.broker.recovery_conflict_constants`

## 5. 중복 탐지 방지

- Partial Unique: `(broker_code, COALESCE(uba_id,0), external_order_id)`
  WHERE `PENDING_REVIEW|ON_HOLD`
- 활성 Conflict면 스냅샷·수량만 갱신
- `APPROVED_IMPORT` / `IGNORED` 등 terminal은 재생성하지 않음
- 내부 동일 UUID 있으면 Conflict 미생성

## 6. 계좌 거래 차단

활성 Conflict 존재 시 해당 UBA만
`broker_recovery_account_state.trading_paused=true`,
`recovery_status=MANUAL_REVIEW`,
사유 `UPBIT_REMOTE_ONLY_ORDER_REVIEW`.
단순 조회·Ignore 단건으로 Pause를 자동 해제하지 않는다.

## 7. 관리자 목록·상세 API

- `GET /api/v1/admin/recovery/conflicts`
- `GET /api/v1/admin/recovery/conflicts/{id}`

필터: broker, user, uba, type, review_status, market, resolved.
응답은 마스킹 UUID·계좌만. Secret 없음.

## 8. 최신 외부 상태 조회

`POST .../conflicts/{id}/refresh`

UBA Vault Credential로 `get_order`만 호출. 내부 주문 자동 생성 없음.
미존재 시 `REMOTE_DISAPPEARED`.

## 9. 내부 주문 Import

`POST .../conflicts/{id}/approve-import`

Body는 `note`만 신뢰. 수량·UUID 등은 Conflict+원격 조회 기준.
`TradingOrderService.create`로 DB만 생성 후 `broker_order_id` 연결.
`metadata_payload.order_origin=RECOVERY_IMPORT`, `broker_submit=false`.
Risk 신규 승인 경로를 타지 않음. **`create_order` 미호출.**

## 10. 체결 Import

원격 `trades`의 uuid(또는 합성 키)를 `trading.execution.broker_execution_id`에
저장. `(broker_code, broker_execution_id)` Unique로 중복 방지.

## 11. Ignore

`POST .../ignore` — 사유 필수. Pause 자동 해제 없음.

## 12. Hold

`POST .../hold` — 사유 필수. Pause 유지.

## 13. 거래 재개 조건

`POST /api/v1/admin/recovery/accounts/{uba_id}/resume`

- 활성 Conflict 0
- Credential `assert_live_order_allowed`
- Kill Switch 비활성
- 계좌 활성
- Recovery RUNNING 아님

## 14. USER 표시 정책

`GET /api/v1/user/accounts`에 `trading_paused`, `recovery_review_required`,
`recovery_user_message`만 노출. Conflict 승인 UI·전체 UUID 없음.

## 15. Frontend

`/admin/recovery` — `RecoveryConflictPanel`
버튼: 최신 조회 / **내부 기록으로 가져오기** / 무시 / 보류 / 계좌 재개.
Confirm: 외부 재주문 없음 명시.

## 16. 권한·보안

`require_admin`, Body 주문 필드 무시, 마스킹, Vault Credential만 사용.

## 17. 감사 로그

`RECOVERY_CONFLICT_REFRESH|APPROVE_IMPORT|IGNORE|HOLD`,
`RECOVERY_ACCOUNT_RESUME(_FAILED)`.

## 18. DB Migration

- Revision: `v9c0d1e2f3a4`
- Revises: `u8b9c0d1e2f3`
- Table: `operation.broker_recovery_conflict`

## 19. 변경 파일

- `database/alembic/versions/v9c0d1e2f3a4_broker_recovery_conflict.py`
- `src/stock_platform/broker/recovery_conflict_*.py`
- `src/stock_platform/broker/upbit/order_reconcile_service.py`
- `src/stock_platform/broker/recovery_adapters/upbit.py`
- `src/stock_platform/api/v1/admin_recovery_conflicts.py`
- `src/stock_platform/api/v1/user_accounts.py`
- `frontend/.../RecoveryConflictPanel.tsx`, `adminApi.ts`, `AccountsView.tsx`
- `tests/test_step8_5_4_recovery_conflict.py`

## 20. 테스트 결과

| 항목 | 결과 |
|------|------|
| Backend `tests/test_step8_5_4_recovery_conflict.py` | 6/6 통과 |
| Frontend Vitest | 78/78 통과 |
| TypeScript (`tsc` / build) | 통과 |
| Lint | 0 errors / 기존 Warning 6건 유지 |
| Production Build | 성공 |
| Migration `v9c0d1e2f3a4` down→up | 성공 (`current=v9c0d1e2f3a4`) |

## 21. 운영 적용 방법

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
```

## 22. 기존 Lint Warning 상태

기존 6건 유지 목표. 신규 Warning 추가 금지.

## 23. 남은 문제

- KRX Calendar `WEEKDAY_FALLBACK`
- Upbit `Retry-After` 정밀 파싱
- 레거시 전역 Runtime 슬롯 제거
- 다중 인스턴스 분산 Lock 강화
- 기존 Lint Warning 6건
