# STEP 9-4 — UBA 58 ARM Enable Only

## 1. ARM 목적

LIVE ON 이후 **단기 무장(ARM)** 만 켠다.  
ARM ON ≠ Scheduler 시작 ≠ 즉시 주문. 주문은 ARM 토큰 + 별도 실행 승인(STEP 9-5+)이 필요하다.

## 2. LIVE와 ARM 차이

| | LIVE | ARM |
|--|------|-----|
| 의미 | 계좌 LIVE 허용 플래그 | TTL 무장 + 토큰 |
| API | `PUT .../live-order/accounts/{uba}` | `POST .../arm` |
| 본 STEP | ON 유지 | **OFF→ON** |
| Audit | `LIVE_APPROVED` | `LIVE_ARM` |

## 3. ARM과 Scheduler 차이

Trading Scheduler PAUSE/PAUSED면 자동 주문 job이 돌지 않는다.  
ARM Enable API는 Scheduler를 시작하지 않는다.

## 4. ARM과 Runtime 차이

Strategy Runtime idle/paused면 전략 평가·주문 경로가 없다.  
ARM Enable API는 Runtime Resume을 호출하지 않는다.

## 5. 사전 조건

- LIVE=true (STEP 9-3 PASS_LIVE_ENABLED 증거)
- ARM=false, Pause OFF, Credential VERIFIED
- Recovery RUNNING/RUNNING, stale=false, latest SUCCESS
- Conflict ACTIVE/PENDING/UNSAFE=0
- Open/Pending/Post-fill pending=0
- Kill GLOBAL/USER/UBA INACTIVE, Health HEALTHY
- Trading Scheduler PAUSE/PAUSED, Strategy Runtime idle

## 6. Admin 승인 경계

- Admin 인증 + 계좌 접근
- reason / correlation_id 필수
- 위 사전조건 게이트 (`enforce_gates=True`)
- **직접 DB UPDATE 금지**
- LIVE/Scheduler/Runtime/주문 API 호출 금지

## 7. reason 정책

`UPBIT_5000_LIVE_ENABLED_OPERATOR_APPROVED_ARM_ENABLE`

## 8. correlation_id 정책

`step9-4-arm-<hex>` — API 1회·Audit 바인딩.

## 9. Audit 정책

공식 이벤트: **`LIVE_ARM`** (LIVE Enable `LIVE_APPROVED`와 분리)

포함: actor, actor_role, user_id, UBA, broker_code, previous_arm, new_arm, live=true,  
Scheduler/Runtime 상태, reason, correlation_id, expires_at  
**금지:** arm_token 원문, Access/Secret Key, 서명

## 10. LIVE ON + ARM ON + Scheduler PAUSED 안전성

자동 주문은 Scheduler가 트리거해야 한다. PAUSED이면:

- `realtime_trading_scheduler.scheduler.running == False`
- Strategy Runtime idle
- create_order / Broker submit = 0

공식 차단 표기: **`TRADING_SCHEDULER_PAUSED`**

## 11. 자동 주문 차단 구조

```
LIVE gate → ARM+token gate → Risk → Outbox/Broker
         ↑
Scheduler PAUSED = 전략/자동 경로 미기동 (본 STEP 보호)
```

수동 주문 API를 운영 UBA에 호출하지 않는다.

## 12. Idempotency

이미 ARM(유효 TTL)이면 `already_armed=true`, 토큰 재발급·Audit 없음.

## 13. ARM Disable 비상 절차

```http
POST /api/v1/admin/live-order/accounts/58/disarm
{ "reason": "...", "correlation_id": "...", "turn_live_off": false }
```

- ARM만 OFF, **LIVE 유지** (turn_live_off=false)
- Scheduler/Runtime 미변경
- Audit: `LIVE_DISARM`

긴급 시 `turn_live_off=true`로 LIVE까지 내릴 수 있으나 본 STEP에서는 실행하지 않는다.

## 14. 장애 시 대응

- Precheck 실패 → ARM 중단
- ARM 후 Scheduler RUNNING/주문 증가 → 즉시 disarm (+ 필요 시 LIVE OFF / Kill)
- ARM TTL 만료 시 기존 계약: **LIVE OFF** (Fail Closed) — STEP 인계 전 재ARM 필요

## 15. STEP 9-5 인계 조건

- LIVE=true, ARM=true (유효), Scheduler PAUSED, Pause OFF
- Open=0, Recovery 정상, ARM Audit 존재
- **Scheduler START·실주문은 별도 명시 승인 전까지 금지**

TTL: 운영 Enable 시 `ttl_seconds=3600` (최대). 만료 전 STEP 9-5 진행 권장.

스크립트: `scripts/step9_4_arm_enable.py`  
리포트: `E:\StockTrading\reports\step9_4_arm_enable.json`
