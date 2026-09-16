# STEP 8-8 — LIVE 운영 보호 (Production Protection)

## 목적

실계좌에서 실제 손실을 막기 위한 운영 보호. LIVE ON만으로 주문 가능하던 경로를 **2단계 ARM**으로 바꾸고, 슬리피지·미체결 한도·이상주문·브로커 단절·체결 후 잔고 검증을 Fail Closed로 적용한다.

## 핵심 흐름

```
LIVE OFF → ADMIN LIVE ON → ARM (관리자, 기본 5분) → arm_token으로 주문
→ TTL 만료 시 자동 DISARM + LIVE OFF
```

- ARM은 관리자만 가능
- 주문 시 현재 ARM Token 해시 검증 (불일치 Reject)
- Broker 복구 후 **자동 LIVE ON 금지** — 관리자 ARM 재필요

## Pipeline 추가 검사 (STEP 8-7 이후)

1. ARM + Token
2. max_open_orders
3. max_slippage_rate (reference_price 대비)
4. anomaly_orders_per_minute (1분 N건)
5. BUY/SELL flip loop
6. (기존) Market / Health / Env flags

## DB (Alembic `l9c0d1e2f3a4`)

- `trading.user_broker_account`: `live_armed`, `arm_token_hash`, `arm_expires_at`, `arm_armed_by`, `arm_armed_at`
- `trading.live_arm_event`
- Risk: `max_open_orders`, `max_slippage_rate`, `anomaly_orders_per_minute`, `loop_detect_window_seconds`, `arm_ttl_seconds`

## API

| Method | Path | 역할 |
|--------|------|------|
| POST | `/api/v1/admin/live-order/accounts/{uba}/arm` | ARM (응답에 arm_token 1회) |
| POST | `/api/v1/admin/live-order/accounts/{uba}/disarm` | DISARM |
| GET | `/api/v1/admin/live-order/accounts/{uba}/arm` | ARM 상태 |
| GET | `/api/v1/admin/live-order/dashboard` | LIVE/ARM/Kill/Broker/Orders |
| POST | `/api/v1/admin/live-order/broker-disconnect/{code}` | Broker Down 시뮬레이션 |
| GET | `/api/v1/user/live-order/dashboard` | 사용자 읽기 전용 |

## Audit / Telegram

`LIVE_ARM`, `LIVE_DISARM`, `LIVE_ARM_EXPIRED`, `OPEN_ORDER_LIMIT`, `SLIPPAGE_REJECT`, `POSITION_MISMATCH`, `CASH_MISMATCH`, `BROKER_DISCONNECTED`, `BROKER_RECOVERED`, `LOOP_DETECTED`, `ANOMALY_ORDER_RATE`, `KILL_SWITCH_ACTIVATE`

## Frontend

- Admin `/admin/dashboard` — LIVE 운영 보호 카드
- Admin `/admin/risk` — ARM / DISARM 버튼
- User `/user/risk` — LIVE + ARM 읽기 전용

## Operation Rehearsal

`--full` 또는 `--risk` 시 `live_protection` suite:

- ARM → 만료 → Reject
- Slippage Reject
- Loop Detect
- Broker Down → LIVE OFF / 복구 시 ARM 필요
- Position Mismatch → Kill Switch

## 관련 코드

- `src/stock_platform/trading/live_arm_service.py`
- `src/stock_platform/trading/broker_disconnect_protector.py`
- `src/stock_platform/trading/live_ops_dashboard.py`
- `src/stock_platform/order/live_safety_pipeline.py`
- `src/stock_platform/order/post_fill_verifier.py`
- `src/stock_platform/order/post_fill_runner.py`
- `src/stock_platform/operations/rehearsal/checks/live_protection.py`
- `tests/test_step8_8_live_production_protection.py`

## 검증 원칙

실계좌 주문은 이 STEP에서 발생시키지 않는다. Mock / 단위 / Rehearsal만 사용.
