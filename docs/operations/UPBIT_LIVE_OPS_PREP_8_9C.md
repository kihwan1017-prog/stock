# STEP 8-9C — Upbit LIVE Dry-run 준비

실주문·ARM·LIVE ON 없이 운영 준비만 한다.

## Admin 기능

| 기능 | 경로 |
|------|------|
| UPBIT UBA CRUD | Admin → 계좌관리 → UPBIT LIVE UBA 패널 |
| Credential 등록/교체/검증/폐기 | 동일 패널 + Credential 상태 카드 |
| 권장 Risk 5000/1/1 | UBA 생성 시 자동 또는 `Risk 5000` 버튼 |
| Scheduler 준비 상태 | `GET /api/v1/admin/live-ops/readiness` |

## API

- `GET/POST /api/v1/admin/broker-accounts`
- `GET/PATCH/DELETE /api/v1/admin/broker-accounts/{uba_id}`
- `POST /api/v1/admin/broker-accounts/{uba_id}/apply-recommended-risk`
- `POST/PUT /api/v1/admin/accounts/{uba_id}/credentials`
- `GET /api/v1/admin/live-ops/readiness`
- 거래 Scheduler Pause: `POST /api/v1/realtime-sessions/stop-scheduler`

## 권장 Risk (계좌 오버레이)

- `max_order_amount=5000`
- `max_open_orders=1`
- `daily_order_limit=1`

시스템 전역 기본값(100000 등)은 유지하고 UPBIT UBA에만 오버레이한다.

## Dry-run 준비 조건

1. UPBIT UBA 존재
2. Vault Credential 등록 + Verify
3. `UPBIT_USE_MOCK=false` (조회 API용)
4. 거래 Scheduler PAUSE
5. Tracking / Post-fill ENABLED
6. Kill Switch OFF
7. LIVE OFF / ARM OFF 유지

실주문(`--execute-live`)은 별도 승인 STEP에서만.
