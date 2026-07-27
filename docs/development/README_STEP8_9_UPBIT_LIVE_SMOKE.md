# STEP 8-9 — Upbit 소액 LIVE Preflight / Smoke

## 목적

업비트 실계좌 소액 **지정가 1건** 검증을 위한 Preflight·CLI·Admin/User API·화면·Runbook.  
개발 STEP에서는 **실주문(`--execute-live`) 실행 금지**.

## 핵심 제약

- Upbit only / LIMIT only / ≤ 10,000 KRW / dry-run default
- 실주문: `--execute-live` + `UPBIT-LIVE-ONE-ORDER` + `arm_token`
- finally: DISARM + LIVE OFF + UBA Pause 유지
- Adapter·Safety Pipeline 우회 금지

## DB

Alembic `n3d4e5f6a7b8` — `trading.live_validation_run`

## 코드

- `trading/upbit_live_preflight_service.py`
- `trading/upbit_live_smoke_service.py`
- `trading/upbit_live_smoke_constants.py`
- `api/v1/upbit_live_validation.py`
- `scripts/run_upbit_live_smoke_test.py`
- Rehearsal: `operations/rehearsal/checks/upbit_live_smoke.py`
- Runbook: `docs/operations/UPBIT_SMALL_LIVE_VALIDATION_RUNBOOK.md`

## 테스트

`tests/test_step8_9_upbit_live_smoke.py` (Mock only)
