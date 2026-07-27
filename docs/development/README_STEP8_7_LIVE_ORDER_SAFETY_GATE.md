# STEP 8-7 — LIVE 주문 안전 게이트

## 목적

실수로 실주문이 나가거나 대량 주문이 발생하지 않도록, Broker Adapter 호출 전 계좌별 LIVE 승인·한도·중복·시장시간·Health를 Fail Closed로 검사한다.

## 핵심 규칙

- `UserBrokerAccount.live_order_enabled` 기본값 **OFF** (기존 계좌 포함)
- 관리자만 LIVE ON/OFF 가능
- LIVE OFF면 실주문 절대 불가
- PAPER / 리허설 Mock 경로는 기존대로 유지
- 실계좌 주문은 이 STEP에서 발생시키지 않음 (Mock 검증만)

## Pipeline 순서

User → Account → LIVE 승인 → Risk flags → Kill Switch → Amount → Qty → Daily count → Daily loss → Duplicate window → Market time(KRX) → Broker Health → Env live flags → Broker Adapter

## DB (Alembic `k8b9c0d1e2f3`)

- `trading.user_broker_account.live_order_enabled` (bool, default false)
- `live_approved_at`, `live_approved_by`
- risk settings: `max_order_quantity`, `daily_order_limit`, `duplicate_order_window_seconds`

## API

| Method | Path | 역할 |
|--------|------|------|
| GET | `/api/v1/admin/live-order/accounts/{uba_id}` | 상태 |
| PUT | `/api/v1/admin/live-order/accounts/{uba_id}` | LIVE ON/OFF |
| PUT | `/api/v1/admin/live-order/accounts/{uba_id}/risk-limits` | 한도 |
| GET | `/api/v1/admin/live-order/users/{user_id}/accounts` | 목록 |
| GET | `/api/v1/user/live-order/accounts` | 사용자 읽기 전용 |
| GET | `/api/v1/user/live-order/accounts/{uba_id}` | 단건 읽기 |

## Audit 이벤트

`LIVE_APPROVED`, `LIVE_DISABLED`, `LIVE_REJECTED`, `ORDER_AMOUNT_REJECT`, `ORDER_QTY_REJECT`, `DAILY_LIMIT_REJECT`, `LOSS_LIMIT_REJECT`, `DUPLICATE_ORDER_REJECT`, `MARKET_TIME_REJECT`, `BROKER_HEALTH_REJECT`, `LIVE_ORDER_SUBMITTED`

## Frontend

- Admin `/admin/risk` — LIVE 승인 Switch + 한도
- User `/user/risk` — LIVE 상태 읽기 전용

## 관련 코드

- `src/stock_platform/order/live_safety_pipeline.py`
- `src/stock_platform/order/live_safety_audit.py`
- `src/stock_platform/trading/live_order_approval_service.py`
- `src/stock_platform/api/v1/live_order_safety.py`
- `tests/test_step8_7_live_order_safety.py`
