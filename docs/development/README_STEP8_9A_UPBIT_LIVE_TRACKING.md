# STEP 8-9A — Upbit LIVE Broker 최종 확정 경로

## 목적

Outbox 완료 ≠ Broker Accepted. Cancel Requested ≠ Canceled.  
Mock/Fake Adapter로 제출·조회·취소 확정 경로 완성. 실주문 금지.

## 핵심

- `internal_status` / `broker_order_status` 분리
- `live-smoke:{run_id}` identifier · UUID 저장
- Timeout → identifier 조회 (재전송 금지)
- Broker Tracking Scheduler (거래 Scheduler와 분리)
- Admin Cancel → Outbox CANCEL → Broker 재조회
- UNKNOWN → Manual Review · 신규 주문 차단
- FILLED → Post-fill 전 COMPLETED 금지

## Alembic

`o4e5f6a7b8c9`

## 코드

- `trading/upbit_live_tracking_service.py`
- `trading/upbit_live_tracking_scheduler.py`
- `tests/test_step8_9a_upbit_live_tracking.py`

## Vitest flaky 수정

상태 색상 상수를 Panel에서 분리 (`*StatusColors.ts`) — 병렬 import 타임아웃 해소.
