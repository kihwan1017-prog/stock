# STEP 9-5 — Trading Scheduler Start Only / No Order

## 1. Scheduler Start 목적

LIVE+ARM 상태에서 **Trading Scheduler만** START하여 heartbeat/tick이 도는지 확인한다.  
주문·전략·Runtime은 계속 비활성.

## 2. Scheduler와 Runtime 차이

| | Trading Scheduler | Strategy/Execution Runtime |
|--|-------------------|----------------------------|
| API | `POST /api/v1/admin/trading-scheduler/start` | `/realtime-strategy/start`, `/realtime-execution/start` |
| 본 STEP | **START** | **미기동** |
| 역할 | 세션 타임라인·heartbeat | 신호·주문 실행 |

## 3. Scheduler와 전략 Deployment 차이

active account_strategy_link / strategy runtime = 0 이어야 Start 가능.  
Scheduler Start는 Deployment를 활성화하지 않는다.

## 4. LIVE·ARM과 Scheduler 관계

- LIVE/ARM ON은 주문 **허용 조건**이지 Scheduler Start 자체 주문이 아님
- Start는 LIVE/ARM 값·ARM TTL을 **변경·갱신하지 않음**

## 5. ARM TTL 영향

Start 전 `remaining_ttl >= 120초` (및 STEP 예상 시간) 필수.  
부족하면 Start 중단. **자동 재ARM 금지.**  
만료 시 기존 Fail Closed(LIVE OFF) — STEP 9-6 불가.

## 6. Recovery COOLDOWN 정상 판정

`Actual=COOLDOWN`이어도 다음이면 정상:

- running=true, stale=false
- current active error 없음
- latest run SUCCESS, failed_accounts=0

## 7. 사전 조건

Pause OFF, LIVE/ARM ON, Credential VERIFIED, Health HEALTHY,  
Conflict/Open/Pending=0, Kill INACTIVE, strategy idle, runners OFF.

## 8. active strategy=0 요구

Start 게이트에서 active runtime / active links > 0 이면 차단.

## 9. Admin 승인 경계

- reason / correlation_id / user_broker_account_id 필수
- 직접 DB UPDATE 금지
- Runner 자동 기동 금지 (MARKET_OPEN 분리 계약)

## 10. reason / correlation_id

reason: `UPBIT_5000_LIVE_ARMED_OPERATOR_APPROVED_SCHEDULER_START_NO_ORDER`  
correlation: `step9-5-sched-<hex>`

## 11. No-Order 관찰

Start 후 ≥25초 관찰 (heartbeat 10초 → tick ≥2).  
strategy/execution runner running=0, order/exec insert=0.

## 12. Audit

`TRADING_SCHEDULER_STARTED` — LIVE/ARM Audit와 분리. arm_token 금지.

## 13. Idempotency

이미 RUNNING이면 `already_running=true`, 중복 Audit 없음.

## 14. 비상 Pause/Disarm

```http
POST /api/v1/admin/trading-scheduler/pause
{ "reason":"...", "correlation_id":"..." }
POST /api/v1/admin/live-order/accounts/58/disarm
{ "reason":"...", "correlation_id":"...", "turn_live_off":false }
```

예상치 못한 주문 경로 감지 시: Pause → Disarm → (필요 시) Pause/Kill/LIVE OFF.

## 15. STEP 9-6 인계

Scheduler RUN/RUNNING + LIVE/ARM ON + runners idle + 주문 0 + ARM TTL 충분.  
실주문·전략 활성화는 **별도 승인** 전까지 금지.

스크립트: `scripts/step9_5_trading_scheduler_start.py`  
리포트: `E:\StockTrading\reports\step9_5_trading_scheduler_start.json`
