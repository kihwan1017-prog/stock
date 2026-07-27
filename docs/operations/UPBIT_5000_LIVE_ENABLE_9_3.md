# STEP 9-3 — UBA 58 LIVE Enable Only

## 1. LIVE Enable 목적

Dry Run(STEP 9-2) PASS 후 **주문 승인 없이** `live_order_enabled`만 ON 한다.  
LIVE ON ≠ 주문 가능. ARM·Scheduler·Runtime이 꺼져 있으면 주문 경로가 차단된다.

## 2. LIVE와 ARM 차이

| | LIVE | ARM |
|--|------|-----|
| 의미 | 계좌 LIVE 주문 **허용 플래그** | 단기 무장(토큰·TTL) |
| API | `PUT /api/v1/admin/live-order/accounts/{uba}` | `/arm` 별도 |
| 본 STEP | **ON** | **OFF 유지** |
| 주문 | ARM 없으면 `LIVE_NOT_ARMED` | 토큰 일치 시 통과 |

## 3. LIVE와 Scheduler 차이

Trading Scheduler가 PAUSE/PAUSED이면 전략 자동 주문 생성이 없다.  
LIVE Enable API는 Scheduler를 시작하지 않는다.

## 4. LIVE와 Runtime 차이

Strategy Runtime이 paused/stopped이면 자동 주문 경로가 돌지 않는다.  
LIVE Enable API는 Runtime Resume을 호출하지 않는다.

## 5. 사전 조건

- UBA=58, active, Pause OFF, Credential VERIFIED
- LIVE=false → true (본 단계), ARM=false
- Recovery RUNNING/RUNNING, stale=false, latest run SUCCESS
- Conflict ACTIVE/PENDING/UNSAFE=0
- Broker/DB Open·Submission Unknown·Cancel/Replace Pending=0
- Kill Switch GLOBAL/USER/UBA INACTIVE
- Broker/system health HEALTHY
- Trading Scheduler PAUSE/PAUSED

## 6. Dry Run 증거 검증

`E:\StockTrading\reports\step9_2_upbit_5000_dry_run.json`

필수: `PASS_DRY_RUN`, UBA=58, KRW-BTC, amount=5000, submit/DB insert=0,  
timestamp 72h 이내. 불일치 시 LIVE Enable 중단 (`dry_run_*` 코드).

모듈: `stock_platform.trading.step9_3_dry_run_evidence`

## 7. Admin 승인 경계

- Admin 인증 + 계좌 접근 검증
- reason / correlation_id 필수 (Enable)
- Pause·Conflict·Open·Credential·Kill·Health·Scheduler PAUSED·ARM OFF 게이트
- **직접 DB UPDATE 금지**
- ARM/Scheduler/Runtime/주문 API 호출 금지

## 8. reason 정책

고정 운영 reason:

`UPBIT_5000_DRY_RUN_PASSED_OPERATOR_APPROVED_LIVE_ENABLE`

## 9. correlation_id 정책

STEP 9-3 전용 ID (`step9-3-live-<hex>`). API 1회 호출에 바인딩. Audit에 기록.

## 10. Audit 정책

공식 이벤트: **`LIVE_APPROVED`** (ARM Audit `LIVE_ARM`과 분리)

포함: actor, actor_role, user_id, UBA, broker_code, previous_live, new_live, arm=false, reason, correlation_id, occurred_at  
금지: Access/Secret Key, 전체 토큰, 서명

## 11. LIVE ON + ARM OFF 주문 차단

공식 reason code: **`LIVE_NOT_ARMED`**  
(파이프라인 `validate_arm_token` / outbox `PermissionError("LIVE_NOT_ARMED")`)  
Broker Adapter·DB order 생성 전 차단.

## 12. Idempotency

이미 LIVE=true면 `already_enabled=true`, `live_changed=false`, **추가 Audit 없음**.

## 13. Rollback / Disable

`PUT .../accounts/58` with `live_order_enabled=false` (Admin).  
ARM/Scheduler 상태는 건드리지 않음.

## 14. 장애 시 대응

- Precheck 실패 → Enable 중단, reason 코드 확인
- Enable 후 ARM이 켜졌거나 Scheduler가 RUNNING이면 **즉시 Disable + 원인 조사** (본 계약 위반)
- 주문/체결 증가 감지 시 Kill Switch / Pause / Disable

## 15. STEP 9-4 인계 조건

- LIVE=true, ARM=false, Scheduler PAUSED, Pause OFF
- Open/Pending=0, Recovery 정상
- LIVE Enable Audit 존재
- **ARM ON·실주문은 별도 명시 승인(STEP 9-4) 전까지 금지**

스크립트: `scripts/step9_3_live_enable.py`  
리포트: `E:\StockTrading\reports\step9_3_live_enable.json`
