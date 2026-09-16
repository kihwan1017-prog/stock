# STEP 10-1 — Post-fill / Snapshot / Position / Balance 동기화 안정화

## 문제 원인

STEP 9-6 실주문 후 다음이 발생했다.

1. Outbox는 Broker 접수 후 **ACCEPTED**까지만 반영
2. Upbit `state=cancel` + `executed_volume>0` 을 **CANCELLED**로 오매핑 → 체결 후속 스킵
3. Upbit 경로가 `trading.execution` 저장 / `PostFillVerification` enqueue를 **호출하지 않음** (Kiwoom ExecutionSync만 연결)
4. Snapshot refresh는 Post-fill worker 또는 Admin sync에만 존재 → Post-fill 미생성 시 stale

## 변경 아키텍처

```
Upbit submit (Outbox)
  → ACCEPTED (+ SUBMITTING 승격 수정)
  → UpbitFillSyncService.sync_by_order_id
       → state 정규화 (cancel+fill → FILLED)
       → Execution 멱등 저장
       → PostFillVerifyRunner.verify_after_order_fill
            → enqueue post_fill_verification
            → (scheduler) Broker Snapshot sync
            → Position/Balance 비교
```

동일 FillSync를 Reconcile / Smoke Tracker / Admin API가 공유한다.

## Upbit 상태 정규화

| 원격 | 도메인 |
|------|--------|
| done + executed>0 | FILLED (잔량>0이면 PARTIALLY_FILLED) |
| cancel + executed>0 | **FILLED** (잔여 KRW 취소 포함 체결 완료) |
| cancel + executed=0 | CANCELLED |
| wait/watch + executed>0 | PARTIALLY_FILLED |
| wait/watch + executed=0 | ACCEPTED |

구현: `broker/upbit/order_status.py`

## Execution 멱등성

- Unique: `(broker_code, broker_execution_id)` on `trading.execution`
- trade.uuid 우선, 없으면 `uuid:executed:{volume}` / timestamp 조합
- 중복 = already_processed (오류 아님)
- insert는 savepoint(`begin_nested`)로 race 방어

## Post-fill

기존 `PostFillVerificationService` 상태 재사용:

PENDING → WAITING_SNAPSHOT / VERIFYING → VERIFIED | MISMATCH | FAILED | EXPIRED

재시도: settings `post_fill_verify_retry_delays` (기본 2,5,10,20초), **max_attempts=5**  
**주문 재제출 없음**

Audit (신규 별칭 포함):

- `EXECUTION_RECORDED`, `POST_FILL_STARTED`, `POST_FILL_FAILED`
- `POST_FILL_SUCCEEDED` (+ 기존 `POST_FILL_VERIFIED`)
- `BALANCE_SNAPSHOT_REFRESHED`, `POSITION_SNAPSHOT_REFRESHED`
- `RECONCILIATION_MATCHED` / `RECONCILIATION_MISMATCH` / `RECONCILIATION_FAILED`

## Snapshot 기준

- Source of Truth: Broker `GET /v1/accounts`
- `UpbitAccountMapper`: KRW available/locked, 자산 qty + `avg_buy_price`
- Post-fill worker가 sync 후 Audit: `BALANCE_SNAPSHOT_REFRESHED`, `POSITION_SNAPSHOT_REFRESHED`

## 평균단가

- Broker `avg_buy_price` → snapshot `average_purchase_price`
- Order `average_fill_price` ← trade 가중 (funds/volume)
- Decimal only

## Reconcile

`UpbitOrderReconcileService`가 FillSync를 호출 (SUBMITTING 포함).  
불일치 시 기존 Post-fill MISMATCH → Kill/Disarm 경로 유지.

## 운영 API

| Method | Path | 설명 |
|--------|------|------|
| GET | `/api/v1/admin/live-order/orders/{id}/post-fill` | 상태 조회 |
| POST | `/api/v1/admin/live-order/orders/{id}/fill-sync` | 체결 동기화 (조회만, 주문 제출 없음) |
| POST | `/api/v1/admin/live-order/orders/{id}/post-fill/retry` | Post-fill 재처리 |
| POST | `/api/v1/admin/broker-accounts/{uba}/refresh-snapshot` | Snapshot 수동 refresh (기존) |

## 장애 대응

1. Admin fill-sync 1회
2. Snapshot refresh
3. Post-fill retry
4. 지속 불일치 → MISMATCH Audit + 필요 시 Pause

## Rollback

- FillSync 호출부를 Outbox/Reconcile에서 제거하면 이전 동작(ACCEPTED만)으로 회귀
- 상태 정규화 모듈만 되돌려도 cancel+fill 오매핑이 재발

## 실주문 없이 검증

```bash
.venv\Scripts\python -m pytest tests/test_step10_1_upbit_fill_post_fill_sync.py -q
```

Fixture: KRW-BTC / 0.00005254 / 95,150,000 / 4,999.181 / fee 2.4995905 (STEP 9-6 형태, 실 UUID 미포함)

## STEP 9-6 주문(order_id=250) 백필

코드 경로 적용 후 운영자가 **read-only**로 실행:

```text
POST /api/v1/admin/live-order/orders/250/fill-sync
```

- `create-order` 호출 없음
- UBA LIVE/ARM OFF 상태에서도 Execution 멱등 + Post-fill enqueue 가능
- Snapshot sync는 worker가 Broker accounts 조회 (실주문 아님)

## STEP 9-6 연결

STEP 9-6 잔여 문제 1–5,7 은 본 STEP에서 코드 경로로 해결.  
항목 6(Scheduler desired 영속화)은 **STEP 10-2** 범위.
