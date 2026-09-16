# STEP 9-6 — UBA 58 Upbit KRW-BTC MARKET BUY 5,000 KRW

## 결과

**PASS_ORDER_FILLED** — 운영자 승인 범위 내 시장가 매수 1건이 Upbit에 접수·체결됨.

| 항목 | 값 |
|------|-----|
| UBA | 58 |
| Broker UUID | `00175133-d943-42fa-aa33-d432d81e3499` |
| Identifier | `spu-1d87a5643b50c9c6a513bb86c205894b` |
| Client Order ID | `S96-e170adae7f7d` |
| DB order_id | 250 |
| 체결 수량 | 0.00005254 BTC |
| 체결가 | 95,150,000 KRW |
| 체결금액 | 4,999.181 KRW |
| 수수료 | 2.4995905 KRW |

## 실행 제약 준수

- 브로커 실주문 **1회** (Outbox #157)
- 자동 retry / 재주문 없음
- Outbox #156은 브로커 도달 전 `KeyError: order_id`로 실패 (잔고 불변)

## 잔고 전/후

| | KRW | BTC |
|--|-----|-----|
| 전 | 173920.37504136 | 0.01017696 |
| 후 | 168918.69445086 | 0.0102295 |

## 코드 수정

- `OrderExecutionService` outbox payload에 `order_id` 포함
- `OrderOutboxWorker` payload `setdefault("order_id")` 보강

## 운영 메모

- `GLOBAL_LIVE_ORDER_ENABLED` / `UPBIT_LIVE_ORDER_ENABLED` = true (env)
- Live Trading Transition Activation #1 활성 (UPBIT / UBA 58)
- 투자비중·일손실 게이트는 본 STEP 승인 주문용 임시 완화 후 실행
- Upbit 시장가 매수 응답 `state=cancel` + `executed_volume>0` = 잔여 KRW 취소(정상)
- Snapshot BTC 수량은 브로커 잔고 대비 stale 가능 → 별도 refresh 권장
- Post-fill verification row = 0

### STEP 10-1 해결 연결

위 Snapshot/Post-fill/cancel+fill 후속 누락은  
[STEP10_1_POST_FILL_SNAPSHOT_SYNC.md](STEP10_1_POST_FILL_SNAPSHOT_SYNC.md) 에서 자동 경로로 수정됨.  
Scheduler desired PAUSE 복귀(항목 6)는 STEP 10-2 범위.

## 보고 파일

- `E:\StockTrading\reports\step9_6_market_buy.json`
- `E:\StockTrading\reports\step9_6_completion_facts.json`
