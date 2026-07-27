# STEP 9-1 — Final Operational Preflight (Read Only)

## 목적

STEP 8 완료 후 LIVE/ARM/주문 직전 최종 조회 점검. 변경 작업 없음.

## 금지

LIVE ON, ARM, Trading Scheduler START, Runtime Resume, 실주문, Import/Ignore, Pause 변경, DB UPDATE.

## 스크립트

`scripts/step9_1_final_operational_preflight.py`  
리포트: `E:\StockTrading\reports\step9_1_final_operational_preflight.json`

## 판정 기준

- Account Pause OFF, Credential VERIFIED
- Recovery RUNNING·stale=false·SUCCESS
- ACTIVE_REVIEW=0, HISTORICAL_PRESERVED=20
- Broker Open=0, KRW ≥ 5,000(+fee)
- Trading Scheduler PAUSED, LIVE OFF, ARM OFF
- Kill Switch INACTIVE

## STEP 9-2 인계

Preflight PASS여도 LIVE/ARM/Scheduler/주문은 별도 승인 필요.
